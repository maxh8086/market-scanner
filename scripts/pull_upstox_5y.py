"""Pull up to N years of DAILY Upstox candles into data/upstox_5y.db.

Resumable: a symbol whose latest `ok` pull_log row has last_date within
SKIP_WITHIN_DAYS of today is skipped. A symbol that already has candles is
fetched only after its newest stored date. Writes only to the SQLite file
given by --db; never touches data/history.db or any Postgres/infra DB.

Usage (from the project root):
    .venv/Scripts/python.exe scripts/pull_upstox_5y.py --symbols RELIANCE,HAL
    .venv/Scripts/python.exe scripts/pull_upstox_5y.py          # full universe
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from scanner.constituents import load_constituents  # noqa: E402
from scanner.history import _to_frame  # noqa: E402
from scanner.upstox import (  # noqa: E402
    MAX_DAYS_PER_CALL,
    UpstoxClient,
    UpstoxError,
    instrument_key,
)

DEFAULT_DB = Path("data/upstox_5y.db")
DEFAULT_DAYS = 1826
SKIP_WITHIN_DAYS = 5
AUTH_STATUS_CODES = (401, 403)

SCHEMA = [
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
    """,
    """
    CREATE TABLE IF NOT EXISTS pull_log (
        symbol TEXT NOT NULL,
        rows INTEGER,
        first_date TEXT,
        last_date TEXT,
        status TEXT NOT NULL,
        pulled_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_pull_log_symbol ON pull_log(symbol)",
]


class AuthError(RuntimeError):
    """Upstox rejected the token (401/403) or no token is configured."""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    for stmt in SCHEMA:
        conn.execute(stmt)
    conn.commit()
    return conn


def _status_code(exc: Exception) -> int | None:
    match = re.search(r"HTTP (\d{3})", str(exc))
    return int(match.group(1)) if match else None


def load_universe(symbols_arg: str | None, limit: int | None) -> list[tuple[str, str]]:
    """Return [(symbol, isin)] from the Nifty Total Market constituents list."""
    df = load_constituents()
    df = df.assign(
        Symbol=df["Symbol"].astype(str).str.strip().str.upper(),
        ISIN=df["ISIN Code"].fillna("").astype(str).str.strip(),
    )
    if symbols_arg:
        wanted = [s.strip().upper() for s in symbols_arg.split(",") if s.strip()]
        df = df[df["Symbol"].isin(wanted)]
        found = set(df["Symbol"])
        for missing in (s for s in wanted if s not in found):
            print(f"{missing}: not in constituents list")
        df = df.set_index("Symbol").loc[[s for s in wanted if s in found]].reset_index()
    pairs = list(zip(df["Symbol"], df["ISIN"]))
    if limit is not None:
        pairs = pairs[:limit]
    return pairs


def _ok_pulls(conn: sqlite3.Connection) -> dict[str, date]:
    """symbol -> last_date of its most recent `ok` pull_log row."""
    latest: dict[str, tuple[str, date]] = {}
    for symbol, last_date, pulled_at in conn.execute(
        "SELECT symbol, last_date, pulled_at FROM pull_log WHERE status = 'ok' ORDER BY pulled_at"
    ):
        if last_date:
            latest[symbol] = (pulled_at, date.fromisoformat(last_date))
    return {sym: last for sym, (_, last) in latest.items()}


def _stored_max_date(conn: sqlite3.Connection, symbol: str) -> date | None:
    row = conn.execute("SELECT MAX(date) FROM candles WHERE symbol = ?", (symbol,)).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def _fetch_range(client, key: str, start: date, end: date) -> pd.DataFrame:
    """Fetch [start, end] inclusive, chunked to MAX_DAYS_PER_CALL."""
    rows: list[dict] = []
    cursor = start
    while cursor <= end:
        chunk_to = min(cursor + timedelta(days=MAX_DAYS_PER_CALL - 1), end)
        rows.extend(client.daily_candles(key, cursor, chunk_to))
        cursor = chunk_to + timedelta(days=1)
    return _to_frame(rows)


def _write_candles(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame) -> int:
    records = []
    for r in df.itertuples(index=False):
        records.append(
            (
                symbol,
                r.date.isoformat(),
                None if pd.isna(r.open) else float(r.open),
                None if pd.isna(r.high) else float(r.high),
                None if pd.isna(r.low) else float(r.low),
                None if pd.isna(r.close) else float(r.close),
                None if pd.isna(r.volume) else int(r.volume),
            )
        )
    conn.executemany(
        """
        INSERT INTO candles (symbol, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, date) DO UPDATE SET
            open = excluded.open, high = excluded.high, low = excluded.low,
            close = excluded.close, volume = excluded.volume
        """,
        records,
    )
    return len(records)


def _log(conn: sqlite3.Connection, symbol: str, rows: int, status: str,
         first: date | None, last: date | None, now: datetime) -> None:
    conn.execute(
        "INSERT INTO pull_log (symbol, rows, first_date, last_date, status, pulled_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            symbol,
            rows,
            first.isoformat() if first else None,
            last.isoformat() if last else None,
            status,
            now.isoformat(timespec="seconds"),
        ),
    )


def pull_symbol(client, conn: sqlite3.Connection, symbol: str, isin: str,
                days: int, today: date, now: datetime) -> str:
    """Pull one symbol and log it. Returns the status written to pull_log."""
    if not isin:
        _log(conn, symbol, 0, "failed", None, None, now)
        conn.commit()
        print(f"{symbol}: failed (no ISIN in constituents list)")
        return "failed"

    key = instrument_key(isin)
    stored_max = _stored_max_date(conn, symbol)
    if stored_max is not None:
        start = stored_max + timedelta(days=1)
    else:
        start = today - timedelta(days=days - 1)
    if start > today:
        df = pd.DataFrame()
    else:
        df = _fetch_range(client, key, start, today)

    written = _write_candles(conn, symbol, df) if len(df) else 0
    first, last = conn.execute(
        "SELECT MIN(date), MAX(date) FROM candles WHERE symbol = ?", (symbol,)
    ).fetchone()
    first_d = date.fromisoformat(first) if first else None
    last_d = date.fromisoformat(last) if last else None
    status = "ok" if last_d else "empty"
    _log(conn, symbol, written, status, first_d, last_d, now)
    conn.commit()
    print(f"{symbol}: {status} new_rows={written} first={first_d} last={last_d}")
    return status


def run(client, conn: sqlite3.Connection, universe: list[tuple[str, str]],
        days: int, today: date, now: datetime) -> dict:
    """Pull every pending symbol. Returns counts and the list of failed symbols.

    Raises AuthError on 401/403 so the caller can stop instead of retrying.
    """
    done_ok = _ok_pulls(conn)
    summary = {"skipped": 0, "ok": 0, "empty": 0, "failed": [], "rows": 0}
    for symbol, isin in universe:
        last = done_ok.get(symbol)
        if last is not None and (today - last).days <= SKIP_WITHIN_DAYS:
            summary["skipped"] += 1
            continue
        try:
            status = pull_symbol(client, conn, symbol, isin, days, today, now)
        except UpstoxError as exc:
            code = _status_code(exc)
            if code in AUTH_STATUS_CODES:
                raise AuthError(f"HTTP {code}") from None
            _log(conn, symbol, 0, "failed", None, None, now)
            conn.commit()
            print(f"{symbol}: failed (HTTP {code})" if code else f"{symbol}: failed (UpstoxError)")
            summary["failed"].append(symbol)
            continue
        except Exception as exc:  # noqa: BLE001 - record and continue
            _log(conn, symbol, 0, "failed", None, None, now)
            conn.commit()
            print(f"{symbol}: failed ({type(exc).__name__})")
            summary["failed"].append(symbol)
            continue
        if status == "ok":
            summary["ok"] += 1
        elif status == "empty":
            summary["empty"] += 1
        else:
            summary["failed"].append(symbol)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", help="comma-separated symbols; default: full constituents list")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"calendar days back from today (default {DEFAULT_DAYS})")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite file (default {DEFAULT_DB})")
    parser.add_argument("--limit", type=int, default=None, help="process only the first N symbols")
    args = parser.parse_args(argv)

    if args.days < 1:
        parser.error("--days must be >= 1")

    universe = load_universe(args.symbols, args.limit)
    if not universe:
        print("No symbols to pull.")
        return 0

    today = date.today()
    now = datetime.now()
    conn = connect(Path(args.db))
    try:
        try:
            client = UpstoxClient()
        except UpstoxError:
            print("Token not set: UPSTOX_ANALYTICS_ACCESS_TOKEN missing from .env.")
            return 2
        try:
            s = run(client, conn, universe, args.days, today, now)
        except AuthError as exc:
            print(f"Auth failed ({exc}). Stopping; no retries.")
            return 2
    finally:
        conn.close()

    print(
        f"Done: skipped={s['skipped']} ok={s['ok']} empty={s['empty']} "
        f"failed={len(s['failed'])} stats={client.stats()}"
    )
    if s["failed"]:
        print("Failed: " + ", ".join(s["failed"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
