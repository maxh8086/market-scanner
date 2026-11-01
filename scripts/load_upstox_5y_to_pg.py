"""Load candles from data/upstox_5y.db (SQLite) into Postgres public.candles.

    .venv/Scripts/python.exe scripts/load_upstox_5y_to_pg.py --dry-run   # count, then roll back
    .venv/Scripts/python.exe scripts/load_upstox_5y_to_pg.py             # load for real

Stages rows in a temp table via COPY, then INSERT ... ON CONFLICT (symbol, date)
DO NOTHING in one transaction. Existing rows are never updated or deleted, so the
script is idempotent: re-running it inserts 0 rows once the data is present.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

import psycopg
from dotenv import dotenv_values, find_dotenv

DEFAULT_DB = "data/upstox_5y.db"


def _connect() -> psycopg.Connection:
    env = dotenv_values(find_dotenv(usecwd=True))
    return psycopg.connect(
        host=os.environ.get("SCANNER_POSTGRES_HOST", "127.0.0.1"),
        port=int(os.environ.get("SCANNER_POSTGRES_PORT", "5433")),
        dbname=env.get("POSTGRES_DB", "market_scanner"),
        user=env.get("POSTGRES_USER", "market_scanner_app"),
        password=env.get("POSTGRES_PASSWORD"),
        connect_timeout=5,
    )


def _parse_date(value) -> date | None:
    """Return a date from an ISO string ('2024-10-07...') or NSE format, else None."""
    if not value:
        return None
    s = str(value).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _read_sqlite(db_path: Path) -> tuple[int, list[tuple]]:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        total = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        rows = conn.execute(
            "SELECT symbol, date, open, high, low, close, volume FROM candles"
        ).fetchall()
    finally:
        conn.close()
    return total, rows


def _scalar(cur, sql: str):
    cur.execute(sql)
    return cur.fetchone()[0]


def _snapshot(cur) -> dict:
    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT symbol), MAX(date) FROM candles"
    )
    n, syms, mx = cur.fetchone()
    return {"rows": n, "symbols": syms, "max_date": mx}


def run(db_path: Path, dry_run: bool) -> int:
    if not db_path.exists():
        print(f"Error: {db_path} not found")
        return 1

    sqlite_total, raw_rows = _read_sqlite(db_path)
    parsed = []
    bad_dates = 0
    for symbol, d, o, h, l, c, v in raw_rows:
        pd = _parse_date(d)
        if pd is None or symbol is None:
            bad_dates += 1
            continue
        parsed.append((symbol, pd, o, h, l, c, v))

    with _connect() as conn:
        with conn.cursor() as cur:
            before = _snapshot(cur)

            cur.execute(
                """
                CREATE TEMP TABLE stage (
                    symbol text, date date, open numeric, high numeric,
                    low numeric, close numeric, volume bigint
                ) ON COMMIT DROP
                """
            )
            with cur.copy(
                "COPY stage (symbol, date, open, high, low, close, volume) FROM STDIN"
            ) as cp:
                for row in parsed:
                    cp.write_row(row)

            cur.execute(
                """
                INSERT INTO candles (symbol, date, open, high, low, close, volume)
                SELECT symbol, date, open, high, low, close, volume FROM stage
                ON CONFLICT (symbol, date) DO NOTHING
                """
            )
            inserted = cur.rowcount

            after = _snapshot(cur)

        if dry_run:
            conn.rollback()
        else:
            conn.commit()

    skipped_present = len(parsed) - inserted
    mode = "DRY RUN (rolled back)" if dry_run else "LOADED (committed)"
    print(f"Mode:                          {mode}")
    print(f"SQLite rows (candles):         {sqlite_total}")
    print(f"SQLite rows with bad date:     {bad_dates}")
    print(f"Rows staged for insert:        {len(parsed)}")
    print(f"Rows inserted (new):           {inserted}")
    print(f"Rows skipped (already present):{skipped_present:>8}")
    print(f"Postgres candles before:       {before['rows']}")
    print(f"Postgres candles after:        {after['rows']}")
    print(f"Distinct symbols before/after: {before['symbols']} / {after['symbols']}")
    print(f"Max date after:                {after['max_date']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="count what would be inserted, then roll back")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default {DEFAULT_DB})")
    args = ap.parse_args(argv)
    try:
        return run(Path(args.db), args.dry_run)
    except Exception as e:  # noqa: BLE001
        print(f"Error: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
