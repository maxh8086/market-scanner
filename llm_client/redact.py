"""Scrub text before it leaves the service in a response body or a log line."""

import re

PLACEHOLDER = "[redacted]"
MAX_LENGTH = 200

_AUTH_DIGEST = re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*)digest\s+[^\r\n]*")
_AUTH_HEADER = re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*)((?:bearer|basic)\s+)?[^\s\"',;&]+")
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_URL_QUERY = re.compile(r"(?i)(https?://[^\s\"'<>?]*)\?[^\s\"'<>]*")


def redact(text, secrets=()) -> str:
    s = "" if text is None else str(text)
    for secret in secrets:
        if secret:
            s = s.replace(secret, PLACEHOLDER)
    s = _AUTH_DIGEST.sub(lambda m: m.group(1) + PLACEHOLDER, s)
    s = _AUTH_HEADER.sub(lambda m: m.group(1) + (m.group(2) or "") + PLACEHOLDER, s)
    s = _BEARER_TOKEN.sub("Bearer " + PLACEHOLDER, s)
    s = _URL_QUERY.sub(r"\1", s)
    return s[:MAX_LENGTH]
