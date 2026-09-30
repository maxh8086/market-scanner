"""MongoDB document store for fetched-but-unparsed source material.

Identical public API to scanner/docstore.py (TinyDB backend), but backed by MongoDB.
Selection per BUILD_PLAN: DOCSTORE_BACKEND=mongo or tinydb.

All writes are upserts on the unique key, never blind inserts. Unique indexes are
created idempotently at open_db(). Every document carries expires_at for retention.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from pymongo import MongoClient, errors
from pymongo.collection import Collection

from scanner import infra, retention


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expiry(base) -> str:
    """Date after which the record may be purged (see scanner/retention.py)."""
    return retention.expires_at(base, retention.load())


class MongoDB:
    """Handle object for Mongo backend, matching TinyDB's interface where needed."""

    def __init__(self, client: MongoClient, db_name: str):
        self.client = client
        self.db = client[db_name]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create unique indexes idempotently."""
        # filings: unique on seq_id
        try:
            self.db.filings.create_index(
                "seq_id", unique=True, background=True, name="seq_id_unique"
            )
        except (errors.DuplicateKeyError, errors.OperationFailure):
            pass

        # extractions: unique on (seq_id, kind, prompt_version, model)
        # where prompt_version and model are in the key if they exist
        try:
            self.db.extractions.create_index(
                [("seq_id", 1), ("kind", 1), ("prompt_version", 1), ("model", 1)],
                unique=True,
                background=True,
                name="extraction_unique",
            )
        except (errors.DuplicateKeyError, errors.OperationFailure):
            pass

        # conclusions: unique on (symbol, as_of); additionally record packet_hash
        try:
            self.db.conclusions.create_index(
                [("symbol", 1), ("as_of", 1)],
                unique=True,
                background=True,
                name="conclusion_unique",
            )
        except (errors.DuplicateKeyError, errors.OperationFailure):
            pass

        # fundamentals: unique on (symbol, as_of) where as_of is fetch date
        try:
            self.db.fundamentals.create_index(
                [("symbol", 1), ("as_of", 1)],
                unique=True,
                background=True,
                name="fundamentals_unique",
            )
        except (errors.DuplicateKeyError, errors.OperationFailure):
            pass

        # Indexes on expires_at for retention purges
        for collection_name in ["filings", "extractions", "conclusions", "fundamentals"]:
            try:
                self.db[collection_name].create_index(
                    "expires_at", background=True, name=f"{collection_name}_expiry"
                )
            except (errors.DuplicateKeyError, errors.OperationFailure):
                pass

    def close(self) -> None:
        self.client.close()

    def table(self, name: str) -> Collection:
        """Return a MongoDB collection (matches TinyDB table interface)."""
        return self.db[name]


def open_db(uri: Optional[str] = None, db_name: Optional[str] = None) -> MongoDB:
    """Open (creating if needed) the MongoDB document store."""
    uri = uri or os.environ.get(
        "MONGO_URI", "mongodb://localhost:27017"
    )
    db_name = db_name or os.environ.get("MONGO_DB", "ath_scanner")

    # Localize hostnames when INFRA_LOCAL is set
    uri = infra.localize(uri)

    client = MongoClient(uri)
    # Test connection
    try:
        client.admin.command("ping")
    except Exception as e:
        client.close()
        raise RuntimeError(f"Cannot connect to MongoDB at {uri}: {e}")

    return MongoDB(client, db_name)


def db() -> MongoDB:
    """Open the MongoDB document store using MONGO_URI and MONGO_DB env vars.

    This is the primary contract function for the MongoDB backend.
    """
    return open_db()


# --------------------------------------------------------------------------
# filings
# --------------------------------------------------------------------------


def put_filing(db: MongoDB, filing: dict) -> None:
    """Upsert one filing document. seq_id is NSE's own id."""
    seq_id = str(filing.get("seq_id") or "")
    if not seq_id:
        raise ValueError("filing needs a seq_id")

    doc = dict(filing, seq_id=seq_id, stored_at=_now())
    doc["expires_at"] = _expiry(doc.get("an_date") or doc["stored_at"])

    db.table("filings").update_one(
        {"seq_id": seq_id}, {"$set": doc}, upsert=True
    )


def get_filing(db: MongoDB, seq_id: str) -> Optional[dict]:
    doc = db.table("filings").find_one({"seq_id": str(seq_id)})
    return dict(doc) if doc else None


def has_filing_text(db: MongoDB, seq_id: str) -> bool:
    """True when this filing's PDF has already been fetched and text extracted."""
    doc = get_filing(db, seq_id)
    return bool(doc and doc.get("raw_text"))


def filings_for(db: MongoDB, symbol: str) -> list[dict]:
    return [dict(d) for d in db.table("filings").find({"symbol": symbol})]


def filings_by_kind(db: MongoDB, kind: str) -> list[dict]:
    return [dict(d) for d in db.table("filings").find({"kind": kind})]


def all_filings(db: MongoDB) -> list[dict]:
    return [dict(d) for d in db.table("filings").find()]


# --------------------------------------------------------------------------
# fundamentals
# --------------------------------------------------------------------------


def put_fundamentals(db: MongoDB, symbol: str, payload: dict) -> None:
    doc = dict(payload, symbol=symbol, stored_at=_now())
    doc["expires_at"] = _expiry(doc["stored_at"])

    # Fundamentals are keyed on (symbol, as_of) where as_of is the fetch date (YYYY-MM-DD)
    # If as_of is not in payload, use today's date (when the fetch happened)
    from datetime import date as date_type
    if doc.get("as_of"):
        as_of = doc["as_of"]
    else:
        as_of = date_type.today().isoformat()
    doc["as_of"] = as_of

    db.table("fundamentals").update_one(
        {"symbol": symbol, "as_of": as_of}, {"$set": doc}, upsert=True
    )


def get_fundamentals(db: MongoDB, symbol: str) -> Optional[dict]:
    """Return the latest fundamentals for a symbol."""
    doc = db.table("fundamentals").find_one(
        {"symbol": symbol},
        sort=[("as_of", -1)]  # Get the latest
    )
    return dict(doc) if doc else None


def all_fundamentals(db: MongoDB) -> list[dict]:
    return [dict(d) for d in db.table("fundamentals").find()]


def fundamentals_age_days(db: MongoDB, symbol: str) -> Optional[float]:
    """How stale a symbol's fundamentals are, or None if absent."""
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


def put_extraction(db: MongoDB, seq_id: str, kind: str, payload: dict) -> None:
    doc = dict(payload, seq_id=str(seq_id), kind=kind, stored_at=_now())
    doc["expires_at"] = _expiry(doc["stored_at"])

    # Unique key includes prompt_version and model if they exist in the payload
    key_doc = {
        "seq_id": str(seq_id),
        "kind": kind,
        "prompt_version": doc.get("prompt_version"),
        "model": doc.get("model"),
    }

    db.table("extractions").update_one(key_doc, {"$set": doc}, upsert=True)


def get_extraction(db: MongoDB, seq_id: str, kind: str) -> Optional[dict]:
    # Find the extraction for this seq_id and kind, regardless of model/prompt_version
    # For backward compatibility, just match on seq_id and kind
    doc = db.table("extractions").find_one(
        {"seq_id": str(seq_id), "kind": kind}
    )
    return dict(doc) if doc else None


def extractions_by_kind(db: MongoDB, kind: str) -> list[dict]:
    return [dict(d) for d in db.table("extractions").find({"kind": kind})]


# --------------------------------------------------------------------------
# conclusions (one per stock per scan date; the model's reading of the facts)
# --------------------------------------------------------------------------


def put_conclusion(db: MongoDB, symbol: str, as_of: str, payload: dict) -> None:
    doc = dict(payload, symbol=symbol, as_of=as_of, stored_at=_now())
    doc["expires_at"] = _expiry(as_of)

    db.table("conclusions").update_one(
        {"symbol": symbol, "as_of": as_of}, {"$set": doc}, upsert=True
    )


def get_conclusion(db: MongoDB, symbol: str, as_of: str) -> Optional[dict]:
    doc = db.table("conclusions").find_one({"symbol": symbol, "as_of": as_of})
    return dict(doc) if doc else None


def conclusions_for(db: MongoDB, as_of: str) -> list[dict]:
    return [dict(d) for d in db.table("conclusions").find({"as_of": as_of})]


# --------------------------------------------------------------------------


def stats(db: MongoDB) -> dict[str, Any]:
    """Counts and estimated sizes."""
    return {
        "filings": db.table("filings").count_documents({}),
        "filings_with_text": db.table("filings").count_documents(
            {"raw_text": {"$exists": True, "$ne": ""}}
        ),
        "fundamentals": db.table("fundamentals").count_documents({}),
        "extractions": db.table("extractions").count_documents({}),
        "conclusions": db.table("conclusions").count_documents({}),
    }


def purge(db: MongoDB, cfg: retention.Retention, today=None,
          dry_run: bool = False) -> dict[str, int]:
    """Delete expired, processed records from MongoDB; mirrors retention.purge_docstore."""
    from datetime import date

    counts = {"filings": 0, "extractions": 0, "conclusions": 0, "fundamentals": 0}
    if not cfg.purge:
        return counts

    today = today or date.today()
    today_str = today.isoformat()

    # Find extracted seq_ids for the only_when_processed check
    extracted = set()
    if cfg.only_when_processed:
        for doc in db.table("extractions").find({"seq_id": {"$exists": True}}):
            extracted.add(str(doc.get("seq_id", "")))

    # Filings: delete if expired AND (processed OR not only_when_processed)
    filing_filter = {"expires_at": {"$lt": today_str}}
    if cfg.only_when_processed:
        filing_docs = list(db.table("filings").find(filing_filter))
        for doc in filing_docs:
            if str(doc.get("seq_id", "")) in extracted:
                if not dry_run:
                    db.table("filings").delete_one({"_id": doc["_id"]})
                counts["filings"] += 1
    else:
        if not dry_run:
            result = db.table("filings").delete_many(filing_filter)
            counts["filings"] = result.deleted_count
        else:
            counts["filings"] = db.table("filings").count_documents(filing_filter)

    # Extractions: delete if expired (always)
    extraction_filter = {"expires_at": {"$lt": today_str}}
    if not dry_run:
        result = db.table("extractions").delete_many(extraction_filter)
        counts["extractions"] = result.deleted_count
    else:
        counts["extractions"] = db.table("extractions").count_documents(extraction_filter)

    # Conclusions: delete if expired (always)
    conclusion_filter = {"expires_at": {"$lt": today_str}}
    if not dry_run:
        result = db.table("conclusions").delete_many(conclusion_filter)
        counts["conclusions"] = result.deleted_count
    else:
        counts["conclusions"] = db.table("conclusions").count_documents(conclusion_filter)

    # Fundamentals: delete if expired (always)
    fundamentals_filter = {"expires_at": {"$lt": today_str}}
    if not dry_run:
        result = db.table("fundamentals").delete_many(fundamentals_filter)
        counts["fundamentals"] = result.deleted_count
    else:
        counts["fundamentals"] = db.table("fundamentals").count_documents(fundamentals_filter)

    return counts
