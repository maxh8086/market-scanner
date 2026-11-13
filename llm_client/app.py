"""llm-client HTTP app.

POST /v1/chat runs the bearer check, then request validation (422), then the
provider, key, version, origin and route checks in order (first failure wins),
then dispatches to the adapter. Only the openai_compat adapter is built here;
ollama and anthropic_native return 501.
"""

import logging
import os
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from starlette.concurrency import run_in_threadpool

from llm_client.auth import check_bearer
from llm_client.errors import ClientError
from llm_client.redact import redact
from llm_client.registry import UiRegistry

log = logging.getLogger(__name__)

PROVIDER_TIMEOUT_SECONDS = 120.0
KEYED_CLASSES = {"openai_compat", "anthropic_native"}
ROUTE_FOR_CLASS = {"openai_compat": "compat", "anthropic_native": "native", "ollama": "native"}
DEFAULT_PORTS = {"http": 80, "https": 443}
KEY_REF_PREFIX = "llm_key_"
PROVIDER_ID_PATTERN = r"^[a-z][a-z0-9_]{0,40}$"
MODEL_MAX_LENGTH = 200
MAX_TOKENS_LIMIT = 32768
JSON_SCHEMA_NAME = "response"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    content: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(pattern=PROVIDER_ID_PATTERN)
    model: str = Field(max_length=MODEL_MAX_LENGTH)
    route: Literal["native", "compat"]
    messages: list[ChatMessage] = Field(min_length=1)
    json_schema: dict[str, Any] | None = None
    max_tokens: StrictInt = Field(ge=1, le=MAX_TOKENS_LIMIT)
    options: dict[str, Any] | None = None


def _origin_parts(origin):
    """Return (scheme, host, port) for an origin, or None when it cannot be parsed."""
    try:
        parts = urlsplit(str(origin or ""))
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port or DEFAULT_PORTS.get(scheme)
    except ValueError:
        return None
    if not scheme or not host:
        return None
    return scheme, host, port


def _base_url(origin):
    """Build scheme://host[:port] from the origin. The path is never used."""
    scheme, host, port = _origin_parts(origin)
    if ":" in host:
        host = f"[{host}]"
    default = DEFAULT_PORTS.get(scheme)
    netloc = host if port in (None, default) else f"{host}:{port}"
    return f"{scheme}://{netloc}"


def _key_record_ok(key) -> bool:
    """A key record needs a non-empty string value and an int key_version (not bool)."""
    value = key.get("value")
    version = key.get("key_version")
    return (
        isinstance(value, str)
        and bool(value)
        and isinstance(version, int)
        and not isinstance(version, bool)
    )


def _strict_content(data) -> str:
    """Return choices[0].message.content, or raise naming the first missing field."""
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ClientError("strict_check_missing_field:choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        raise ClientError("strict_check_missing_field:message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ClientError("strict_check_missing_field:message.content")
    return content


def _call_openai_compat(provider, key, req: ChatRequest, transport):
    key_value = str(key.get("value") or "")
    url = _base_url(provider["origin"]) + "/v1/chat/completions"
    body: dict[str, Any] = {
        "model": req.model,
        "messages": [m.model_dump() for m in req.messages],
        "max_tokens": req.max_tokens,
    }
    if req.json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": JSON_SCHEMA_NAME,
                "schema": req.json_schema,
                "strict": True,
            },
        }
    headers = {"Authorization": f"Bearer {key_value}"}
    try:
        with httpx.Client(transport=transport, timeout=PROVIDER_TIMEOUT_SECONDS) as client:
            resp = client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        raise ClientError("provider_timeout") from None
    except httpx.HTTPError:
        raise ClientError("provider_unreachable") from None

    if not 200 <= resp.status_code < 300:
        raise ClientError(
            f"provider_rejected:{resp.status_code}",
            detail=redact(resp.text, secrets=[key_value]),
        )
    try:
        data = resp.json()
    except ValueError:
        raise ClientError("strict_check_missing_field:choices") from None
    content = _strict_content(data)
    return {"content": content}


def _run_chat(ui, transport, req: ChatRequest):
    provider = ui.get_provider(req.provider_id)
    if provider is None or not provider.get("approved"):
        raise ClientError("provider_not_approved")

    cls = provider.get("class")
    key = None
    if cls in KEYED_CLASSES:
        if provider.get("key_ref") != KEY_REF_PREFIX + req.provider_id:
            raise ClientError("key_missing", detail=f"key_ref mismatch for provider {req.provider_id}")
        key = ui.get_key(provider.get("key_ref"))
        if key is None or not _key_record_ok(key):
            raise ClientError("key_missing", detail=f"no usable key record for provider {req.provider_id}")
        if key.get("key_version") != provider.get("key_version"):
            raise ClientError("key_stale_version")
        provider_origin = _origin_parts(provider.get("origin"))
        if provider_origin is None or provider_origin != _origin_parts(key.get("origin")):
            raise ClientError("origin_mismatch")
        if provider_origin[0] != "https":
            raise ClientError("origin_not_https")

    if ROUTE_FOR_CLASS.get(cls) != req.route:
        raise ClientError("route_mismatch")

    if cls == "openai_compat":
        return _call_openai_compat(provider, key, req, transport)
    raise ClientError("adapter_not_built")


def _chat_sync(ui, transport, req: ChatRequest):
    try:
        result = _run_chat(ui, transport, req)
    except ClientError as exc:
        log.info(redact(f"chat provider_id={req.provider_id} refused={exc.code}"))
        raise
    log.info(redact(f"chat provider_id={req.provider_id} ok"))
    return result


def _model_blank(raw) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("model"), str) and not raw["model"].strip()


def create_app(chat_token: str, ui, transport=None) -> FastAPI:
    if not isinstance(chat_token, str) or not chat_token:
        raise ValueError("chat_token must be a non-empty string")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ClientError)
    async def _client_error(request: Request, exc: ClientError):
        body: dict[str, Any] = {"error": exc.code}
        if exc.detail is not None:
            body["detail"] = exc.detail
        return JSONResponse(status_code=exc.status, content=body)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/v1/chat")
    async def chat(request: Request):
        check_bearer(request.headers.get("authorization"), chat_token)
        try:
            raw = await request.json()
        except ValueError:
            return JSONResponse(status_code=422, content={"error": "invalid_json"})
        if _model_blank(raw):
            return JSONResponse(status_code=422, content={"error": "model_not_set"})
        try:
            req = ChatRequest.model_validate(raw)
        except ValidationError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "invalid_request",
                    "detail": exc.errors(include_url=False, include_input=False, include_context=False),
                },
            )
        return await run_in_threadpool(_chat_sync, ui, transport, req)

    return app


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def create_app_from_env() -> FastAPI:
    token_file = _required_env("LLM_CHAT_TOKEN_FILE")
    try:
        with open(token_file, encoding="utf-8") as f:
            chat_token = f.read().strip()
    except OSError:
        chat_token = ""
    if not chat_token:
        raise SystemExit("LLM_CHAT_TOKEN_FILE must point to a readable, non-empty token file")
    ui = UiRegistry(
        secrets_api_url=_required_env("SECRETS_API_URL"),
        token_file_path=_required_env("LLM_CLIENT_TOKEN_FILE"),
    )
    return create_app(chat_token=chat_token, ui=ui)
