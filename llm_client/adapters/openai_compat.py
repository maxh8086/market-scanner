"""OpenAI-style chat completions adapter (openai_compat class, keyed).

Only scheme, host and port are taken from the origin. The origin path is
ignored, so the URL is always scheme://host[:port]/v1/chat/completions.
options is not forwarded; it is reserved for the ollama class.
"""

from typing import Any
from urllib.parse import urlsplit

JSON_SCHEMA_NAME = "response"
DEFAULT_PORTS = {"http": 80, "https": 443}


def build_url(origin: str) -> str:
    parts = urlsplit(str(origin or ""))
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None or port == DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    return f"{scheme}://{netloc}/v1/chat/completions"


def build_payload(req: dict) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": req["model"],
        "messages": req["messages"],
        "max_tokens": req["max_tokens"],
    }
    if req.get("json_schema") is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": JSON_SCHEMA_NAME,
                "schema": req["json_schema"],
                "strict": True,
            },
        }
    return body
