"""Daily candles for benchmark indices, stored in the live Postgres `candles` table.

Each index is stored under the reserved symbol `IDX:<NAME>` (NAME uppercased),
using the same upsert as equity candles (`_save_candles_pg`). Symbol-level
stats (`symbol_stats`) are deliberately not touched.

Upstox rejects a daily window longer than MAX_DAYS_PER_CALL (UDAPI1148, see
scanner/upstox.py), so the history is walked backwards in chunks of that size
from the end date down to the start date, stopping at the first empty chunk (a
window before listing returns no candles rather than an error). Stepping the
start forward instead would stop at roughly 2016 and misreport the earliest date.

Both modes end at yesterday, so a partial bar for the current session is never
stored. Full history (default) fetches START_DATE through yesterday. Incremental
mode (`--incremental`) fetches from each index's last stored date minus
INCREMENTAL_OVERLAP_DAYS through yesterday; an index with no stored candles gets
a full fetch instead.

Run: python -m scanner.index_candles [--incremental]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from scanner.history import _to_frame
from scanner.marketdata.postgres_backend import _save_candles_pg
from scanner.pg.db import connect
from scanner.upstox import MAX_DAYS_PER_CALL, UpstoxClient, UpstoxError

START_DATE = date(2010, 1, 1)
IDX_PREFIX = "IDX:"
INCREMENTAL_OVERLAP_DAYS = 7

INDEX_KEYS = {
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "NIFTY BANK": "NSE_INDEX|Nifty Bank",
    "Nifty 500": "NSE_INDEX|Nifty 500",
    "NIFTY NEXT 50": "NSE_INDEX|Nifty Next 50",
    "NIFTY MIDCAP 150": "NSE_INDEX|NIFTY MIDCAP 150",
    "NIFTY SMALLCAP 250": "NSE_INDEX|NIFTY_SMLCAP_250",
    "Nifty500 Mul50:25:25": "NSE_INDEX|NIFTY500 MULTICAP",
    "NIFTY Services": "NSE_INDEX|Nifty Serv Sector",
    "NIFTY MICROCAP 250": "NSE_INDEX|NIFTY MICROCAP250",
    "INDIA VIX": "NSE_INDEX|India VIX",
    # Watchlist indices matched to the NSE instrument master by name (see server/src/live/liveRoute.ts).
    "NIFTY 100": "NSE_INDEX|Nifty 100",
    "NIFTY 200": "NSE_INDEX|Nifty 200",
    "NIFTY Midcap 100": "NSE_INDEX|NIFTY MIDCAP 100",
    "NIFTY MIDCAP 50": "NSE_INDEX|Nifty Midcap 50",
    "NIFTY Smallcap 100": "NSE_INDEX|NIFTY SMLCAP 100",
    "NIFTY SMLCAP 50": "NSE_INDEX|NIFTY SMLCAP 50",
    "NIFTY 750 TOTAL MKT": "NSE_INDEX|NIFTY TOTAL MKT",
    "NIFTY Auto": "NSE_INDEX|Nifty Auto",
    "NIFTY IT": "NSE_INDEX|Nifty IT",
    "NIFTY PSU Bank": "NSE_INDEX|Nifty PSU Bank",
    "NIFTY Fin Service": "NSE_INDEX|Nifty Fin Service",
    "NIFTY Pharma": "NSE_INDEX|Nifty Pharma",
    "NIFTY FMCG": "NSE_INDEX|Nifty FMCG",
    "NIFTY Metal": "NSE_INDEX|Nifty Metal",
    "NIFTY Realty": "NSE_INDEX|Nifty Realty",
    "NIFTY Media": "NSE_INDEX|Nifty Media",
    "NIFTY Energy": "NSE_INDEX|Nifty Energy",
    "Nifty Pvt Bank": "NSE_INDEX|Nifty Pvt Bank",
    "NIFTY Infra": "NSE_INDEX|Nifty Infra",
    "NIFTY Commodities": "NSE_INDEX|Nifty Commodities",
    "NIFTY Consumption": "NSE_INDEX|Nifty Consumption",
    "NIFTY PSE": "NSE_INDEX|Nifty PSE",
    "Nifty FinSrv25/50": "NSE_INDEX|Nifty FinSrv25 50",
    "Nifty Cons Durbl": "NSE_INDEX|NIFTY CONSR DURBL",
    "Nifty Healthcare": "NSE_INDEX|NIFTY HEALTHCARE",
    "Nifty Oil & Gas": "NSE_INDEX|NIFTY OIL AND GAS",
    "NIFTY India Mfg": "NSE_INDEX|NIFTY INDIA MFG",
    "Nifty India Defence": "NSE_INDEX|Nifty Ind Defence",
    "NIFTY MIDSML 400": "NSE_INDEX|NIFTY MIDSML 400",
    "NIFTY MNC": "NSE_INDEX|Nifty MNC",
    "NIFTY AlphaLowVol 30": "NSE_INDEX|NIFTY AlphaLowVol",
    "Nifty200 Momentum 30": "NSE_INDEX|Nifty200Momentm30",
    "Nifty LargeMid250": "NSE_INDEX|NIFTY LARGEMID250",
    "NIFTY CPSE": "NSE_INDEX|Nifty CPSE",
    "NIFTY MID SELECT": "NSE_INDEX|NIFTY MID SELECT",
    "NIFTY IND DIGITAL": "NSE_INDEX|NIFTY IND DIGITAL",
    "NIFTY M150 QLTY50": "NSE_INDEX|NIFTY M150 QLTY50",
    "Nifty Capital Market": "NSE_INDEX|Nifty Capital Mkt",
    "Nifty India FPI 150": "NSE_INDEX|Nifty FPI 150",
}

# Unverified spellings, tried in order when the primary key fails.
ALTERNATE_KEYS = {
    "NIFTY NEXT 50": ["NSE_INDEX|NIFTY NEXT 50"],
    "NIFTY MIDCAP 150": ["NSE_INDEX|Nifty Midcap 150"],
    "NIFTY SMALLCAP 250": ["NSE_INDEX|NIFTY SMLCAP 250", "NSE_INDEX|NIFTY SMALLCAP 250"],
    "NIFTY MICROCAP 250": ["NSE_INDEX|NIFTY MICROCAP 250", "NSE_INDEX|Nifty Microcap250"],
}


def index_symbol(name: str) -> str:
    return IDX_PREFIX + name.upper()


def last_stored_date(name: str) -> date | None:
    """Latest stored candle date for an index, or None if it has no candles."""
    with connect() as conn:
        row = conn.execute(
            "SELECT max(date) AS last_date FROM candles WHERE symbol = %s",
            (index_symbol(name),),
        ).fetchone()
    return row["last_date"] if row else None


def fetch_history(client, key: str, start: date, end: date) -> tuple[list[dict], str | None]:
    """Daily candles for `key` from `start` to `end` inclusive, walked in chunks.

    Returns (rows, error). `error` is set if a request was rejected; rows
    fetched before the rejection are still returned. An empty chunk ends the
    walk, since nothing exists before that point.
    """
    chunk_to = end
    rows: list[dict] = []
    while chunk_to >= start:
        chunk_from = max(chunk_to - timedelta(days=MAX_DAYS_PER_CALL - 1), start)
        try:
            part = client.daily_candles(key, chunk_from, chunk_to)
        except UpstoxError as exc:
            return rows, str(exc)
        if not part:
            break
        rows.extend(part)
        if chunk_from <= start:
            break
        chunk_to = chunk_from - timedelta(days=1)
    return rows, None


def fetch_full_history(client, key: str, today: date | None = None) -> tuple[list[dict], str | None]:
    """All daily candles for `key` from START_DATE to yesterday."""
    today = today or date.today()
    return fetch_history(client, key, START_DATE, today - timedelta(days=1))


def resolve_and_fetch(
    client,
    name: str,
    since: date | None = None,
    today: date | None = None,
    include_today: bool = False,
) -> tuple[str | None, list[dict], str | None]:
    """Try the primary key, then alternates. Returns (key_used, rows, last_error).

    By default both modes end at yesterday (today's bar is partial during market hours).
    With `include_today=True` the end date is `today` instead, for a run after the close
    when today's bar is complete. With `since` set, fetches only from
    `since - INCREMENTAL_OVERLAP_DAYS` through the end date. Without it, fetches the full
    history from START_DATE through the end date.
    """
    today = today or date.today()
    end = today if include_today else today - timedelta(days=1)
    if since is None:
        fetch = lambda key: fetch_history(client, key, START_DATE, end)  # noqa: E731
    else:
        start = since - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
        fetch = lambda key: fetch_history(client, key, start, end)  # noqa: E731

    last_error = None
    for key in [INDEX_KEYS[name], *ALTERNATE_KEYS.get(name, [])]:
        rows, err = fetch(key)
        if rows:
            return key, rows, err
        last_error = err or "no candles returned"
    return None, [], last_error


def store(name: str, rows: list[dict]) -> int:
    """Upsert rows under `IDX:<NAME>`. Returns the number of rows written."""
    df = _to_frame(rows)
    if df.empty:
        return 0
    with connect() as conn:
        _save_candles_pg(conn, index_symbol(name), df)
    return len(df)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="fetch only from each index's last stored date minus a week (full fetch if none stored)",
    )
    args = parser.parse_args(argv)

    client = UpstoxClient()
    failures = 0
    for name in INDEX_KEYS:
        since = last_stored_date(name) if args.incremental else None
        if args.incremental and since is None:
            print(f"{name} | no stored candles, full fetch")
        key, rows, err = resolve_and_fetch(client, name, since=since)
        if key is None:
            failures += 1
            print(f"{name} | NO KEY WORKED | last error: {err}")
            continue
        df = _to_frame(rows)
        written = store(name, rows)
        print(
            f"{name} | {key} | {df['date'].min()} | {df['date'].max()} | {written} rows"
            + (f" | note: {err}" if err else "")
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
