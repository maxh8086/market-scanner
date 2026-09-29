"""How long stored data is kept, and the purge that enforces it.

Every record gets an ``expires_at`` date when it is stored: its own date (filing
date, scan date, fetch date) plus ``years`` from ``config/retention.json``. The
purge deletes a record only once it is past that date **and processed** -- a
filing that never produced an extraction is kept, so nothing is dropped before
it has done its job. ``purge: false`` turns deletion off entirely; the dates are
still written, so it can be switched on later.

Two stores follow the same rule: the TinyDB document store (here) and the Neo4j
graph (``scanner/graph.py``, which reuses ``expires_at``/``is_expired``).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from tinydb import Query, TinyDB

from scanner import docstore

CONFIG_PATH = Path("config/retention.json")
DEFAULT_YEARS = 3


@dataclass(frozen=True)
class Retention:
    years: int = DEFAULT_YEARS
    purge: bool = True
    only_when_processed: bool = True


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def load(path: Path | str = CONFIG_PATH, env: Optional[dict] = None) -> Retention:
    """Config file, then environment overrides. A missing or broken file means the
    defaults (3 years, purge on): retention must never stop a run."""
    env = os.environ if env is None else env
    raw: dict = {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    years, purge = raw.get("years", DEFAULT_YEARS), raw.get("purge", True)
    if env.get("RETENTION_YEARS"):
        years = env["RETENTION_YEARS"]
    if env.get("RETENTION_PURGE") not in (None, ""):
        purge = _truthy(env["RETENTION_PURGE"])
    try:
        years = max(int(years), 0)
    except (TypeError, ValueError):
        years = DEFAULT_YEARS
    return Retention(years=years, purge=bool(purge),
                     only_when_processed=bool(raw.get("only_when_processed", True)))


def parse_date(value) -> Optional[date]:
    """Any date string the store holds (ISO, ISO with time, or NSE's dd-Mon-yyyy)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(text[:11].strip(), fmt).date()
        except ValueError:
            continue
    return None


def expires_at(base, cfg: Retention) -> str:
    """ISO expiry date for a record dated ``base``; today's date if ``base`` is unreadable."""
    d = parse_date(base) or date.today()
    try:
        return d.replace(year=d.year + cfg.years).isoformat()
    except ValueError:                       # 29 February
        return (d + timedelta(days=365 * cfg.years)).isoformat()


def is_expired(expiry, today: Optional[date] = None) -> bool:
    d = parse_date(expiry)
    return bool(d and d < (today or date.today()))


# --------------------------------------------------------------------------
# TinyDB document store
# --------------------------------------------------------------------------

def _filing_expiry(doc, cfg: Retention) -> str:
    return doc.get("expires_at") or expires_at(doc.get("an_date") or doc.get("stored_at"), cfg)


def purge_docstore(db: TinyDB, cfg: Retention, today: Optional[date] = None,
                   dry_run: bool = False) -> dict[str, int]:
    """Delete expired, processed records; returns what was (or would be) removed."""
    counts = {"filings": 0, "extractions": 0, "conclusions": 0, "fundamentals": 0}
    if not cfg.purge:
        return counts
    today = today or date.today()
    ext_table = db.table(docstore.EXTRACTIONS)
    extracted = {str(e.get("seq_id")) for e in ext_table.all()}

    for f in db.table(docstore.FILINGS).all():
        if not is_expired(_filing_expiry(f, cfg), today):
            continue
        if cfg.only_when_processed and str(f["seq_id"]) not in extracted:
            continue
        counts["filings"] += 1
        if not dry_run:
            db.table(docstore.FILINGS).remove(doc_ids=[f.doc_id])
        for e in ext_table.search(Query().seq_id == str(f["seq_id"])):
            counts["extractions"] += 1
            if not dry_run:
                ext_table.remove(doc_ids=[e.doc_id])

    for c in db.table(docstore.CONCLUSIONS).all():
        if is_expired(c.get("expires_at") or expires_at(c.get("as_of"), cfg), today):
            counts["conclusions"] += 1
            if not dry_run:
                db.table(docstore.CONCLUSIONS).remove(doc_ids=[c.doc_id])

    for fu in db.table(docstore.FUNDAMENTALS).all():
        if is_expired(fu.get("expires_at") or expires_at(fu.get("stored_at"), cfg), today):
            counts["fundamentals"] += 1
            if not dry_run:
                db.table(docstore.FUNDAMENTALS).remove(doc_ids=[fu.doc_id])
    return counts
