"""Monthly job: fetch reference data and store it in Postgres.

Stores three things, all in one transaction:
  - NSE's full equity list (EQUITY_L.csv) and the Upstox NSE master, into company_reference;
  - each index in SCAN_INDEXES (for example NIFTY TOTAL MARKET), into index_constituents.

Scans then read the database only (decision O3: this runs in the collector job, never in a
scan). The run path never calls this module. It needs a DB role with DELETE and INSERT on the
tables (decision O2). The fetchers are injectable, so tests run offline.

Usage (once the loader role exists):
    python -m scanner.company_reference_job
The loader password is read from the file named by POSTGRES_LOADER_PASSWORD_FILE. The loader
user comes from POSTGRES_LOADER_USER (default market_scanner_loader).
"""
from __future__ import annotations

import csv
import io
import os
from datetime import date
from pathlib import Path
from typing import Callable

import psycopg
import requests
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from scanner import company_reference as cr
from scanner.constituents import HEADERS
from scanner.isin_resolver import DOWNLOAD_TIMEOUT, MASTER_URL

# Index name -> (primary URL, fallback URL) of its constituents CSV.
# To scan another index, add its name and two source URLs here; no other change is needed.
SCAN_INDEXES: dict[str, tuple[str, str]] = {
    "NIFTY TOTAL MARKET": (
        "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv",
    ),
}


def fetch_csv_bytes() -> bytes:
    """Download NSE's full equity list (EQUITY_L.csv, all series)."""
    try:
        resp = requests.get(cr.EQUITY_LIST_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"NSE equity list download failed: {exc}") from exc
    return resp.content


def fetch_master_bytes() -> bytes:
    """Download the Upstox NSE instrument master (gzipped JSON)."""
    resp = requests.get(MASTER_URL, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def fetch_index_bytes(index_name: str) -> bytes:
    """Download one index's constituents CSV. Tries each source in SCAN_INDEXES order."""
    urls = SCAN_INDEXES.get(index_name)
    if urls is None:
        raise RuntimeError(f"index {index_name!r} is not in SCAN_INDEXES")
    failures: list[str] = []
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            failures.append(type(exc).__name__)
    raise RuntimeError(f"index {index_name!r} download failed from every source ({', '.join(failures)})")


def fetch_all_indexes() -> dict[str, bytes]:
    """Download every index in SCAN_INDEXES. Keys are index names."""
    return {name: fetch_index_bytes(name) for name in SCAN_INDEXES}


def parse_csv_bytes(raw: bytes, as_of: date) -> list[cr.RefRow]:
    text = raw.decode("utf-8-sig")
    return cr.equity_list_rows(csv.DictReader(io.StringIO(text)), as_of)


def parse_index_bytes(raw: bytes, index_name: str, as_of: date) -> list[dict]:
    text = raw.decode("utf-8-sig")
    return cr.constituent_rows(csv.DictReader(io.StringIO(text)), as_of, index_name)


def run_refresh(
    conn,
    *,
    today: date,
    fetch_csv: Callable[[], bytes] = fetch_csv_bytes,
    fetch_master: Callable[[], bytes] = fetch_master_bytes,
    fetch_indexes: Callable[[], dict[str, bytes]] = fetch_all_indexes,
) -> dict[str, int]:
    """Fetch and parse every source first, then write them all in one transaction.

    If any fetch or parse fails, or any source comes back empty, nothing is written and the
    error propagates, so last month's rows stay in place. Returns row counts keyed by source
    name (nse_csv, upstox_master) and by index name.
    """
    csv_rows = parse_csv_bytes(fetch_csv(), today)
    master_rows = cr.master_rows(fetch_master(), today)
    index_raw = fetch_indexes()
    missing = [name for name in SCAN_INDEXES if name not in index_raw]
    if missing:
        raise RuntimeError(f"index download missing for: {', '.join(missing)}; refresh refused")
    index_rows = {name: parse_index_bytes(index_raw[name], name, today) for name in SCAN_INDEXES}
    for name, rows in index_rows.items():
        if not rows:
            raise cr.EmptySourceError(f"{name}: no constituents parsed; refresh refused, last month's rows kept")

    counts: dict[str, int] = {}
    with conn.transaction():  # the inner calls run as savepoints of this one
        counts.update(cr.refresh(conn, {cr.SOURCE_CSV: csv_rows, cr.SOURCE_MASTER: master_rows}))
        for name, rows in index_rows.items():
            counts[name] = cr.replace_index_constituents(conn, name, rows, today)
    return counts


LOADER_USER_DEFAULT = "market_scanner_loader"


def loader_dsn(env=None) -> str:
    """Connection string for the loader role. The password is read from the file named by
    POSTGRES_LOADER_PASSWORD_FILE, never from an environment value. Host, port and database
    come from POSTGRES_HOST, POSTGRES_PORT and POSTGRES_DB. Errors name the variable, never the
    password."""
    env = os.environ if env is None else env
    path = env.get("POSTGRES_LOADER_PASSWORD_FILE")
    if not path:
        raise RuntimeError("POSTGRES_LOADER_PASSWORD_FILE is unset: point it at the loader password file.")
    try:
        password = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"cannot read the loader password file named by POSTGRES_LOADER_PASSWORD_FILE: {exc.strerror}") from None
    if not password:
        raise RuntimeError("the loader password file is empty.")
    missing = [k for k in ("POSTGRES_HOST", "POSTGRES_DB") if not env.get(k)]
    if missing:
        raise RuntimeError("Postgres is not configured: " + ", ".join(missing) + " unset.")
    return make_conninfo(
        host=env["POSTGRES_HOST"],
        port=env.get("POSTGRES_PORT", "5432"),
        dbname=env["POSTGRES_DB"],
        user=env.get("POSTGRES_LOADER_USER", LOADER_USER_DEFAULT),
        password=password,
    )


def main() -> int:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())
    conn = psycopg.connect(loader_dsn(), row_factory=dict_row)
    try:
        counts = run_refresh(conn, today=date.today())
    finally:
        conn.close()
    print(f"reference data refreshed: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
