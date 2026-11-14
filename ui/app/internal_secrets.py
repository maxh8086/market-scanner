"""Internal endpoints for other services on the project network (secrets S5, LC2, S3b).

GET /internal/secrets/{name} returns one app secret to a service that holds its own
bearer token. GET /internal/llm/providers/{provider_id} returns one llm_provider row to
the llm-client service (never key material). Rules, in order:

1. The three token files are read on every request: the collector token file
   (COLLECTOR_TOKEN_FILE), the llm-client token file (LLM_CLIENT_TOKEN_FILE) and the
   server token file (SERVER_TOKEN_FILE). Each token is matched on its own.
   If no token matches and the collector token file is missing, unreadable or empty -> 503.
2. Authorization must be "Bearer <token>" and match one of the token files (constant-time,
   compared in the order collector, llm_client, server) -> else 401. The matching token
   names the service: collector, llm_client or server.
3. Each endpoint has its own allowlist:
   - secrets: collector may read upstox_analytics_token; server may read
     upstox_analytics_token and kite_api_key, and any broker secret named
     broker_<profile>_<broker>_access_token or broker_<profile>_<broker>_api_key
     (names in broker_tokens.SECRET_NAME_RE); llm_client may read names that
     match ^llm_key_[a-z][a-z0-9_]{0,40}$. Any other name -> 403. Broker api_secret
     names are never served to any service. collector and llm_client get 403 for all
     broker_* names.
   - llm providers: llm_client only. Any other service -> 403.
   The global kite_access_token may be stored, but no service is ever served it
   (Decision 16 in docs/designs/secrets-and-roles.md). kite_api_secret is never served either.
4. Secrets are decrypted here, with the master key, and returned with Cache-Control:
   no-store. Secret not stored -> 404. Provider row not found -> 404.
   A broker access token is served only while unexpired (Decision 17, which replaces 16 for
   broker tokens): an expired one is treated as not stored, and is never decrypted.

Only the name and the status code are logged. Never the token or the value.
"""
from __future__ import annotations

import datetime as dt
import hmac
import logging
import os
import re

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from scanner import app_secrets, broker_tokens
from scanner.pg import db
from scanner.secret_crypto import load_master_key

log = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_TOKEN_FILE = "/run/app-keys/collector_token"
DEFAULT_LLM_TOKEN_FILE = "/run/app-keys/llm_client_token"
DEFAULT_SERVER_TOKEN_FILE = "/run/service-tokens/server_token"
SERVICE_ALLOWED = {
    "collector": {"upstox_analytics_token"},
    "server": {"upstox_analytics_token", "kite_api_key"},
}
LLM_KEY_NAME = re.compile(r"llm_key_[a-z][a-z0-9_]{0,40}")
PROVIDER_FIELDS = ("provider_id", "class", "origin", "approved", "key_ref", "key_version")
_LOG_UNSAFE = re.compile(r"[^A-Za-z0-9_.:-]")


def _log_safe(value: str) -> str:
    """Return a log-safe copy of an unauthenticated path parameter.

    Every character outside [A-Za-z0-9_.:-] becomes "?" (so %0A cannot forge a log line)
    and the result is cut to 80 characters.
    """
    return _LOG_UNSAFE.sub("?", str(value))[:80]


def _read_token(env_var: str, default_path: str) -> str:
    path = os.environ.get(env_var, default_path)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _authenticate(label: str, authorization: str | None) -> str:
    """Return the service that owns the bearer token. Raises 503 or 401.

    Each service token is matched on its own. A missing collector token file does not
    block the llm-client token. 503 is raised only when no token matched and the
    collector token file is missing or empty.
    """
    collector = _read_token("COLLECTOR_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    llm = _read_token("LLM_CLIENT_TOKEN_FILE", DEFAULT_LLM_TOKEN_FILE)
    server = _read_token("SERVER_TOKEN_FILE", DEFAULT_SERVER_TOKEN_FILE)
    scheme, _, presented = (authorization or "").partition(" ")
    presented = presented.strip()
    if scheme == "Bearer" and presented:
        raw = presented.encode("utf-8")
        if collector and hmac.compare_digest(raw, collector.encode("utf-8")):
            return "collector"
        if llm and hmac.compare_digest(raw, llm.encode("utf-8")):
            return "llm_client"
        if server and hmac.compare_digest(raw, server.encode("utf-8")):
            return "server"

    if not collector:
        log.warning("%s: status 503 (service token unavailable)", label)
        raise HTTPException(status_code=503, detail="service token unavailable")

    log.info("%s: status 401", label)
    raise HTTPException(status_code=401, detail="unauthorized",
                        headers={"WWW-Authenticate": "Bearer"})


def _secret_name_allowed(service: str, name: str) -> bool:
    if service == "llm_client":
        return LLM_KEY_NAME.fullmatch(name) is not None
    if name in SERVICE_ALLOWED.get(service, set()):
        return True
    if service == "server":
        parsed = broker_tokens.parse_secret_name(name)
        return parsed is not None and parsed[2] in ("access_token", "api_key")
    return False


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _broker_token_usable(conn, name: str) -> bool:
    """False for a broker access token that is not stored or has expired. Reads meta only."""
    parsed = broker_tokens.parse_secret_name(name)
    if parsed is None or parsed[2] != "access_token":
        return True
    meta = app_secrets.get_meta(conn, name)
    if meta is None:
        return False
    return not broker_tokens.is_expired(parsed[1], meta["updated_at"], _utc_now())


@router.get("/internal/secrets/{name}")
def get_internal_secret(name: str, authorization: str | None = Header(default=None)):
    safe = _log_safe(name)
    service = _authenticate(f"internal secret {safe}", authorization)
    if not _secret_name_allowed(service, name):
        log.info("internal secret %s: status 403", safe)
        raise HTTPException(status_code=403, detail="not allowed for this service")

    try:
        with db.connect() as conn:
            if not _broker_token_usable(conn, name):
                raise app_secrets.SecretNotFound(name)
            value = app_secrets.get_value(conn, load_master_key(), name)
    except app_secrets.SecretNotFound:
        log.info("internal secret %s: status 404", safe)
        raise HTTPException(status_code=404, detail="secret not found") from None

    log.info("internal secret %s: status 200", safe)
    return JSONResponse({"name": name, "value": value},
                        headers={"Cache-Control": "no-store"})


@router.get("/internal/llm/providers/{provider_id}")
def get_internal_llm_provider(provider_id: str, authorization: str | None = Header(default=None)):
    label = f"internal llm provider {_log_safe(provider_id)}"
    service = _authenticate(label, authorization)
    if service != "llm_client":
        log.info("%s: status 403", label)
        raise HTTPException(status_code=403, detail="not allowed for this service")

    with db.connect() as conn:
        row = conn.execute(
            'SELECT provider_id, "class", origin, approved, key_ref, key_version '
            "FROM llm_provider WHERE provider_id = %s", (provider_id,)).fetchone()
    if row is None:
        log.info("%s: status 404", label)
        raise HTTPException(status_code=404, detail="provider not found")

    log.info("%s: status 200", label)
    return JSONResponse({k: row[k] for k in PROVIDER_FIELDS},
                        headers={"Cache-Control": "no-store"})
