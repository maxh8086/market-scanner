"""Resolve each constituent's ISIN and symbol against the Upstox NSE instrument master.

The constituents list (scanner/constituents.py) goes stale: an ISIN can change (CCAVENUE
moved from INE483S01020 to INE483S01038) and a symbol can be renamed while its ISIN stays.
This module checks each (symbol, ISIN) pair against the master and reports what changed.

    master = load_master(conn)                  # read from company_reference (monthly job)
    res = resolve("CCAVENUE", "INE483S01020", master)
    # res.isin == "INE483S01038", res.changed is True

The master is stored in Postgres by the monthly job (scanner/company_reference_job.py). This
module never downloads it at run time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from scanner import company_reference as cr

logger = logging.getLogger(__name__)

# Used by the monthly job (scanner/company_reference_job.py); not used at run time.
MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
SOURCE = "upstox_nse_master"
DOWNLOAD_TIMEOUT = 60


@dataclass
class Resolution:
    symbol: str
    isin: str
    changed: bool = False
    renamed_from: Optional[str] = None
    reason: str = ""
    resolved: bool = True


def load_master(conn=None) -> dict:
    """Return {"by_symbol": {SYMBOL: isin}, "by_isin": {isin: SYMBOL}} for NSE equities.

    Read from company_reference (source upstox_master). Raises RuntimeError when no
    connection is given or the table has no master rows.
    """
    if conn is None:
        raise RuntimeError("no database connection: the Upstox master is read from company_reference")
    return cr.load_master_from_db(conn)


def resolve(symbol: str, csv_isin: Optional[str], master: Optional[dict] = None) -> Resolution:
    """Map one constituent (symbol, ISIN from the CSV) onto the current master.

    1. Symbol is in the master: use the master ISIN. changed is True when it differs from the CSV.
    2. Symbol is not in the master, but the CSV ISIN belongs to another symbol: a rename.
    3. Otherwise: unresolved. The CSV values are kept and changed is False.
    """
    if master is None:
        master = load_master()
    sym = (symbol or "").strip().upper()
    isin = (csv_isin or "").strip().upper()
    by_symbol = master["by_symbol"]
    by_isin = master["by_isin"]

    if sym in by_symbol:
        current = by_symbol[sym]
        if not isin:
            return Resolution(sym, current, changed=True, reason="CSV ISIN blank; filled from master")
        if current == isin:
            return Resolution(sym, current, reason="ISIN matches master")
        return Resolution(sym, current, changed=True, reason=f"ISIN changed in master (was {isin})")

    if isin and isin in by_isin and by_isin[isin] != sym:
        new_symbol = by_isin[isin]
        return Resolution(new_symbol, isin, changed=True, renamed_from=sym,
                          reason=f"renamed: ISIN now listed as {new_symbol}")

    return Resolution(sym, isin, changed=False, reason="not found in master", resolved=False)


def try_load_master(conn=None) -> tuple[Optional[dict], str]:
    """load_master that never raises. Returns (master, "") or (None, one-line reason)."""
    try:
        return load_master(conn), ""
    except Exception as exc:  # noqa: BLE001 - callers keep the constituents ISINs
        first = (str(exc).splitlines() or [""])[0].strip()
        reason = f"{type(exc).__name__}: {first}" if first else type(exc).__name__
        return None, reason


def describe_change(symbol: str, csv_isin: Optional[str], res: Resolution) -> str:
    """One console line for a changed ISIN or a rename. The storage symbol is the CSV symbol."""
    old = (csv_isin or "").strip().upper() or "(blank)"
    if res.renamed_from:
        return f"{res.renamed_from} -> {res.symbol}: renamed, ISIN {res.isin}"
    return f"{symbol}: ISIN {old} -> {res.isin}"


_UPSERT_HISTORY = """INSERT INTO isin_history (symbol, isin, first_seen, last_seen, source)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (symbol, isin) DO UPDATE SET last_seen = EXCLUDED.last_seen, source = EXCLUDED.source"""

_UPSERT_ALIAS = """INSERT INTO symbol_alias (old_symbol, new_symbol, isin, seen_at)
VALUES (%s, %s, %s, %s)
ON CONFLICT (old_symbol, new_symbol, isin) DO UPDATE SET seen_at = EXCLUDED.seen_at"""


def record(conn, resolutions, today: Optional[date] = None) -> int:
    """Write resolved pairs to isin_history and renames to symbol_alias. Returns rows written.

    first_seen is kept on conflict; last_seen moves to today. The caller owns the transaction.
    """
    today = today or date.today()
    written = 0
    for r in resolutions:
        if not r.resolved or not r.isin:
            continue
        conn.execute(_UPSERT_HISTORY, (r.symbol, r.isin, today, today, SOURCE))
        written += 1
        if r.renamed_from:
            conn.execute(_UPSERT_ALIAS, (r.renamed_from, r.symbol, r.isin, today))
            written += 1
    return written


def resolve_all(pairs, conn, record_results: bool = True) -> list:
    """Resolve (symbol, csv_isin) pairs against one master read from conn.
    Records the results with record(conn, results) only when record_results is True."""
    master = load_master(conn)
    results = [resolve(symbol, isin, master) for symbol, isin in pairs]
    if record_results:
        record(conn, results)
    return results
