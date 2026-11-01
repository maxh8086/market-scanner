"""Kite Connect login + access-token caching.

Kite access tokens expire at ~6 AM IST the next day, so we cache the
token together with the IST calendar date it was issued on and only
reuse it while that date still matches "today" in IST.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from kiteconnect import KiteConnect

IST = timezone(timedelta(hours=5, minutes=30))
TOKEN_CACHE_PATH = Path(".kite_token")


def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _load_cached_token() -> str | None:
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("date") != _today_ist():
        return None
    return data.get("access_token")


def _save_token(access_token: str) -> None:
    TOKEN_CACHE_PATH.write_text(
        json.dumps({"access_token": access_token, "date": _today_ist()})
    )


def get_kite_client(verbose: bool = False) -> KiteConnect:
    """Return an authenticated KiteConnect client, reusing today's cached token
    or running the interactive login flow if none is cached yet."""
    load_dotenv()
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(
            "KITE_API_KEY / KITE_API_SECRET not set. Copy .env.example to .env "
            "and fill in your Kite Connect app credentials."
        )

    kite = KiteConnect(api_key=api_key)

    cached_token = _load_cached_token()
    if cached_token:
        kite.set_access_token(cached_token)
        if verbose:
            print("Reusing cached access token for today.")
        return kite

    print("\nNo valid access token cached for today. Please log in:")
    print(f"  {kite.login_url()}\n")
    request_token = input("Paste the request_token from the redirect URL: ").strip()

    session = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session["access_token"]
    kite.set_access_token(access_token)
    _save_token(access_token)
    print("Login successful, access token cached for today.\n")
    return kite
