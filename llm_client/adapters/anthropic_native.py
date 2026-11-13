"""Anthropic Messages API adapter (anthropic_native class, keyed).

System messages are joined into the top-level "system" field. Structured
output uses output_config.format. temperature, top_p and top_k are never sent:
from anthropic-version 2026-10-21 the API rejects them with 400.
options is not forwarded; it is reserved for the ollama class.
"""

from typing import Any

ANTHROPIC_VERSION = "2026-10-21"


def build_url(origin: str) -> str:
    return str(origin).rstrip("/") + "/v1/messages"


def build_headers(key: str) -> dict[str, str]:
    return {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def build_payload(req: dict) -> dict[str, Any]:
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    for msg in req["messages"]:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            messages.append({"role": msg["role"], "content": msg["content"]})

    body: dict[str, Any] = {
        "model": req["model"],
        "messages": messages,
        "max_tokens": req["max_tokens"],
    }
    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    if req.get("json_schema") is not None:
        body["output_config"] = {
            "format": {"type": "json_schema", "schema": req["json_schema"]},
        }
    return body
