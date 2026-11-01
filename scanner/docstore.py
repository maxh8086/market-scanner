"""TinyDB document store for fetched-but-unparsed source material.

Why a document store rather than the existing SQLite caches: the things kept
here are whole documents of irregular shape -- PDF text, a screener page's
ratio blocks, an AI extraction -- and the point is to **separate fetching from
parsing**. Re-parsing with a better regex must never re-download 450 PDFs, and
an AI extraction is worth keeping verbatim so a prompt change can be re-run
offline and diffed against the old answer.

Four collections, keyed so a re-run is idempotent:

  filings       one per NSE filing PDF, keyed `seq_id` (NSE's own id)
  fundamentals  one per symbol, keyed `symbol`
  extractions   one per (seq_id, kind), for AI-derived fields
  conclusions   one per (symbol, as_of), the per-stock LLM reading

Scope note: this holds only documents we actually download -- order and
expansion filings for matched symbols, a few hundred -- not all 165,881
announcements. TinyDB loads its whole JSON file into memory, so if this ever
needs to cover the full announcement universe it should move to SQLite with a
JSON column. `stats()` exists to make that ceiling visible before it bites.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from tinydb import Query, TinyDB
from tinydb.storages import JSONStorage
from tinydb.table import Document

DB_PATH = Path("data/documents.json")

FILINGS = "filings"
FUNDAMENTALS = "fundamentals"
EXTRACTIONS = "extractions"
CONCLUSIONS = "conclusions"

# Bump when a stored document's shape changes in a way parsers depend on.
SCHEMA_VERSION = 1
_META = "_meta"


class _CompactStorage(JSONStorage):
    """JSONStorage without the indent, so PDF text does not triple the file."""

    def write(self, data):  # noqa: D102
        self._handle.seek(0)
        serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        self._handle.write(serialized)
        self._handle.flush()
        self._handle.truncate()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expiry(base) -> str:
    """Date after which the record may be purged (see scanner/retention.py)."""
    from scanner import retention          # retention imports this module
    return retention.expires_at(base, retention.load())


def open_db(path: Path | str = DB_PATH) -> TinyDB:
    """Open (creating if needed) the document store and record its schema.

    Selection per BUILD_PLAN: DOCSTORE_BACKEND env var controls which backend.
    - mongo: uses MongoDB via scanner.mongo
    - tinydb (default): uses TinyDB at path
    """
    import os
    backend = os.environ.get("DOCSTORE_BACKEND", "tinydb").lower()

    if backend == "mongo":
        from scanner import mongo
        return mongo.open_db()

    # TinyDB backend (default)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    db = TinyDB(p, storage=_CompactStorage, encoding="utf-8")
    meta = db.table(_META)
    if not meta.all():
        meta.insert({"schema_version": SCHEMA_VERSION, "created": _now()})
    return db


def schema_version(db: TinyDB) -> int:
    rows = db.table(_META).all()
    return int(rows[0].get("schema_version", 0)) if rows else 0


# --------------------------------------------------------------------------
# filings
# --------------------------------------------------------------------------

def put_filing(db: TinyDB, filing: dict) -> None:
    """Upsert one filing document. `seq_id` is NSE's own id, so this is
    idempotent across re-runs and across overlapping date windows."""
    seq_id = str(filing.get("seq_id") or "")
    if not seq_id:
        raise ValueError("filing needs a seq_id")
    doc = dict(filing, seq_id=seq_id, stored_at=_now())
    doc["expires_at"] = _expiry(doc.get("an_date") or doc["stored_at"])
    db.table(FILINGS).upsert(doc, Query().seq_id == seq_id)


def get_filing(db: TinyDB, seq_id: str) -> Optional[Document]:
    return db.table(FILINGS).get(Query().seq_id == str(seq_id))


def has_filing_text(db: TinyDB, seq_id: str) -> bool:
    """True when this filing's PDF has already been fetched and text extracted.

    Used to skip the download on a re-run. A row that exists but recorded a
    fetch error returns False so the next run retries it.
    """
    doc = get_filing(db, seq_id)
    return bool(doc and doc.get("raw_text"))


def filings_for(db: TinyDB, symbol: str) -> list[Document]:
    return db.table(FILINGS).search(Query().symbol == symbol)

def filings_by_kind(db: TinyDB, kind: str) -> list[Document]:
    return db.table(FILINGS).search(Query().kind == kind)


def all_filings(db: TinyDB) -> list[Document]:
    return db.table(FILINGS).all()


# --------------------------------------------------------------------------
# fundamentals
# --------------------------------------------------------------------------

def put_fundamentals(db: TinyDB, symbol: str, payload: dict) -> None:
    doc = dict(payload, symbol=symbol, stored_at=_now())
    doc["expires_at"] = _expiry(doc["stored_at"])
    db.table(FUNDAMENTALS).upsert(doc, Query().symbol == symbol)


def get_fundamentals(db: TinyDB, symbol: str) -> Optional[Document]:
    return db.table(FUNDAMENTALS).get(Query().symbol == symbol)


def all_fundamentals(db: TinyDB) -> list[Document]:
    return db.table(FUNDAMENTALS).all()


def fundamentals_age_days(db: TinyDB, symbol: str) -> Optional[float]:
    """How stale a symbol's fundamentals are, or None if absent.

    Market cap moves daily, so callers refresh on age rather than assuming a
    cached row is good forever.
    """
    doc = get_fundamentals(db, symbol)
    if not doc or not doc.get("stored_at"):
        return None
    try:
        then = datetime.fromisoformat(doc["stored_at"])
    except (ValueError, TypeError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 86400.0


# --------------------------------------------------------------------------
# extractions (AI-derived, kept verbatim so a prompt change can be diffed)
# --------------------------------------------------------------------------

def put_extraction(db: TinyDB, seq_id: str, kind: str, payload: dict) -> None:
    doc = dict(payload, seq_id=str(seq_id), kind=kind, stored_at=_now())
    doc["expires_at"] = _expiry(doc["stored_at"])
    q = Query()
    db.table(EXTRACTIONS).upsert(doc, (q.seq_id == str(seq_id)) & (q.kind == kind))


def get_extraction(db: TinyDB, seq_id: str, kind: str) -> Optional[Document]:
    q = Query()
    return db.table(EXTRACTIONS).get((q.seq_id == str(seq_id)) & (q.kind == kind))


def extractions_by_kind(db: TinyDB, kind: str) -> list[Document]:
    return db.table(EXTRACTIONS).search(Query().kind == kind)


# --------------------------------------------------------------------------
# conclusions (one per stock per scan date; the model's reading of the facts)
# --------------------------------------------------------------------------

def put_conclusion(db: TinyDB, symbol: str, as_of: str, payload: dict) -> None:
    doc = dict(payload, symbol=symbol, as_of=as_of, stored_at=_now())
    doc["expires_at"] = _expiry(as_of)
    q = Query()
    db.table(CONCLUSIONS).upsert(doc, (q.symbol == symbol) & (q.as_of == as_of))


def get_conclusion(db: TinyDB, symbol: str, as_of: str) -> Optional[Document]:
    q = Query()
    return db.table(CONCLUSIONS).get((q.symbol == symbol) & (q.as_of == as_of))


def conclusions_for(db: TinyDB, as_of: str) -> list[Document]:
    return db.table(CONCLUSIONS).search(Query().as_of == as_of)


# --------------------------------------------------------------------------

def stats(db: TinyDB, path: Path | str = DB_PATH) -> dict[str, Any]:
    """Counts and on-disk size -- the memory ceiling made visible."""
    # Handle both TinyDB and MongoDB backends
    try:
        from scanner import mongo
        if isinstance(db, mongo.MongoDB):
            return mongo.stats(db)
    except ImportError:
        pass

    # TinyDB path
    p = Path(path)
    filings = db.table(FILINGS).all()
    return {
        "schema_version": schema_version(db),
        "filings": len(filings),
        "filings_with_text": sum(1 for f in filings if f.get("raw_text")),
        "fundamentals": len(db.table(FUNDAMENTALS).all()),
        "extractions": len(db.table(EXTRACTIONS).all()),
        "conclusions": len(db.table(CONCLUSIONS).all()),
        "bytes_on_disk": p.stat().st_size if p.exists() else 0,
    }
