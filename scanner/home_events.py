"""Exchange filings for the home events feed (spec section 6).

T3a only adds `redact_error`. Later tasks add the feed registry, parsers,
fetch and run logic to this module.
"""
from __future__ import annotations

import re

# Query strings: everything from "?" up to whitespace or a quote/bracket.
_QUERY_RE = re.compile(r"(https?://[^\s'\"<>?]+)\?[^\s'\"<>]*")
# "Bearer <token>" pairs.
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+\S+")
# key=value pairs whose key names a credential.
_SECRET_KV_RE = re.compile(r"(?i)\b(token|secret|password|passwd|apikey|api_key|auth|key)=\S+")
# Long opaque runs (30+ url-safe characters with at least one digit or upper-case letter).
_TOKEN_LIKE_RE = re.compile(r"\b(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{30,}\b|\b(?=[A-Za-z0-9_\-]*[A-Z])[A-Za-z0-9_\-]{30,}\b")


def redact_error(text: str) -> str:
    """Strip query strings and token-like substrings from error text.

    Used before any text goes into a run message, so a feed URL or a token
    never reaches `collector_runs.message`.
    """
    if not text:
        return ""
    out = _QUERY_RE.sub(r"\1", text)
    out = _BEARER_RE.sub(r"\1 <redacted>", out)
    out = _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}=<redacted>", out)
    out = _TOKEN_LIKE_RE.sub("<redacted>", out)
    return out
