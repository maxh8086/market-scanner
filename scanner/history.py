"""Chunked, SQLite-cached fetch of daily historical candles.

The data provider is injected (see `scanner/upstox.py`): anything exposing
`daily_candles(key, from_date, to_date) -> list[{date, open, high, low,
close, volume}]` works, which keeps this module provider-agnostic.

Upstox's daily endpoint accepts roughly a decade per call, so full histories
are fetched in MAX_DAYS_PER_CALL chunks walking backwards from today and
stopping at the first empty chunk (a window entirely before listing comes
back empty rather than erroring). Verified live: RELIANCE's whole history --
6,648 candles back to 2000-01-03 -- takes 3 requests.

Rate limiting and 429 backoff are the client's job, not this module's;
throttling in both places would silently compound.

Daily candles are cached per-symbol in SQLite under data/history.db, along
with the running ath_high / ath_date / ath_close / first_date so a repeat
run only has to fetch days after the last cached date.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from scanner.upstox import HISTORY_FLOOR, MAX_DAYS_PER_CALL

DB_PATH = Path("data/history.db")
MIN_DATE = HISTORY_FLOOR
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (symbol, date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS symbol_stats (
            symbol TEXT PRIMARY KEY,
            ath_high REAL,
            ath_date TEXT,
            ath_close REAL,
            ath_close_date TEXT,
            first_date TEXT,
            last_date TEXT
        )
        """
    )
    return conn


def _to_frame(rows: list[dict]) -> pd.DataFrame:
    """Normalise raw provider rows into a deduped, date-sorted frame.

    Upstox returns tz-aware IST timestamps (`2024-10-25T00:00:00+05:30`);
    dropping the tz before taking `.date()` keeps the calendar day as traded
    rather than shifting it under UTC conversion.
    """
    if not rows:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], utc=False, format="ISO8601").dt.tz_localize(
        None
    ).dt.date
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    return df[CANDLE_COLUMNS]


def _fetch_full_history(client, key: str, symbol: str, cutoff: date) -> pd.DataFrame:
    """Fetch a symbol's entire history from `cutoff` back to MIN_DATE (or its
    listing date, whichever comes first), walking backwards in
    MAX_DAYS_PER_CALL chunks and stopping when a chunk comes back empty."""
    all_rows: list[dict] = []
    chunk_to = cutoff

    while chunk_to >= MIN_DATE:
        chunk_from = max(chunk_to - timedelta(days=MAX_DAYS_PER_CALL - 1), MIN_DATE)
        rows = client.daily_candles(key, chunk_from, chunk_to)
        if not rows:
            break
        all_rows.extend(rows)
        if chunk_from <= MIN_DATE:
            break
        chunk_to = chunk_from - timedelta(days=1)

    return _to_frame(all_rows)


def _fetch_incremental(client, key: str, symbol: str, since: date, cutoff: date) -> pd.DataFrame:
    """Fetch candles strictly after `since`, up to `cutoff`, chunked if needed."""
    from_date = since + timedelta(days=1)
    to_date = cutoff
    if from_date > to_date:
        return pd.DataFrame(columns=CANDLE_COLUMNS)

    all_rows: list[dict] = []
    cursor = from_date
    while cursor <= to_date:
        chunk_to = min(cursor + timedelta(days=MAX_DAYS_PER_CALL - 1), to_date)
        rows = client.daily_candles(key, cursor, chunk_to)
        if rows:
            all_rows.extend(rows)
        cursor = chunk_to + timedelta(days=1)

    return _to_frame(all_rows)


def _load_cached_candles(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM candles WHERE symbol = ? ORDER BY date",
        conn,
        params=(symbol,),
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _save_candles(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    rows = [
        (symbol, d.isoformat(), o, h, l, c, v)
        for d, o, h, l, c, v in df[["date", "open", "high", "low", "close", "volume"]].itertuples(
            index=False, name=None
        )
    ]
    conn.executemany(
        """
        INSERT INTO candles (symbol, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, date) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low,
            close=excluded.close, volume=excluded.volume
        """,
        rows,
    )
    conn.commit()


def _update_symbol_stats(conn: sqlite3.Connection, symbol: str) -> None:
    df = _load_cached_candles(conn, symbol)
    if df.empty:
        return
    ath_idx = df["high"].idxmax()
    ath_close_idx = df["close"].idxmax()
    conn.execute(
        """
        INSERT INTO symbol_stats (symbol, ath_high, ath_date, ath_close, ath_close_date, first_date, last_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            ath_high=excluded.ath_high, ath_date=excluded.ath_date,
            ath_close=excluded.ath_close, ath_close_date=excluded.ath_close_date,
            first_date=excluded.first_date, last_date=excluded.last_date
        """,
        (
            symbol,
            float(df.loc[ath_idx, "high"]),
            df.loc[ath_idx, "date"].isoformat(),
            float(df.loc[ath_close_idx, "close"]),
            df.loc[ath_close_idx, "date"].isoformat(),
            df["date"].min().isoformat(),
            df["date"].max().isoformat(),
        ),
    )
    conn.commit()


@dataclass
class SymbolHistory:
    symbol: str
    candles: pd.DataFrame
    ath_high: float | None
    ath_date: date | None
    ath_close: float | None
    first_date: date | None
    last_date: date | None


def get_history(
    client, key: str, symbol: str, force_refresh: bool = False, today: date | None = None
) -> SymbolHistory:
    """Return cached history for `symbol` up to (but excluding) `today`,
    topping up with any new days since the last cached date (or doing a
    full fetch if uncached or force_refresh is set).

    `client` is any provider exposing `daily_candles`; `key` is that
    provider's instrument identifier (for Upstox, `NSE_EQ|{ISIN}`).

    Today's own candle is deliberately never fetched here — the caller
    combines this history with today's live quote/OHLC instead, so a
    forming intraday "day" candle never gets double-counted.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=1)

    conn = _connect()
    try:
        if force_refresh:
            conn.execute("DELETE FROM candles WHERE symbol = ?", (symbol,))
            conn.execute("DELETE FROM symbol_stats WHERE symbol = ?", (symbol,))
            conn.commit()
            new_df = _fetch_full_history(client, key, symbol, cutoff)
            _save_candles(conn, symbol, new_df)
        else:
            cached = _load_cached_candles(conn, symbol)
            if cached.empty:
                new_df = _fetch_full_history(client, key, symbol, cutoff)
                _save_candles(conn, symbol, new_df)
            else:
                last_date = cached["date"].max()
                if last_date < cutoff:
                    incremental = _fetch_incremental(client, key, symbol, last_date, cutoff)
                    _save_candles(conn, symbol, incremental)

        _update_symbol_stats(conn, symbol)

        candles = _load_cached_candles(conn, symbol)
        if candles.empty:
            # Brand-new listing with no completed sessions before `today` yet.
            return SymbolHistory(
                symbol=symbol,
                candles=candles,
                ath_high=None,
                ath_date=None,
                ath_close=None,
                first_date=None,
                last_date=None,
            )

        row = conn.execute(
            "SELECT ath_high, ath_date, ath_close, first_date, last_date FROM symbol_stats WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        ath_high, ath_date_str, ath_close, first_date_str, last_date_str = row

        return SymbolHistory(
            symbol=symbol,
            candles=candles,
            ath_high=ath_high,
            ath_date=datetime.strptime(ath_date_str, "%Y-%m-%d").date(),
            ath_close=ath_close,
            first_date=datetime.strptime(first_date_str, "%Y-%m-%d").date(),
            last_date=datetime.strptime(last_date_str, "%Y-%m-%d").date(),
        )
    finally:
        conn.close()
