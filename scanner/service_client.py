"""Client for the UI's internal secrets API (secrets S5).

fetch_secret() asks the UI for one app secret with this service's bearer token. The token
comes from a file (SERVICE_TOKEN_FILE), never from the environment or the repo. Errors
never include the token, the response body or the value.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TOKEN_FILE = "/run/app-keys/collector_token"
DEFAULT_BASE_URL = "http://ui:8080"


class SecretUnavailable(RuntimeError):
    """A service secret could not be fetched. The message names the cause, never a secret."""


def _read_token(token_file: str) -> str:
    try:
        with open(token_file, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        token = ""
    if not token:
        raise SecretUnavailable("service token not configured")
    return token


def fetch_secret(name: str, *, token_file: str | None = None, base_url: str | None = None,
                 timeout: float = 10) -> str:
    if token_file is None:
        token_file = os.environ.get("SERVICE_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    if base_url is None:
        base_url = os.environ.get("SECRETS_API_URL", DEFAULT_BASE_URL)

    token = _read_token(token_file)
    url = base_url.rstrip("/") + "/internal/secrets/" + urllib.parse.quote(name, safe="")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise SecretUnavailable(f"secrets API returned HTTP {e.code} for {name}") from None
    except (urllib.error.URLError, OSError):
        raise SecretUnavailable("secrets API unreachable") from None

    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        raise SecretUnavailable(f"secrets API returned an unreadable response for {name}") from None

    value = data.get("value") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value:
        raise SecretUnavailable(f"secrets API returned no value for {name}")
    return value
