"""Resolve each constituent's ISIN and symbol against Upstox's public NSE instrument master.

The constituents CSV (scanner/constituents.py) goes stale: an ISIN can change (CCAVENUE
moved from INE483S01020 to INE483S01038) and a symbol can be renamed while its ISIN stays.
This module checks each (symbol, ISIN) pair against the master and reports what changed.

    master = load_master()                      # cached for one day
    res = resolve("CCAVENUE", "INE483S01020", master)
    # res.isin == "INE483S01038", res.changed is True

The master is a gzip JSON list. Only NSE equity rows are kept (segment NSE_EQ, instrument_type EQ).
No auth is needed for this file.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "upstox_nse_master.json.gz"
MAX_AGE_SECONDS = 24 * 60 * 60
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


def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def _parse(raw_gz: bytes) -> dict:
    rows = json.loads(gzip.decompress(raw_gz).decode("utf-8"))
    by_symbol: dict = {}
    by_isin: dict = {}
    for row in rows:
        if row.get("segment") != "NSE_EQ" or row.get("instrument_type") != "EQ":
            continue
        symbol = (row.get("trading_symbol") or "").strip().upper()
        isin = (row.get("isin") or "").strip().upper()
        if not symbol or not isin:
            continue
        by_symbol[symbol] = isin
        by_isin[isin] = symbol
    return {"by_symbol": by_symbol, "by_isin": by_isin}


def _is_fresh(path: Path, now: float) -> bool:
    return path.exists() and (now - path.stat().st_mtime) < MAX_AGE_SECONDS


def _write_cache(path: Path, raw_gz: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw_gz)
    os.replace(tmp, path)


def load_master(cache_path: Optional[Path] = None, now: Optional[float] = None, refresh: bool = False) -> dict:
    """Return {"by_symbol": {SYMBOL: isin}, "by_isin": {isin: SYMBOL}} for NSE equities.

    Uses the cache when it is under a day old. Otherwise downloads and refreshes it. If the
    download fails, a stale cache is used with a warning; with no cache at all, RuntimeError.
    refresh=True skips the fresh-cache check and always downloads first.
    """
    path = Path(cache_path) if cache_path is not None else CACHE_PATH
    now = time.time() if now is None else now
    if not refresh and _is_fresh(path, now):
        return _parse(path.read_bytes())
    try:
        raw = _download(MASTER_URL)
        master = _parse(raw)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}".splitlines()[0]
        if not path.exists():
            raise RuntimeError(f"Upstox NSE instrument master unavailable and no cache at {path} ({reason})") from exc
        logger.warning("Upstox NSE instrument master download failed (%s); using stale cache %s", reason, path)
        try:
            return _parse(path.read_bytes())
        except Exception as bad:
            raise RuntimeError(f"Upstox NSE instrument master unavailable: download failed ({reason}) and cache {path} is unreadable") from bad
    _write_cache(path, raw)
    return master


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


def try_load_master(refresh: bool = False) -> tuple[Optional[dict], str]:
    """load_master that never raises. Returns (master, "") or (None, one-line reason)."""
    try:
        return load_master(refresh=refresh), ""
    except Exception as exc:  # noqa: BLE001 - callers keep the CSV ISINs
        reason = f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc).strip() else ''}"
        return None, reason.rstrip(": ")


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


def resolve_all(pairs, conn=None) -> list:
    """Resolve (symbol, csv_isin) pairs against one master load. Records them when conn is given."""
    master = load_master()
    results = [resolve(symbol, isin, master) for symbol, isin in pairs]
    if conn is not None:
        record(conn, results)
    return results
