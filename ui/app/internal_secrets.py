"""Internal secrets endpoint for other services on the project network (secrets S5).

GET /internal/secrets/{name} returns one app secret to a service that holds its own
bearer token. The collector is the only service today. Rules, in order:

1. The token file (COLLECTOR_TOKEN_FILE) is read on every request. Missing, unreadable
   or empty -> 503.
2. Authorization must be "Bearer <token>" and match the file (constant-time) -> else 401.
3. The name must be on that service's allowlist -> else 403.
4. The value is decrypted here, with the master key, and returned with Cache-Control:
   no-store. Not stored -> 404.

Only the name and the status code are logged. Never the token or the value.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from scanner import app_secrets
from scanner.pg import db
from scanner.secret_crypto import load_master_key

log = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_TOKEN_FILE = "/run/app-keys/collector_token"
SERVICE_ALLOWED = {"collector": {"upstox_analytics_token"}}


def _read_expected_token() -> str:
    path = os.environ.get("COLLECTOR_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


@router.get("/internal/secrets/{name}")
def get_internal_secret(name: str, authorization: str | None = Header(default=None)):
    expected = _read_expected_token()
    if not expected:
        log.warning("internal secret %s: status 503 (service token unavailable)", name)
        raise HTTPException(status_code=503, detail="service token unavailable")

    scheme, _, presented = (authorization or "").partition(" ")
    presented = presented.strip()
    if scheme != "Bearer" or not presented or not hmac.compare_digest(
            presented.encode("utf-8"), expected.encode("utf-8")):
        log.info("internal secret %s: status 401", name)
        raise HTTPException(status_code=401, detail="unauthorized",
                            headers={"WWW-Authenticate": "Bearer"})

    service = "collector"  # the only token on file maps to this service
    if name not in SERVICE_ALLOWED[service]:
        log.info("internal secret %s: status 403", name)
        raise HTTPException(status_code=403, detail="not allowed for this service")

    try:
        key = load_master_key()
        with db.connect() as conn:
            value = app_secrets.get_value(conn, key, name)
    except app_secrets.SecretNotFound:
        log.info("internal secret %s: status 404", name)
        raise HTTPException(status_code=404, detail="secret not found") from None

    log.info("internal secret %s: status 200", name)
    return JSONResponse({"name": name, "value": value},
                        headers={"Cache-Control": "no-store"})
