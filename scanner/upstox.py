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

Rate limiting: Verified against Upstox's official documentation at
https://upstox.com/developer/api-documentation/rate-limiting/ (checked
2026-09-29). Market data endpoints (quotes, historical candles) fall under
"Other Standard APIs" with limits: 50 req/sec, 500 req/min, 2000 req/30min.
This implementation maintains all three limits with 80% safety margin (40/sec,
400/min, 1600/30min) using a multi-window sliding-window rate limiter.
429 responses are tracked; escalating cool-down after 3 in 5 minutes.

Everything below was verified live against the API on 2026-09-28; see the
"Verified behaviour" notes on each method for what was actually observed
rather than merely documented.
"""
from __future__ import annotations

import bisect
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import quote

import requests
from dotenv import find_dotenv, load_dotenv

logger = logging.getLogger(__name__)

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

# Per-second limit defaults (backward compatible).
REQUESTS_PER_SEC = 8.0
MAX_RETRIES = 5


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds to wait for a Retry-After value, or None if absent or unparseable.

    The header is either delta-seconds ("2") or an HTTP-date. A date in the past
    gives 0.0.
    """
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())

# Official limits from https://upstox.com/developer/api-documentation/rate-limiting/
# (checked 2026-09-29): 50 req/sec, 500 req/min, 2000 req/30min for market data.
# Safety margin: 80% of official limits.
RATE_LIMIT_WINDOWS = [
    (1, 40),      # 80% of 50 req/sec
    (60, 400),    # 80% of 500 req/min
    (1800, 1600), # 80% of 2000 req/30min
]


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


@dataclass
class _RateLimiterStats:
    """Accumulated stats during a client lifetime."""

    requests_made: int = 0
    responses_429: int = 0
    seconds_waiting: float = 0.0


class _RateLimiter:
    """Multi-window sliding-window rate limiter for safety under all caps.

    Maintains per-second, per-minute, and per-30-minute windows to ensure
    compliance with official rate limits (with safety margin). Thread-safe.
    """

    def __init__(
        self,
        windows: list[tuple[int, int]] | None = None,
        per_sec: float | None = None,
        time_func: Callable[[], float] | None = None,
        sleep_func: Callable[[float], None] | None = None,
    ):
        """
        Args:
            windows: List of (window_seconds, max_requests). If None and per_sec
                is also None, uses RATE_LIMIT_WINDOWS.
            per_sec: If provided, overrides windows to use only per-second limit
                for backward compatibility. Ignored if windows is not None.
            time_func: Clock function (default: time.monotonic). Injected for testing.
            sleep_func: Sleep function (default: time.sleep). Injected for testing.
        """
        self._time_func = time_func or time.monotonic
        self._sleep_func = sleep_func or time.sleep
        self._lock = threading.Lock()
        self.stats = _RateLimiterStats()

        # Determine windows: per_sec for backward compat, else RATE_LIMIT_WINDOWS
        if windows is not None:
            self._windows = windows
        elif per_sec is not None:
            # Backward-compatible mode: per-second limit only
            self._windows = [(1, int(per_sec))]
        else:
            self._windows = RATE_LIMIT_WINDOWS

        # Track request timestamps per window (one queue per window)
        self._request_times: list[list[float]] = [[] for _ in self._windows]

    def wait(self) -> None:
        """Block until the next request is allowed under all windows.

        Thread-safe. Updates stats.requests_made.
        """
        with self._lock:
            now = self._time_func()
            total_wait = 0.0

            # Slide windows and check all constraints
            for i, (window_secs, max_reqs) in enumerate(self._windows):
                cutoff = now - window_secs
                # Remove old timestamps outside this window
                self._request_times[i] = [t for t in self._request_times[i] if t > cutoff]

                # If this window is at capacity, calculate wait time
                if len(self._request_times[i]) >= max_reqs:
                    # Wait until the oldest request falls out of this window
                    oldest = self._request_times[i][0]
                    wait_until = oldest + window_secs
                    wait_time = wait_until - now
                    if wait_time > total_wait:
                        total_wait = wait_time

            # Reserve the send slot under the lock, at the time it will actually go out.
            # Other threads then see it and queue behind it; the sleep itself runs
            # after the lock is released.
            send_at = now + total_wait
            for i in range(len(self._windows)):
                bisect.insort(self._request_times[i], send_at)

            self.stats.requests_made += 1
            self.stats.seconds_waiting += total_wait

        if total_wait > 0.0:
            self._sleep_func(total_wait)


@dataclass
class _429State:
    """Track 429 responses for escalating cool-down logic."""

    count: int = 0  # 429s seen recently
    last_time: float = 0.0  # Last 429 timestamp
    cool_down_factor: int = 1  # Escalating multiplier


class UpstoxClient:
    """Market-data client. Injected where the Kite client used to be.

    Enforces multi-window rate limiting (per-second, per-minute, per-30-minute)
    with safety margins below official limits. Detects 429 rate-limit responses
    and escalates cool-down if they recur frequently (3 within 5 min).
    """

    def __init__(
        self,
        token: str | None = None,
        per_sec: float | None = None,
        time_func: Callable[[], float] | None = None,
        sleep_func: Callable[[float], None] | None = None,
    ):
        """
        Args:
            token: Upstox access token. If None, loads from UPSTOX_ANALYTICS_ACCESS_TOKEN.
            per_sec: Per-second rate limit (backward compat, optional). If None, uses
                multi-window rate limiting. If set, overrides with per-second only.
            time_func: Injected clock (for testing).
            sleep_func: Injected sleep (for testing).
        """
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
        self._limiter = _RateLimiter(per_sec=per_sec, time_func=time_func, sleep_func=sleep_func)
        self._429_state = _429State()
        self._time_func = time_func or time.monotonic
        self._sleep_func = sleep_func or time.sleep

    def stats(self) -> dict:
        """Return accumulated statistics: requests made, 429s seen, wait time."""
        return {
            "requests_made": self._limiter.stats.requests_made,
            "responses_429": self._limiter.stats.responses_429,
            "seconds_waiting": round(self._limiter.stats.seconds_waiting, 2),
        }

    # -- plumbing ---------------------------------------------------------

    def _get(self, url: str, params: dict | None = None) -> dict:
        """GET with rate limiting, multi-window compliance, and 429 escalation.

        Never logs the token or Authorization header.
        """
        for attempt in range(MAX_RETRIES):
            self._limiter.wait()
            resp = self._session.get(url, params=params, timeout=60)

            if resp.status_code == 429:
                self._limiter.stats.responses_429 += 1
                self._handle_429(attempt, url, resp)
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

    def _handle_429(self, attempt: int, url: str, resp: requests.Response) -> None:
        """Handle 429 response: honor Retry-After, track recurrence, escalate if needed.

        Logs a WARNING if 429s are recurring frequently to alert the user.
        """
        if attempt == MAX_RETRIES - 1:
            raise UpstoxError(f"Rate limited after {MAX_RETRIES} attempts: {url}")

        now = self._time_func()
        window_start = now - 300.0  # 5-minute window

        # Count 429s in the last 5 minutes
        if self._429_state.last_time >= window_start:
            self._429_state.count += 1
        else:
            self._429_state.count = 1

        self._429_state.last_time = now

        # Escalate if we've seen 3+ in 5 minutes
        if self._429_state.count >= 3:
            self._429_state.cool_down_factor = min(self._429_state.cool_down_factor * 2, 16)
            logger.warning(
                f"Received {self._429_state.count} rate-limit 429 responses in 5 min; "
                f"escalating cool-down factor to {self._429_state.cool_down_factor}x to avoid account block"
            )

        # Honor Retry-After header, else use exponential backoff * escalation factor
        delay = _parse_retry_after(resp.headers.get("Retry-After"))
        if delay is None:
            delay = (2 ** attempt) * self._429_state.cool_down_factor

        self._sleep_func(delay)

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
