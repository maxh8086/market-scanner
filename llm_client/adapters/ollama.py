"""Request payload for the native Ollama chat endpoint (ollama class, unkeyed).

Streaming is off, output is constrained to JSON, and thinking is disabled
because thinking models return empty content unless thinking is off.
options is sent only when the request carries it.
"""

from typing import Any


def build_payload(req: dict) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": req["model"],
        "messages": req["messages"],
        "stream": False,
        "format": "json",
        "think": False,
    }
    if req.get("options") is not None:
        body["options"] = req["options"]
    return body
