"""Internal broker login endpoints for the server service (broker login, phases 1 and 2: Kite, Upstox).

POST /internal/broker/{broker}/login-url   -> broker login URL carrying a single-use state
POST /internal/broker/{broker}/exchange    -> kite: trade request_token; upstox: trade code;
                                              store the access token
GET  /internal/broker/{broker}/status      -> connected flag and expiry, never the token

Only the server service may call these (its bearer token). Other identities get 403 and
bad tokens 401. Responses carry Cache-Control: no-store. Only the broker, profile and status
code are logged: never a token, api key, api secret, request_token or state.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse

import requests
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from scanner import app_secrets, broker_tokens
from scanner.pg import db
from scanner.secret_crypto import load_master_key
from ui.app import internal_secrets

log = logging.getLogger(__name__)

router = APIRouter()

KITE_LOGIN_URL = "https://kite.zerodha.com/connect/login"
KITE_SESSION_URL = "https://api.kite.trade/session/token"
KITE_TIMEOUT_S = 10
UPSTOX_LOGIN_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
UPSTOX_TIMEOUT_S = 10
UPSTOX_REDIRECT_DEFAULT = "http://127.0.0.1:8081/api/broker/upstox/callback"
STATE_TTL_S = 600
STATE_MAX = 1000
NO_STORE = {"Cache-Control": "no-store"}

_clock = time.monotonic  # tests replace this to move time


class BrokerExchangeError(Exception):
    """The broker did not return an access token. The message never carries the broker body."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _err(status: int, detail: str, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail=detail, headers={**NO_STORE, **(headers or {})})


class _StateStore:
    """In-process single-use login states: {state: (profile, broker, expires_monotonic)}."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, tuple[str, str, float]] = {}

    def issue(self, profile: str, broker: str) -> str:
        state = secrets.token_urlsafe(32)
        now = _clock()
        with self._lock:
            self._purge(now)
            while len(self._items) >= STATE_MAX:
                self._items.pop(next(iter(self._items)))
            self._items[state] = (profile, broker, now + STATE_TTL_S)
        return state

    def consume(self, state: str, broker: str) -> str | None:
        """Pop the state whatever the outcome. Returns the profile when it was valid."""
        now = _clock()
        with self._lock:
            entry = self._items.pop(state, None)
        if entry is None:
            return None
        profile, issued_broker, expires = entry
        if now >= expires or issued_broker != broker:
            return None
        return profile

    def _purge(self, now: float) -> None:
        for key in [k for k, (_, _, exp) in self._items.items() if now >= exp]:
            del self._items[key]


_STATES = _StateStore()


def _server_only(label: str, authorization: str | None) -> None:
    try:
        service = internal_secrets._authenticate(label, authorization)
    except HTTPException as exc:
        raise _err(exc.status_code, exc.detail, exc.headers) from None
    if service != "server":
        log.info("%s: status 403", label)
        raise _err(403, "not allowed for this service")


def _require_broker(broker: str, label: str) -> None:
    if broker not in broker_tokens.BROKERS:
        log.info("%s: status 404", label)
        raise _err(404, "broker not supported")


def _profile(value) -> str:
    try:
        return broker_tokens.validate_profile(value)
    except ValueError:
        raise _err(400, "invalid profile id") from None


async def _json_body(request: Request) -> dict:
    raw = await request.body()
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        raise _err(400, "invalid request body") from None
    if not isinstance(data, dict):
        raise _err(400, "invalid request body")
    return data


def _read_optional(conn, key: bytes, names: list[str]) -> str | None:
    for name in names:
        try:
            return app_secrets.get_value(conn, key, name)
        except app_secrets.SecretNotFound:
            continue
    return None


GLOBAL_KITE_NAMES = {"api_key": "kite_api_key", "api_secret": "kite_api_secret"}


def _names(profile: str, broker: str, kind: str) -> list[str]:
    """Per-profile name. For kite the default profile also falls back to the existing global
    name. Upstox has no global fallback: its credentials are per profile only."""
    names = [broker_tokens.secret_name(profile, broker, kind)]
    global_name = GLOBAL_KITE_NAMES.get(kind) if broker == "kite" else None
    if profile == broker_tokens.DEFAULT_PROFILE and global_name:
        names.append(global_name)
    return names


def _kite_exchange(api_key: str, request_token: str, api_secret: str) -> str:
    checksum = hashlib.sha256(
        (api_key + request_token + api_secret).encode("utf-8")).hexdigest()
    resp = requests.post(
        KITE_SESSION_URL,
        data={"api_key": api_key, "request_token": request_token, "checksum": checksum},
        headers={"X-Kite-Version": "3"},
        timeout=KITE_TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise BrokerExchangeError("kite session call failed")
    token = resp.json()["data"]["access_token"]
    if not isinstance(token, str) or not token:
        raise BrokerExchangeError("kite session call returned no token")
    return token


def _upstox_exchange(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str:
    resp = requests.post(
        UPSTOX_TOKEN_URL,
        data={"code": code, "client_id": client_id, "client_secret": client_secret,
              "redirect_uri": redirect_uri, "grant_type": "authorization_code"},
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"},
        timeout=UPSTOX_TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise BrokerExchangeError("upstox token call failed")
    token = resp.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise BrokerExchangeError("upstox token call returned no token")
    return token


def _upstox_redirect_uri() -> str:
    """Read at call time so a test or a compose override takes effect without a restart."""
    return os.environ.get("UPSTOX_REDIRECT_URI") or UPSTOX_REDIRECT_DEFAULT


def _upstox_login_url(client_id: str, state: str, redirect_uri: str) -> str:
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id,
        "redirect_uri": redirect_uri, "state": state})
    return f"{UPSTOX_LOGIN_URL}?{query}"


def _login_url(label: str, profile: str, broker: str) -> JSONResponse:
    with db.connect() as conn:
        key = load_master_key()
        api_key = _read_optional(conn, key, _names(profile, broker, "api_key"))
    if api_key is None:
        log.info("%s: status 409", label)
        raise _err(409, "api key not configured")
    state = _STATES.issue(profile, broker)
    if broker == "upstox":
        url = _upstox_login_url(api_key, state, _upstox_redirect_uri())
    else:
        redirect_params = urllib.parse.urlencode({"state": state})
        query = urllib.parse.urlencode(
            {"v": 3, "api_key": api_key, "redirect_params": redirect_params})
        url = f"{KITE_LOGIN_URL}?{query}"
    log.info("%s: status 200", label)
    return JSONResponse({"url": url}, headers=NO_STORE)


def _exchange(label: str, broker: str, credential: str, state: str) -> JSONResponse:
    """credential is the kite request_token or the upstox authorization code."""
    profile = _STATES.consume(state, broker)
    if profile is None:
        log.info("%s: status 400", label)
        raise _err(400, "invalid or expired state")

    with db.connect() as conn:
        key = load_master_key()
        api_key = _read_optional(conn, key, _names(profile, broker, "api_key"))
        api_secret = _read_optional(conn, key, _names(profile, broker, "api_secret"))
    if api_key is None or api_secret is None:
        log.info("%s: status 409", label)
        raise _err(409, "api key not configured")

    try:
        if broker == "kite":
            token = _kite_exchange(api_key, credential, api_secret)
        else:
            token = _upstox_exchange(api_key, api_secret, credential, _upstox_redirect_uri())
    except Exception:
        log.info("%s: status 502", label)
        raise _err(502, "broker exchange failed") from None

    now = _utc_now()
    expiry = broker_tokens.token_expiry(broker, now)
    with db.connect() as conn:
        app_secrets.put(
            conn, load_master_key(),
            broker_tokens.secret_name(profile, broker, "access_token"), token,
            created_on=now.astimezone(broker_tokens.IST).date(),
            expires_on=expiry.astimezone(broker_tokens.IST).date(),
            updated_by="broker_login",
        )
    log.info("%s: status 200", label)
    return JSONResponse({"profile_id": profile, "expires_at": expiry.isoformat()},
                        headers=NO_STORE)


def _status(label: str, profile: str, broker: str) -> JSONResponse:
    name = broker_tokens.secret_name(profile, broker, "access_token")
    with db.connect() as conn:
        meta = app_secrets.get_meta(conn, name)
    connected = False
    expires_at = None
    if meta is not None:
        now = _utc_now()
        if not broker_tokens.is_expired(broker, meta["updated_at"], now):
            connected = True
            expires_at = broker_tokens.token_expiry(broker, meta["updated_at"]).isoformat()
    log.info("%s: status 200", label)
    return JSONResponse({"connected": connected, "expires_at": expires_at}, headers=NO_STORE)


@router.post("/internal/broker/{broker}/login-url")
async def broker_login_url(broker: str, request: Request,
                           authorization: str | None = Header(default=None)):
    label = f"broker {internal_secrets._log_safe(broker)} login-url"
    _server_only(label, authorization)
    _require_broker(broker, label)
    body = await _json_body(request)
    profile = _profile(body.get("profile_id", broker_tokens.DEFAULT_PROFILE))
    return await run_in_threadpool(_login_url, label, profile, broker)


@router.post("/internal/broker/{broker}/exchange")
async def broker_exchange(broker: str, request: Request,
                          authorization: str | None = Header(default=None)):
    label = f"broker {internal_secrets._log_safe(broker)} exchange"
    _server_only(label, authorization)
    _require_broker(broker, label)
    body = await _json_body(request)
    # kite sends request_token, upstox sends code. The other body on a route is a 400.
    field = "code" if broker == "upstox" else "request_token"
    credential = body.get(field)
    state = body.get("state")
    if (not isinstance(credential, str) or not credential
            or not isinstance(state, str) or not state):
        log.info("%s: status 400", label)
        raise _err(400, "invalid request")
    return await run_in_threadpool(_exchange, label, broker, credential, state)


@router.get("/internal/broker/{broker}/status")
def broker_status(broker: str, profile_id: str = Query(default=broker_tokens.DEFAULT_PROFILE),
                  authorization: str | None = Header(default=None)):
    label = f"broker {internal_secrets._log_safe(broker)} status"
    _server_only(label, authorization)
    _require_broker(broker, label)
    return _status(label, _profile(profile_id), broker)
