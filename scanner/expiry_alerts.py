"""Expiry alerts for the Upstox analytics token (docs/designs/fundamentals-upstox-secondary.md,
"Analytics token expiry alert"; docs/designs/secrets-and-roles.md, decision 14).

Rules
- One message per run at most. The most urgent alert that is due and not yet sent is the one sent,
  so a missed daily check cannot produce a burst.
- Alert kinds: d30 (30 days before), d7, d1, d0 (expiry day). After expiry: no expiry alert; the
  authorisation alert (`alert_auth_failure`) covers that case.
- A row in token_alert_sent is written only after Telegram accepts the message. A failed send is
  retried on the next run.
- The message carries the secret name and the dates only. Never the token value, the bot token or the
  request URL (the URL contains the bot token, so errors are raised without it).

The bot token and chat ID are read from app_secret (`telegram_bot_token`, `telegram_chat_id`).
If either is missing the check reports `not_configured` and sends nothing.
"""
from __future__ import annotations

import datetime as dt

from . import app_secrets

SECRET_NAME = "upstox_analytics_token"
BOT_TOKEN_NAME = "telegram_bot_token"
CHAT_ID_NAME = "telegram_chat_id"
TELEGRAM_TIMEOUT_S = 15
# (kind, days before expiry). Order: most urgent first.
OFFSETS = (("d0", 0), ("d1", 1), ("d7", 7), ("d30", 30))


class AlertSendError(RuntimeError):
    """Telegram did not accept the message. The message never includes the URL or the token."""


def due_kind(expires_on: dt.date, today: dt.date) -> str | None:
    """The most urgent expiry alert that applies today, or None. Past expiry gives None."""
    days = (expires_on - today).days
    if days < 0:
        return None
    for kind, limit in OFFSETS:  # most urgent first: the tightest window that still applies
        if days <= limit:
            return kind
    return None


def _message(name: str, expires_on: dt.date, kind: str, today: dt.date) -> str:
    days = (expires_on - today).days
    when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    return f"Upstox analytics token '{name}' expires on {expires_on.isoformat()} ({when}). Renew it on the Upstox Developer Apps page and update it in the secret store."


def _auth_message(name: str, status: int) -> str:
    return (f"Upstox rejected the analytics token '{name}' (HTTP {status}). It may have been revoked "
            "or regenerated elsewhere. Check it in the secret store.")


def _already_sent(conn, name: str, expires_on: dt.date, kind: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM token_alert_sent WHERE secret_name = %s AND expires_on = %s AND alert_kind = %s",
        (name, expires_on, kind)).fetchone() is not None


def _record(conn, name: str, expires_on: dt.date, kind: str) -> None:
    conn.execute(
        "INSERT INTO token_alert_sent (secret_name, expires_on, alert_kind) VALUES (%s, %s, %s) "
        "ON CONFLICT DO NOTHING", (name, expires_on, kind))


def send_telegram(bot_token: str, chat_id: str, text: str, post=None) -> None:
    """Send one message with Telegram Bot API sendMessage. No polling."""
    if post is None:
        import requests
        post = requests.post
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = post(url, json={"chat_id": chat_id, "text": text}, timeout=TELEGRAM_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - exception text can contain the URL and so the bot token
        raise AlertSendError("telegram request failed") from None
    if resp.status_code != 200:
        raise AlertSendError(f"telegram returned HTTP {resp.status_code}")
    try:
        ok = bool(resp.json().get("ok"))
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        raise AlertSendError("telegram did not accept the message")


def _telegram_config(conn, key: bytes) -> tuple[str, str] | None:
    try:
        return (app_secrets.get_value(conn, key, BOT_TOKEN_NAME),
                app_secrets.get_value(conn, key, CHAT_ID_NAME))
    except app_secrets.SecretNotFound:
        return None


def check_expiry(conn, key: bytes, today: dt.date, post=None) -> dict:
    """Daily check. Returns a status dict with no secret values in it. Caller commits."""
    meta = app_secrets.get_meta(conn, SECRET_NAME)
    if meta is None:
        return {"status": "no_token"}
    expires_on = meta["expires_on"]
    if expires_on is None:
        return {"status": "no_expiry_date"}
    kind = due_kind(expires_on, today)
    if kind is None:
        return {"status": "not_due"}
    if _already_sent(conn, SECRET_NAME, expires_on, kind):
        return {"status": "already_sent", "kind": kind}
    config = _telegram_config(conn, key)
    if config is None:
        return {"status": "not_configured", "kind": kind}
    try:
        send_telegram(config[0], config[1], _message(SECRET_NAME, expires_on, kind, today), post=post)
    except AlertSendError as exc:
        return {"status": "send_failed", "kind": kind, "reason": str(exc)}
    _record(conn, SECRET_NAME, expires_on, kind)
    return {"status": "sent", "kind": kind}


def alert_auth_failure(conn, key: bytes, today: dt.date, status_code: int, post=None) -> dict:
    """Call when a fundamentals request returns 401 or 403. Sends once per expiry date."""
    if status_code not in (401, 403):
        return {"status": "not_an_auth_error"}
    meta = app_secrets.get_meta(conn, SECRET_NAME)
    if meta is None:
        return {"status": "no_token"}
    expires_on = meta["expires_on"] or today
    if _already_sent(conn, SECRET_NAME, expires_on, "auth"):
        return {"status": "already_sent", "kind": "auth"}
    config = _telegram_config(conn, key)
    if config is None:
        return {"status": "not_configured", "kind": "auth"}
    try:
        send_telegram(config[0], config[1], _auth_message(SECRET_NAME, status_code), post=post)
    except AlertSendError as exc:
        return {"status": "send_failed", "kind": "auth", "reason": str(exc)}
    _record(conn, SECRET_NAME, expires_on, "auth")
    return {"status": "sent", "kind": "auth"}
