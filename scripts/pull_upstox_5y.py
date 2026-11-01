"""Pull up to N years of DAILY Upstox candles into data/upstox_5y.db.

Candles are staged in the SQLite file given by --db. The resume ledger
(pull_log) lives in the Postgres table `upstox_pull_log` (migration
db/migrations/011_fetch_metadata_pull_log.sql). Set UPSTOX_PULL_LOG=sqlite to
keep the ledger in the SQLite file instead (offline runs and tests). In the
default Postgres mode, an unreachable or unconfigured database, or a missing
table, exits 2 with a one-line error; there is no silent fallback to SQLite.

Resumable: a symbol whose latest `ok` ledger row has last_date within
SKIP_WITHIN_DAYS of today is skipped. A symbol that already has candles is
fetched only after its newest stored date. Candle writes go only to the SQLite
file given by --db; the only Postgres writes are ledger rows; data/history.db
is never touched.

Usage (from the project root):
    .venv/Scripts/python.exe scripts/pull_upstox_5y.py --symbols RELIANCE,HAL
    .venv/Scripts/python.exe scripts/pull_upstox_5y.py          # full universe
    UPSTOX_PULL_LOG=sqlite .venv/Scripts/python.exe scripts/pull_upstox_5y.py --symbols HAL
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from psycopg import Error as PsycopgError  # noqa: E402

from scanner import isin_resolver  # noqa: E402
from scanner.constituents import load_constituents  # noqa: E402
from scanner.history import _to_frame  # noqa: E402
from scanner.pg import db as pg_db  # noqa: E402
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
PULL_LOG_ENV = "UPSTOX_PULL_LOG"
PG_PULL_LOG_TABLE = "upstox_pull_log"

CANDLES_SCHEMA = [
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
]
# SQLite pull_log: only used when UPSTOX_PULL_LOG=sqlite.
PULL_LOG_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS pull_log (
        symbol TEXT NOT NULL,
        rows INTEGER,
        first_date TEXT,
        last_date TEXT,
        status TEXT NOT NULL,
        pulled_at TEXT NOT NULL,
        error TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_pull_log_symbol ON pull_log(symbol)",
]
# Added after the first release: CREATE TABLE IF NOT EXISTS does not add it to old DBs.
MIGRATIONS = [
    ("pull_log", "error", "ALTER TABLE pull_log ADD COLUMN error TEXT"),
]
ERROR_MAX_CHARS = 300
_SECRET_PATTERNS = (
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer [redacted]"),
    (re.compile(r"(authorization|access_token|token)(\W{0,3})\S+", re.IGNORECASE),
     r"\1\2[redacted]"),
)


class AuthError(RuntimeError):
    """Upstox rejected the token (401/403) or no token is configured."""


class PullLogUnavailable(RuntimeError):
    """The Postgres ledger cannot be used; the message is a single line."""


def pull_log_backend() -> str:
    """'postgres' (default, also when UPSTOX_PULL_LOG is empty) or 'sqlite'."""
    value = os.environ.get(PULL_LOG_ENV, "").strip().lower()
    if value in ("", "postgres"):
        return "postgres"
    if value == "sqlite":
        return "sqlite"
    raise ValueError(f"{PULL_LOG_ENV} must be 'sqlite' or unset, got {value!r}")


def _one_line(exc: BaseException) -> str:
    return " ".join((str(exc) or type(exc).__name__).split())


def open_pg_pull_log():
    """Open the Postgres connection used for the pull_log ledger, or raise PullLogUnavailable."""
    try:
        conn = pg_db.connect(connect_timeout=5)
    except Exception as exc:  # unconfigured or unreachable
        raise PullLogUnavailable(f"Postgres unavailable for {PG_PULL_LOG_TABLE}: {_one_line(exc)}") from None
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT to_regclass('{PG_PULL_LOG_TABLE}') IS NOT NULL AS present")
            row = cur.fetchone()
        present = bool(row["present"]) if row else False
    except Exception as exc:
        conn.close()
        raise PullLogUnavailable(f"Postgres check for {PG_PULL_LOG_TABLE} failed: {_one_line(exc)}") from None
    if not present:
        conn.close()
        raise PullLogUnavailable(
            f"table {PG_PULL_LOG_TABLE} not found in Postgres; apply "
            "db/migrations/011_fetch_metadata_pull_log.sql first"
        )
    return conn


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the SQLite candles file. Creates the SQLite pull_log only in sqlite mode."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    for stmt in CANDLES_SCHEMA:
        conn.execute(stmt)
    if pull_log_backend() == "sqlite":
        for stmt in PULL_LOG_SCHEMA:
            conn.execute(stmt)
        for table, column, stmt in MIGRATIONS:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                conn.execute(stmt)
    conn.commit()
    return conn


def _status_code(exc: Exception) -> int | None:
    match = re.search(r"HTTP (\d{3})", str(exc))
    return int(match.group(1)) if match else None


def _error_text(exc: BaseException) -> str:
    """Short, token-free error text for pull_log.error (at most ERROR_MAX_CHARS)."""
    text = " ".join((str(exc) or type(exc).__name__).split())
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:ERROR_MAX_CHARS]


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
    return _apply_isin_resolution(pairs)


def _apply_isin_resolution(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Swap stale CSV ISINs for the master's ISIN. Symbols stay as they are (storage is symbol-keyed).
    If the master is unavailable, the CSV ISINs are returned unchanged."""
    master, reason = isin_resolver.try_load_master()
    if master is None:
        print(f"Warning: ISIN master unavailable ({reason}); using constituents CSV ISINs.")
        return pairs
    out: list[tuple[str, str]] = []
    for symbol, isin in pairs:
        res = isin_resolver.resolve(symbol, isin, master)
        if res.changed:
            print(isin_resolver.describe_change(symbol, isin, res))
        out.append((symbol, res.isin if res.resolved and res.isin else isin))
    return out


def _refreshed_isin(symbol: str, isin: str) -> str | None:
    """Re-resolve one symbol from a freshly downloaded master. Returns the new ISIN only when it differs."""
    master, reason = isin_resolver.try_load_master(refresh=True)
    if master is None:
        print(f"{symbol}: ISIN refresh skipped ({reason})")
        return None
    res = isin_resolver.resolve(symbol, isin, master)
    if not res.resolved or not res.isin or res.isin == isin.strip().upper():
        return None
    return res.isin


def _as_date(value) -> date:
    """Postgres returns date objects; SQLite returns ISO strings."""
    return value if isinstance(value, date) else date.fromisoformat(value)


def _ok_pulls(log) -> dict[str, date]:
    """symbol -> last_date of its most recent `ok` ledger row.

    `log` is the SQLite connection (sqlite mode) or the Postgres connection.
    """
    if isinstance(log, sqlite3.Connection):
        rows = [
            (symbol, last_date, pulled_at)
            for symbol, last_date, pulled_at in log.execute(
                "SELECT symbol, last_date, pulled_at FROM pull_log WHERE status = 'ok' ORDER BY pulled_at"
            )
        ]
    else:
        with log.cursor() as cur:
            cur.execute(
                f"SELECT symbol, last_date, pulled_at FROM {PG_PULL_LOG_TABLE} "
                "WHERE status = 'ok' ORDER BY pulled_at"
            )
            rows = [(r["symbol"], r["last_date"], r["pulled_at"]) for r in cur.fetchall()]
    latest: dict[str, tuple[object, date]] = {}
    for symbol, last_date, pulled_at in rows:
        if last_date:
            latest[symbol] = (pulled_at, _as_date(last_date))
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


def _log(log, symbol: str, rows: int, status: str,
         first: date | None, last: date | None, now: datetime,
         error: str | None = None) -> None:
    """Insert one ledger row into the SQLite pull_log or the Postgres upstox_pull_log."""
    if isinstance(log, sqlite3.Connection):
        log.execute(
            "INSERT INTO pull_log (symbol, rows, first_date, last_date, status, pulled_at, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                symbol,
                rows,
                first.isoformat() if first else None,
                last.isoformat() if last else None,
                status,
                now.isoformat(timespec="seconds"),
                error,
            ),
        )
        return
    with log.cursor() as cur:
        cur.execute(
            f"INSERT INTO {PG_PULL_LOG_TABLE} "
            "(symbol, rows, first_date, last_date, status, pulled_at, error) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (symbol, rows, first, last, status, now, error),
        )


def pull_symbol(client, conn: sqlite3.Connection, symbol: str, isin: str,
                days: int, today: date, now: datetime, log=None) -> str:
    """Pull one symbol and log it. Returns the status written to the ledger."""
    log = conn if log is None else log
    if not isin:
        _log(log, symbol, 0, "failed", None, None, now, "no ISIN in constituents list")
        conn.commit()
        log.commit()
        print(f"{symbol}: failed (no ISIN in constituents list)")
        return "failed"

    stored_max = _stored_max_date(conn, symbol)
    if stored_max is not None:
        start = stored_max + timedelta(days=1)
    else:
        start = today - timedelta(days=days - 1)
    if start > today:
        df = pd.DataFrame()
    else:
        try:
            df = _fetch_range(client, instrument_key(isin), start, today)
        except UpstoxError as exc:
            # HTTP 400 can mean a stale ISIN. Re-resolve once from a fresh master; retry only if it changed.
            if _status_code(exc) != 400:
                raise
            new_isin = _refreshed_isin(symbol, isin)
            if new_isin is None:
                raise
            print(f"{symbol}: HTTP 400 with ISIN {isin}; retrying with {new_isin} from refreshed master")
            isin = new_isin
            df = _fetch_range(client, instrument_key(isin), start, today)

    written = _write_candles(conn, symbol, df) if len(df) else 0
    first, last = conn.execute(
        "SELECT MIN(date), MAX(date) FROM candles WHERE symbol = ?", (symbol,)
    ).fetchone()
    first_d = date.fromisoformat(first) if first else None
    last_d = date.fromisoformat(last) if last else None
    status = "ok" if last_d else "empty"
    _log(log, symbol, written, status, first_d, last_d, now)
    conn.commit()
    log.commit()
    print(f"{symbol}: {status} new_rows={written} first={first_d} last={last_d}")
    return status


def run(client, conn: sqlite3.Connection, universe: list[tuple[str, str]],
        days: int, today: date, now: datetime, log=None) -> dict:
    """Pull every pending symbol. Returns counts and the list of failed symbols.

    `log` is the ledger connection (Postgres, or SQLite when `log` is None).
    Raises AuthError on 401/403 so the caller can stop instead of retrying.
    """
    log = conn if log is None else log
    done_ok = _ok_pulls(log)
    summary = {"skipped": 0, "ok": 0, "empty": 0, "failed": [], "rows": 0}
    for symbol, isin in universe:
        last = done_ok.get(symbol)
        if last is not None and (today - last).days <= SKIP_WITHIN_DAYS:
            summary["skipped"] += 1
            continue
        try:
            status = pull_symbol(client, conn, symbol, isin, days, today, now, log=log)
        except UpstoxError as exc:
            code = _status_code(exc)
            if code in AUTH_STATUS_CODES:
                raise AuthError(f"HTTP {code}") from None
            _log(log, symbol, 0, "failed", None, None, now, _error_text(exc))
            conn.commit()
            log.commit()
            print(f"{symbol}: failed (HTTP {code})" if code else f"{symbol}: failed (UpstoxError)")
            summary["failed"].append(symbol)
            continue
        except Exception as exc:  # noqa: BLE001 - record and continue
            _log(log, symbol, 0, "failed", None, None, now, _error_text(exc))
            conn.commit()
            log.commit()
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
    try:
        backend = pull_log_backend()
    except ValueError as exc:
        parser.error(str(exc))

    universe = load_universe(args.symbols, args.limit)
    if not universe:
        print("No symbols to pull.")
        return 0

    log = None
    if backend == "postgres":
        try:
            log = open_pg_pull_log()
        except PullLogUnavailable as exc:
            print(exc)
            return 2

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
            s = run(client, conn, universe, args.days, today, now, log=log)
        except AuthError as exc:
            print(f"Auth failed ({exc}). Stopping; no retries.")
            return 2
        except PsycopgError as exc:
            print(f"Postgres {PG_PULL_LOG_TABLE} failed mid-run ({_one_line(exc)}). "
                  "Stopping; re-run to resume.")
            return 3
    finally:
        conn.close()
        if log is not None:
            log.close()

    print(
        f"Done: skipped={s['skipped']} ok={s['ok']} empty={s['empty']} "
        f"failed={len(s['failed'])} stats={client.stats()}"
    )
    if s["failed"]:
        print("Failed: " + ", ".join(s["failed"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
