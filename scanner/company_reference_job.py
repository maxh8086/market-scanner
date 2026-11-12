"""Monthly job: fetch reference data and store it in Postgres.

Stores three things, all in one transaction:
  - NSE's full equity list (EQUITY_L.csv) and the Upstox NSE master, into company_reference;
  - each index in SCAN_INDEXES (names and candidate URLs live in scanner/index_sources.py),
    into index_constituents.

Each index refreshes on its own (rule M-09). An index that fails to download or parse keeps its
last good rows, is listed in the failures, and does not stop the other indices or the master
refresh, which still commits.

Scans then read the database only (decision O3: this runs in the collector job, never in a
scan). The run path never calls this module. It needs a DB role with DELETE and INSERT on the
tables (decision O2). The fetchers are injectable, so tests run offline.

Usage:
    python -m scanner.company_reference_job
The loader password is read from the file named by POSTGRES_LOADER_PASSWORD_FILE. The loader
user comes from POSTGRES_LOADER_USER (default market_scanner_loader). The exit status is 1 when
any index was not refreshed.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import psycopg
import requests
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from scanner import company_reference as cr
from scanner.constituents import HEADERS
from scanner.index_sources import INDEX_SOURCES
from scanner.isin_resolver import DOWNLOAD_TIMEOUT, MASTER_URL

# Index name -> candidate CSV URLs, tried in order (primary host first, fallback last).
# The source of truth is scanner/index_sources.py; add an index there, not here.
SCAN_INDEXES: dict[str, tuple[str, ...]] = dict(INDEX_SOURCES)

logger = logging.getLogger(__name__)


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


def _is_html(content: bytes) -> bool:
    """True when the body is an HTML page (for example an access-denied page), not a CSV."""
    return content.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<")


def fetch_index_bytes(index_name: str) -> bytes:
    """Download one index's constituents CSV. Tries each candidate URL in SCAN_INDEXES order.

    A 404 or network error moves to the next candidate. A 200 response that is an HTML page is
    refused and also moves to the next candidate. Raises RuntimeError when no candidate gives a
    CSV. Failures record the host and the error type only, never the query string.
    """
    urls = SCAN_INDEXES.get(index_name)
    if urls is None:
        raise RuntimeError(f"index {index_name!r} is not in SCAN_INDEXES")
    failures: list[str] = []
    for url in urls:
        host = urlsplit(url).netloc
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            failures.append(f"{host} {type(exc).__name__}")
            continue
        if _is_html(resp.content):
            failures.append(f"{host} HTML page, not a CSV")
            continue
        return resp.content
    raise RuntimeError(f"index {index_name!r} download failed from every source ({'; '.join(failures)})")


def fetch_all_indexes() -> dict[str, bytes]:
    """Download every index in SCAN_INDEXES. A failed index is logged and left out of the result,
    so the caller sees its name missing and can report it. The other indices still download."""
    out: dict[str, bytes] = {}
    for name in SCAN_INDEXES:
        try:
            out[name] = fetch_index_bytes(name)
        except RuntimeError as exc:
            logger.warning("%s", exc)
    return out


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
    failures: list[str] | None = None,
) -> dict[str, int]:
    """Fetch and parse every source first, then write them all in one transaction.

    The NSE equity list and the Upstox master must fetch and parse, or the error propagates and
    nothing is written. Each index is independent: an index that is missing from the download,
    fails to parse, or parses to zero rows is appended to `failures` and skipped, so its
    last good rows stay in place. The other indices and the master refresh still commit.
    Returns row counts keyed by source name (nse_csv, upstox_master) and by index name.
    """
    if failures is None:
        failures = []
    csv_rows = parse_csv_bytes(fetch_csv(), today)
    master_rows = cr.master_rows(fetch_master(), today)
    index_raw = fetch_indexes()
    index_rows: dict[str, list[dict]] = {}
    for name in SCAN_INDEXES:
        if name not in index_raw:
            failures.append(f"{name}: download failed, last good rows kept")
            continue
        try:
            rows = parse_index_bytes(index_raw[name], name, today)
            if not rows:
                raise cr.EmptySourceError(f"{name}: no constituents parsed")
        except Exception as exc:  # one bad index must not stop the others or the master refresh
            failures.append(f"{name}: {exc}; last good rows kept")
            continue
        index_rows[name] = rows

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
    failures: list[str] = []
    try:
        counts = run_refresh(conn, today=date.today(), failures=failures)
    finally:
        conn.close()
    print(f"reference data refreshed: {counts}")
    for item in failures:
        print(f"index not refreshed: {item}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
