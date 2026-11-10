"""Live checks for app secrets (docs/designs/secrets-and-roles.md, S6).

`secrets_cli test NAME` and `secrets_cli rotate NAME` run one of these before a value is
trusted. Each check makes exactly one read-only request and never sends a message.

Error text never contains a URL, a token or a response body: the exception chain is cut
with `from None`, because a requests exception message can contain the full URL, and the
Telegram URL contains the bot token.
"""
from __future__ import annotations

from typing import Callable

from .upstox import BASE_URL, instrument_key

TELEGRAM_TIMEOUT_S = 15
UPSTOX_TIMEOUT_S = 15
# Public probe instrument (the example key from upstox.py's own docstring). Not personal data.
UPSTOX_PROBE_KEY = instrument_key("INE002A01018")


class SecretCheckFailed(RuntimeError):
    """A live check did not accept the value. The message is safe to print."""


def check_telegram_token(token: str, get: Callable | None = None) -> None:
    """One GET to getMe. Passes on HTTP 200 with JSON ok true."""
    if get is None:
        import requests
        get = requests.get
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        resp = get(url, timeout=TELEGRAM_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - the exception text can contain the URL and so the token
        raise SecretCheckFailed("telegram request failed") from None
    if resp.status_code != 200:
        raise SecretCheckFailed(f"telegram getMe rejected (HTTP {resp.status_code})")
    try:
        ok = resp.json().get("ok") is True
    except Exception:  # noqa: BLE001 - a body that is not JSON counts as rejected
        ok = False
    if not ok:
        raise SecretCheckFailed(f"telegram getMe rejected (HTTP {resp.status_code})")


def check_upstox_token(token: str, get: Callable | None = None) -> None:
    """One GET to the market-quote OHLC endpoint that quote_ohlc uses. Passes on HTTP 200."""
    if get is None:
        import requests
        get = requests.get
    try:
        resp = get(
            f"{BASE_URL}/v3/market-quote/ohlc",
            params={"instrument_key": UPSTOX_PROBE_KEY, "interval": "1d"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=UPSTOX_TIMEOUT_S,
        )
    except Exception:  # noqa: BLE001 - keep the exception text (URL, header) out of the message
        raise SecretCheckFailed("upstox request failed") from None
    code = resp.status_code
    if code == 200:
        return
    if code in (401, 403):
        raise SecretCheckFailed(f"upstox rejected the token (HTTP {code})")
    raise SecretCheckFailed(f"upstox returned HTTP {code}")


CHECKS = {
    "telegram_bot_token": check_telegram_token,
    "upstox_analytics_token": check_upstox_token,
}
