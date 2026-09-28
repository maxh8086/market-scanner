"""Upstox market-data provider.

This is the MARKET DATA source. Portfolio/holdings stay on Kite (see README
"Architecture"): Upstox's long-lived analytics token is data-only, and the
Kite side is where the actual positions live.

Auth is a long-lived (~1 year) "analytics" access token read from .env as
UPSTOX_ANALYTICS_ACCESS_TOKEN. Unlike Kite Connect there is no daily
interactive request_token paste, which is what makes an unattended scheduled
run practical.

Instruments are addressed by `instrument_key`, which for NSE equities is
`NSE_EQ|{ISIN}`. The NSE constituents CSV already carries an `ISIN Code`
column, so resolution is ISIN-native -- a tradingsymbol rename cannot break a
lookup, unlike the Kite path which matched on `tradingsymbol`.

Everything below was verified live against the API on 2026-09-28; see the
"Verified behaviour" notes on each method for what was actually observed
rather than merely documented.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

import requests
from dotenv import find_dotenv, load_dotenv

BASE_URL = "https://api.upstox.com"
TOKEN_ENV_VAR = "UPSTOX_ANALYTICS_ACCESS_TOKEN"
NSE_EQ_SEGMENT = "NSE_EQ"

QUOTE_BATCH_SIZE = 500  # documented maximum instrument keys per quote call

# Verified live: a 3653-day (10y+1d) daily request succeeds, while
# 2000-01-01..2026-09-28 is rejected with UDAPI1148 "Invalid date range".
# 3650 sits safely inside the limit and covers 2000-to-now in 3 chunks.
MAX_DAYS_PER_CALL = 3650

# Upstox's own floor for daily equity history. Verified live: asking for
# 1996-09-28..2006-09-27 returns candles starting 2000-01-03, so nothing
# earlier than 2000 exists to fetch.
HISTORY_FLOOR = date(2000, 1, 1)

REQUESTS_PER_SEC = 8.0
MAX_RETRIES = 5


class UpstoxError(RuntimeError):
    """An Upstox API error that is not a transient rate limit."""


@dataclass(frozen=True)
class QuoteSnapshot:
    """One symbol's live snapshot, normalised away from Upstox's wire format."""

    symbol: str
    ltp: float
    today_high: float | None
    candle_ts: int | None  # start of the candle, epoch millis


def instrument_key(isin: str, segment: str = NSE_EQ_SEGMENT) -> str:
    """Build an instrument_key, e.g. INE002A01018 -> NSE_EQ|INE002A01018."""
    return f"{segment}|{str(isin).strip()}"


class _RateLimiter:
    """Paces calls to stay under REQUESTS_PER_SEC."""

    def __init__(self, per_sec: float = REQUESTS_PER_SEC):
        self.min_interval = 1.0 / per_sec
        self._last = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


class UpstoxClient:
    """Market-data client. Injected where the Kite client used to be."""

    def __init__(self, token: str | None = None, per_sec: float = REQUESTS_PER_SEC):
        if token is None:
            # usecwd: resolve .env from the invocation directory, not from this
            # module's location -- otherwise an import from outside the project
            # root silently finds no .env and the token looks absent.
            load_dotenv(find_dotenv(usecwd=True))
            token = os.environ.get(TOKEN_ENV_VAR)
        if not token:
            raise UpstoxError(
                f"{TOKEN_ENV_VAR} not set. Put your Upstox analytics access token "
                "in .env (copy .env.example). Note: .env is gitignored; never put "
                "a real token in .env.example."
            )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self._limiter = _RateLimiter(per_sec)

    # -- plumbing ---------------------------------------------------------

    def _get(self, url: str, params: dict | None = None) -> dict:
        """GET with rate limiting and 429 backoff. Never logs the token."""
        for attempt in range(MAX_RETRIES):
            self._limiter.wait()
            resp = self._session.get(url, params=params, timeout=60)

            if resp.status_code == 429:
                if attempt == MAX_RETRIES - 1:
                    raise UpstoxError(f"Rate limited after {MAX_RETRIES} attempts: {url}")
                # Honour Retry-After when present, else exponential backoff.
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else (2**attempt)
                time.sleep(delay)
                continue

            if resp.status_code == 200:
                return resp.json()

            # Surface the API's own error code; the caller decides whether a
            # given code is fatal or just "no data for this instrument".
            try:
                errors = resp.json().get("errors", [])
                detail = "; ".join(
                    f"{e.get('errorCode')}: {e.get('message')}" for e in errors
                ) or resp.text[:300]
            except ValueError:
                detail = resp.text[:300]
            raise UpstoxError(f"HTTP {resp.status_code} from {url.split('?')[0]} -- {detail}")

        raise UpstoxError(f"Exhausted retries: {url}")

    # -- quotes -----------------------------------------------------------

    def quote_ohlc(
        self, keys_by_symbol: dict[str, str], interval: str = "1d"
    ) -> tuple[dict[str, QuoteSnapshot], list[str]]:
        """Fetch live OHLC for up to QUOTE_BATCH_SIZE symbols in one call.

        `keys_by_symbol` maps our symbol -> instrument_key. Returns
        (snapshots_by_symbol, unmatched_response_keys).

        Verified behaviour: the response is NOT keyed by the instrument_key we
        send. It comes back keyed `EXCHANGE:TRADINGSYMBOL` (e.g.
        `NSE_EQ:RELIANCE`) with our key echoed in the payload's
        `instrument_token`. A 200-symbol batch mapped 200/200 via
        `instrument_token` with zero misses, so that is the primary path;
        the tradingsymbol fallback exists only in case that field ever
        changes form. Mapping on the response key alone would silently
        produce zero matches.
        """
        if not keys_by_symbol:
            return {}, []
        if len(keys_by_symbol) > QUOTE_BATCH_SIZE:
            raise ValueError(
                f"{len(keys_by_symbol)} keys exceeds QUOTE_BATCH_SIZE={QUOTE_BATCH_SIZE}; "
                "batch upstream"
            )

        by_key = {key: sym for sym, key in keys_by_symbol.items()}
        by_symbol = {sym.upper(): sym for sym in keys_by_symbol}

        body = self._get(
            f"{BASE_URL}/v3/market-quote/ohlc",
            params={
                "instrument_key": ",".join(keys_by_symbol.values()),
                "interval": interval,
            },
        )
        data = body.get("data") or {}

        snapshots: dict[str, QuoteSnapshot] = {}
        unmatched: list[str] = []

        for resp_key, payload in data.items():
            symbol = by_key.get(payload.get("instrument_token") or "")
            if symbol is None and ":" in resp_key:
                symbol = by_symbol.get(resp_key.split(":", 1)[1].strip().upper())
            if symbol is None:
                unmatched.append(resp_key)
                continue

            ltp = payload.get("last_price")
            if ltp is None:
                unmatched.append(resp_key)
                continue

            # `live_ohlc` is the current session's forming candle; `prev_ohlc`
            # the previous one. Verified: prev_ohlc can be None (not {}), so
            # both are coerced before use. Prefer live; fall back to prev when
            # the market has not opened.
            live = payload.get("live_ohlc") or {}
            prev = payload.get("prev_ohlc") or {}
            candle = live if live.get("high") is not None else prev

            high = candle.get("high")
            snapshots[symbol] = QuoteSnapshot(
                symbol=symbol,
                ltp=float(ltp),
                today_high=float(high) if high is not None else None,
                candle_ts=candle.get("ts"),
            )

        return snapshots, unmatched

    # -- history ----------------------------------------------------------

    def daily_candles(
        self, key: str, from_date: date, to_date: date
    ) -> list[dict]:
        """Daily candles for one instrument, inclusive of both dates.

        Returns Kite-shaped rows -- ``{"date", "open", "high", "low",
        "close", "volume"}`` -- so the caching layer in `history.py` is
        provider-agnostic.

        Verified behaviour:
          - path order really is `.../{unit}/{interval}/{to_date}/{from_date}`,
            i.e. **to_date before from_date**
          - each candle is `[ts, open, high, low, close, volume, open_interest]`
          - candles ARE corporate-action adjusted (see README); RELIANCE's
            pre-bonus 2024-10-25 high returns 1344.35, matching Kite to the
            paise, with no cliff across the 2024-10-28 ex-date
          - a window entirely before listing returns an empty `candles` list
            rather than an error, which is what lets the caller stop walking
            back
        """
        if from_date > to_date:
            return []
        url = (
            f"{BASE_URL}/v3/historical-candle/{quote(key, safe='')}"
            f"/days/1/{to_date.isoformat()}/{from_date.isoformat()}"
        )
        body = self._get(url)
        candles = (body.get("data") or {}).get("candles") or []
        return [
            {
                "date": c[0],
                "open": c[1],
                "high": c[2],
                "low": c[3],
                "close": c[4],
                "volume": c[5],
            }
            for c in candles
        ]
