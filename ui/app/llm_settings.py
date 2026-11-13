"""LLM provider and model settings for the UI (LC3). Router prefix /api/llm.

Routes:
  GET  /api/llm/providers                  provider rows with a masked key hint (never a key value)
  POST /api/llm/providers                  add a provider by URL and class; approved starts false
  PUT  /api/llm/settings                   AI_PROVIDER_NAME, AI_MODEL_NAME, AI_PROVIDER_ROUTE and approved flags
  POST /api/llm/keys                       save one provider key, encrypted in app_secret; never echoed
  GET  /api/llm/providers/{id}/models      stub until LC4: 501 not_built_yet
  POST /api/llm/providers/{id}/test        stub until LC4: 501 not_built_yet

Every write route needs the X-Market-Scanner-UI header set to "1" and an Origin equal to
UI_ORIGIN. Missing or wrong values are refused with 403 before the body is read.
Key values are never logged and never returned.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from scanner import app_secrets
from scanner import secret_crypto
from scanner.pg import db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm")

UI_HEADER = "X-Market-Scanner-UI"
UI_ORIGIN = os.environ.get("UI_ORIGIN", "http://localhost:8080")
PROVIDER_ID_RE = r"^[a-z][a-z0-9_]{0,40}$"
_PROVIDER_ID = re.compile(PROVIDER_ID_RE)
CLASSES = ("ollama", "openai_compat", "anthropic_native")
KEYED_CLASSES = ("openai_compat", "anthropic_native")
ROUTE_RE = r"^(native|compat)$"
CLASS_RE = r"^(ollama|openai_compat|anthropic_native)$"
MAX_KEY_LENGTH = 4096
MAX_APPROVALS = 50


def require_ui_write(
    ui_header: Optional[str] = Header(default=None, alias=UI_HEADER),
    origin: Optional[str] = Header(default=None),
) -> None:
    """Guard for every write route: the custom header and the configured UI origin."""
    if ui_header != "1":
        log.info("llm write refused: status 403 (ui header missing)")
        raise HTTPException(status_code=403, detail="ui header required")
    if origin != UI_ORIGIN:
        log.info("llm write refused: status 403 (origin not allowed)")
        raise HTTPException(status_code=403, detail="origin not allowed")


class ProviderIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider_id: str = Field(pattern=PROVIDER_ID_RE)
    display_name: str = Field(min_length=1, max_length=80)
    class_: str = Field(alias="class", pattern=CLASS_RE)
    origin: str = Field(min_length=8, max_length=300)
    list_endpoint: Optional[str] = Field(default=None, max_length=200)


class SettingsIn(BaseModel):
    ai_provider_name: Optional[str] = Field(default=None, pattern=PROVIDER_ID_RE)
    ai_model_name: Optional[str] = Field(default=None, max_length=200)
    ai_provider_route: Optional[str] = Field(default=None, pattern=ROUTE_RE)
    approved: dict[str, bool] = Field(default_factory=dict)


class KeyIn(BaseModel):
    provider_id: str = Field(pattern=PROVIDER_ID_RE)
    api_key: str = Field(min_length=1, max_length=MAX_KEY_LENGTH)


def _check_origin(origin: str, cls: str) -> None:
    """Provider origin: http or https with a host. Keyed classes must use https."""
    try:
        parts = urlsplit(origin)
    except ValueError:
        raise HTTPException(status_code=422, detail="origin is not a valid URL") from None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(status_code=422, detail="origin must be an http or https URL with a host")
    if cls in KEYED_CLASSES and parts.scheme != "https":
        raise HTTPException(status_code=422, detail="keyed providers need an https origin")


@router.get("/providers")
def list_providers():
    """Provider rows. The key is shown only as its masked last four characters."""
    with db.connect() as conn:
        rows = conn.execute(
            'SELECT p.provider_id, p.display_name, p."class", p.origin, p.list_endpoint, '
            "p.approved, p.key_ref, p.key_version, p.updated_at, s.last4 AS key_last4 "
            "FROM llm_provider p LEFT JOIN app_secret s ON s.name = p.key_ref "
            "ORDER BY p.provider_id").fetchall()
    providers = []
    for r in rows:
        item = dict(r)
        item["key_set"] = item["key_last4"] is not None
        providers.append(item)
    return {"providers": providers}


@router.post("/providers", status_code=201, dependencies=[Depends(require_ui_write)])
def add_provider(body: ProviderIn):
    """Add a provider. It starts unapproved; the user turns approval on in settings."""
    _check_origin(body.origin, body.class_)
    if body.list_endpoint is not None and not body.list_endpoint.startswith("/"):
        raise HTTPException(status_code=422, detail="list_endpoint must start with /")
    with db.connect() as conn:
        row = conn.execute(
            'INSERT INTO llm_provider (provider_id, display_name, "class", origin, list_endpoint, '
            "approved, updated_at) VALUES (%s, %s, %s, %s, %s, false, now()) "
            "ON CONFLICT (provider_id) DO NOTHING RETURNING provider_id",
            (body.provider_id, body.display_name, body.class_, body.origin,
             body.list_endpoint)).fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="provider already exists")
        conn.commit()
    return {"provider_id": body.provider_id, "class": body.class_, "approved": False}


@router.put("/settings", dependencies=[Depends(require_ui_write)])
def put_settings(body: SettingsIn):
    """Save the active provider, model and route, and per-provider approval flags.

    A field left out (null) is not changed. An empty ai_model_name is allowed: the scanner
    then stops each run with model_not_set until a model is typed.
    """
    if len(body.approved) > MAX_APPROVALS:
        raise HTTPException(status_code=422, detail="too many approval flags")
    for pid in body.approved:
        if not _PROVIDER_ID.fullmatch(pid):
            raise HTTPException(status_code=422, detail="approval key is not a valid provider_id")

    settings = {
        "AI_PROVIDER_NAME": body.ai_provider_name,
        "AI_MODEL_NAME": body.ai_model_name,
        "AI_PROVIDER_ROUTE": body.ai_provider_route,
    }
    settings = {k: v for k, v in settings.items() if v is not None}
    with db.connect() as conn:
        for key, value in settings.items():
            conn.execute(
                'INSERT INTO ai_setting ("key", value, updated_at) VALUES (%s, %s, now()) '
                'ON CONFLICT ("key") DO UPDATE SET value = EXCLUDED.value, updated_at = now()',
                (key, value))
        for pid, approved in body.approved.items():
            conn.execute(
                "UPDATE llm_provider SET approved = %s, updated_at = now() WHERE provider_id = %s",
                (approved, pid))
        conn.commit()
    return {"saved_settings": sorted(settings), "approval_updates": len(body.approved)}


@router.post("/keys", dependencies=[Depends(require_ui_write)])
def save_key(body: KeyIn):
    """Encrypt and store one provider key, then bump llm_provider.key_version.

    The response has the provider id, the key_ref and the masked last four characters.
    The plaintext is passed to the encrypted store and nowhere else.
    """
    value = body.api_key.strip()
    if not value:
        raise HTTPException(status_code=422, detail="api_key is empty")
    try:
        master = secret_crypto.load_master_key()
    except Exception as exc:  # fail closed; name the error type only, never the key
        log.error("llm key save: status 503 (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="secrets_unavailable") from None

    key_ref = f"llm_key_{body.provider_id}"
    with db.connect() as conn:
        app_secrets.put(conn, master, key_ref, value,
                        created_on=dt.date.today(), expires_on=None, updated_by="ui")
        conn.execute(
            "UPDATE llm_provider SET key_ref = %s, key_version = key_version + 1, "
            "updated_at = now() WHERE provider_id = %s",
            (key_ref, body.provider_id))
        conn.commit()
    log.info("llm key saved for provider %s", body.provider_id)
    return {"provider_id": body.provider_id, "key_ref": key_ref,
            "last4": app_secrets.last4(value)}


@router.get("/providers/{provider_id}/models")
def list_models(provider_id: str = Path(pattern=PROVIDER_ID_RE)):
    """Model list through llm-client. Not built until LC4."""
    return JSONResponse(status_code=501, content={"error": "not_built_yet"})


@router.post("/providers/{provider_id}/test", dependencies=[Depends(require_ui_write)])
def test_provider(provider_id: str = Path(pattern=PROVIDER_ID_RE)):
    """One test call through llm-client. Not built until LC4."""
    return JSONResponse(status_code=501, content={"error": "not_built_yet"})
