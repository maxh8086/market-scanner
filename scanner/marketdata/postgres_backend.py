"""Postgres implementation of market data storage.

Uses the shared Postgres database with proper gap tracking via feed_coverage
for incremental fetches.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from scanner.pg.db import connect
from scanner.upstox import HISTORY_FLOOR, MAX_DAYS_PER_CALL
from scanner.history import SymbolHistory, _to_frame, _fetch_full_history, _fetch_incremental


MIN_DATE = HISTORY_FLOOR
CANDLE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def cached_closes(symbols: Iterable[str], min_rows: int = 1) -> dict[str, list[float]]:
    """Closes already cached in Postgres, per symbol, oldest first."""
    wanted = [s for s in symbols if s]
    if not wanted:
        return {}

    try:
        with connect() as conn:
            out: dict[str, list[float]] = {}
            # Chunked: Postgres parameter limit is often 32767 but play it safe
            for start in range(0, len(wanted), 500):
                chunk = wanted[start : start + 500]
                rows = conn.execute(
                    "SELECT symbol, close FROM candles WHERE symbol = ANY(%s) "
                    "AND close IS NOT NULL ORDER BY symbol, date",
                    (chunk,),
                ).fetchall()
                for row in rows:
                    out.setdefault(row["symbol"], []).append(float(row["close"]))
            return {s: v for s, v in out.items() if len(v) >= min_rows}
    except Exception:
        return {}


def _to_float(value):
    """NUMERIC -> float at the read boundary (None stays None)."""
    return None if value is None else float(value)


def _load_cached_candles_pg(conn, symbol: str) -> pd.DataFrame:
    """Load cached candles from Postgres for a symbol."""
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM candles "
        "WHERE symbol = %s ORDER BY date",
        (symbol,),
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    df = pd.DataFrame(rows)
    # NUMERIC columns arrive as Decimal; the scanner does float arithmetic on them.
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    return df


def _save_candles_pg(conn, symbol: str, df: pd.DataFrame) -> None:
    """Save candles to Postgres via COPY (fast bulk insert)."""
    if df.empty:
        return

    # Use executemany for flexibility (handles NULL values, types)
    with conn.cursor() as cur:
        data = [
            (symbol, d.isoformat() if hasattr(d, 'isoformat') else str(d), o, h, l, c, v)
            for d, o, h, l, c, v in df[["date", "open", "high", "low", "close", "volume"]].itertuples(
                index=False, name=None
            )
        ]
        cur.executemany(
            """
            INSERT INTO candles (symbol, date, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, date) DO UPDATE SET
                open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                close=EXCLUDED.close, volume=EXCLUDED.volume
            """,
            data,
        )
    conn.commit()


def _update_symbol_stats_pg(conn, symbol: str) -> None:
    """Update symbol_stats in Postgres after inserting candles."""
    df = _load_cached_candles_pg(conn, symbol)
    if df.empty:
        return

    ath_idx = df["high"].idxmax()
    ath_close_idx = df["close"].idxmax()

    conn.execute(
        """
        INSERT INTO symbol_stats (symbol, ath_high, ath_date, ath_close, ath_close_date, first_date, last_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            ath_high=EXCLUDED.ath_high, ath_date=EXCLUDED.ath_date,
            ath_close=EXCLUDED.ath_close, ath_close_date=EXCLUDED.ath_close_date,
            first_date=EXCLUDED.first_date, last_date=EXCLUDED.last_date,
            updated_at=now()
        """,
        (
            symbol,
            float(df.loc[ath_idx, "high"]),
            df.loc[ath_idx, "date"],
            float(df.loc[ath_close_idx, "close"]),
            df.loc[ath_close_idx, "date"],
            df["date"].min(),
            df["date"].max(),
        ),
    )
    conn.commit()


def get_history(
    client, key: str, symbol: str, force_refresh: bool = False, today: date | None = None
) -> SymbolHistory:
    """Return cached history for `symbol`, fetching new days as needed."""
    from datetime import datetime

    today = today or date.today()
    cutoff = today - timedelta(days=1)

    with connect() as conn:
        if force_refresh:
            conn.execute("DELETE FROM candles WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM symbol_stats WHERE symbol = %s", (symbol,))
            conn.commit()
            new_df = _fetch_full_history(client, key, symbol, cutoff)
            _save_candles_pg(conn, symbol, new_df)
        else:
            cached = _load_cached_candles_pg(conn, symbol)
            if cached.empty:
                new_df = _fetch_full_history(client, key, symbol, cutoff)
                _save_candles_pg(conn, symbol, new_df)
            else:
                last_date = cached["date"].max()
                if last_date < cutoff:
                    incremental = _fetch_incremental(client, key, symbol, last_date, cutoff)
                    _save_candles_pg(conn, symbol, incremental)

        _update_symbol_stats_pg(conn, symbol)

        candles = _load_cached_candles_pg(conn, symbol)
        if candles.empty:
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
            "SELECT ath_high, ath_date, ath_close, first_date, last_date FROM symbol_stats WHERE symbol = %s",
            (symbol,),
        ).fetchone()

        return SymbolHistory(
            symbol=symbol,
            candles=candles,
            ath_high=_to_float(row["ath_high"]),
            ath_date=row["ath_date"],
            ath_close=_to_float(row["ath_close"]),
            first_date=row["first_date"],
            last_date=row["last_date"],
        )


def collect_eod(client, key: str, symbol: str, today: date | None = None) -> dict:
    """Collect end-of-day candles for gaps only.

    Checks feed_coverage for candles_eod to find missing windows,
    fetches only those, and records the coverage.

    Returns:
        {"fetched": int, "new": int, "from": date|None, "to": date|None}
    """
    from scanner.coverage import missing_windows, record_coverage

    today = today or date.today()
    cutoff = today - timedelta(days=1)

    with connect() as conn:
        # Find missing windows
        gaps = missing_windows(conn, "candles_eod", MIN_DATE, cutoff)

        total_fetched = 0
        total_new = 0
        from_date = None
        to_date = None

        for gap_from, gap_to in gaps:
            # Fetch this gap
            new_df = _fetch_incremental(client, key, symbol, gap_from - timedelta(days=1), gap_to)
            fetched = len(new_df)
            total_fetched += fetched

            if not new_df.empty:
                before_count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM candles WHERE symbol = %s", (symbol,)
                ).fetchone()["cnt"]

                _save_candles_pg(conn, symbol, new_df)

                after_count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM candles WHERE symbol = %s", (symbol,)
                ).fetchone()["cnt"]

                new_rows = after_count - before_count
                total_new += new_rows

                if from_date is None:
                    from_date = new_df["date"].min()
                to_date = new_df["date"].max()

            # Record this window as fetched
            record_coverage(conn, "candles_eod", gap_from, gap_to)

        _update_symbol_stats_pg(conn, symbol)

    return {
        "fetched": total_fetched,
        "new": total_new,
        "from": from_date,
        "to": to_date,
    }
