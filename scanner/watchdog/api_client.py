"""Client for the server's watchdog endpoints: GET /internal/due and POST /internal/due/finish.

The bearer token is only ever placed in the Authorization header. It never appears in a URL,
an exception message or a log line. Network and HTTP failures never raise: they come back as
an error kind (see DueResult.error).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

ERR_UNAUTHORIZED = "unauthorized"
ERR_POSTGRES_DOWN = "postgres_down"
ERR_API_UNAVAILABLE = "api_unavailable"
ERR_BAD_RESPONSE = "bad_response"

_SOURCE_RE = re.compile(r"^[a-z0-9_]+$")

Opener = Callable[..., Any]


@dataclass(frozen=True)
class DueSource:
    name: str
    service: str
    reason: str
    request_id: str | None
    order: int


@dataclass(frozen=True)
class DueResult:
    ok: bool
    sources: list[DueSource] = field(default_factory=list)
    error: str | None = None


def _fail(error: str) -> DueResult:
    return DueResult(ok=False, sources=[], error=error)


def _parse_source(item: object) -> DueSource:
    if not isinstance(item, dict):
        raise ValueError("source is not an object")
    name = item.get("name")
    service = item.get("service")
    reason = item.get("reason")
    request_id = item.get("request_id")
    order = item.get("order")
    if not isinstance(name, str) or not isinstance(service, str) or not isinstance(reason, str):
        raise ValueError("source fields are not strings")
    if request_id is not None and not isinstance(request_id, str):
        raise ValueError("request_id is not a string or null")
    if isinstance(order, bool) or not isinstance(order, int):
        raise ValueError("order is not an integer")
    return DueSource(name=name, service=service, reason=reason, request_id=request_id, order=order)


def _status_error(exc: urllib.error.HTTPError) -> str:
    if exc.code == 401:
        return ERR_UNAUTHORIZED
    if exc.code == 503:
        return ERR_POSTGRES_DOWN
    return ERR_API_UNAVAILABLE


def _status_of(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if status is None and hasattr(response, "getcode"):
        status = response.getcode()
    return status


def fetch_due(
    base_url: str,
    token: str,
    timeout_s: float,
    opener: Opener = urllib.request.urlopen,
) -> DueResult:
    """GET <base>/internal/due. Never raises; returns sources sorted by server order."""
    url = base_url.rstrip("/") + "/internal/due"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout_s) as response:
            status = _status_of(response)
            body = response.read()
    except urllib.error.HTTPError as exc:
        return _fail(_status_error(exc))
    except Exception:  # noqa: BLE001 - timeouts, DNS, refused connections, anything else
        return _fail(ERR_API_UNAVAILABLE)

    if status != 200:
        return _fail(ERR_API_UNAVAILABLE)
    try:
        parsed = json.loads(body)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("sources"), list):
            return _fail(ERR_BAD_RESPONSE)
        sources = [_parse_source(item) for item in parsed["sources"]]
    except (ValueError, TypeError, UnicodeDecodeError):
        return _fail(ERR_BAD_RESPONSE)
    sources.sort(key=lambda s: s.order)
    return DueResult(ok=True, sources=sources, error=None)


def finish_killed(
    base_url: str,
    token: str,
    source: str,
    timeout_s: float,
    opener: Opener = urllib.request.urlopen,
) -> bool:
    """POST <base>/internal/due/finish with {"source": ...}. True only on HTTP 200 + JSON object."""
    if not isinstance(source, str) or not _SOURCE_RE.match(source):
        return False
    url = base_url.rstrip("/") + "/internal/due/finish"
    payload = json.dumps({"source": source}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout_s) as response:
            status = _status_of(response)
            body = response.read()
    except Exception:  # noqa: BLE001 - HTTP errors, timeouts, connection failures
        return False
    if status != 200:
        return False
    try:
        return isinstance(json.loads(body), dict)
    except (ValueError, TypeError, UnicodeDecodeError):
        return False
