"""One-off import: copy data from TinyDB (data/documents.json) to MongoDB.

Idempotent: running a second time adds zero rows (upserts on unique keys).
Does not delete data/documents.json.

Usage:
    python -m scanner.mongo_import           # import for real
    python -m scanner.mongo_import --dry-run # show what would happen
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scanner import docstore, mongo

DB_PATH = Path("data/documents.json")


def import_data(mongo_db: mongo.MongoDB, tinydb_path: Path = DB_PATH,
                dry_run: bool = False) -> dict[str, int]:
    """Copy all collections from TinyDB to MongoDB.

    Returns counts of documents processed (upserts, which may be 0 on re-run).
    """
    counts = {"filings": 0, "extractions": 0, "conclusions": 0, "fundamentals": 0}

    if not tinydb_path.exists():
        print(f"TinyDB file not found: {tinydb_path}")
        return counts

    # Open TinyDB
    tinydb = docstore.TinyDB(
        str(tinydb_path),
        storage=docstore._CompactStorage,
        encoding="utf-8"
    )

    try:
        # Import filings
        for doc in tinydb.table(docstore.FILINGS).all():
            doc_dict = dict(doc)
            if not dry_run:
                mongo.put_filing(mongo_db, doc_dict)
            counts["filings"] += 1

        # Import extractions
        for doc in tinydb.table(docstore.EXTRACTIONS).all():
            doc_dict = dict(doc)
            seq_id = doc_dict.get("seq_id")
            kind = doc_dict.get("kind")
            if seq_id and kind:
                if not dry_run:
                    mongo.put_extraction(mongo_db, seq_id, kind, doc_dict)
                counts["extractions"] += 1

        # Import conclusions
        for doc in tinydb.table(docstore.CONCLUSIONS).all():
            doc_dict = dict(doc)
            symbol = doc_dict.get("symbol")
            as_of = doc_dict.get("as_of")
            if symbol and as_of:
                if not dry_run:
                    mongo.put_conclusion(mongo_db, symbol, as_of, doc_dict)
                counts["conclusions"] += 1

        # Import fundamentals
        for doc in tinydb.table(docstore.FUNDAMENTALS).all():
            doc_dict = dict(doc)
            symbol = doc_dict.get("symbol")
            if symbol:
                if not dry_run:
                    mongo.put_fundamentals(mongo_db, symbol, doc_dict)
                counts["fundamentals"] += 1

    finally:
        tinydb.close()

    return counts


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be imported, change nothing")
    p.add_argument("--db-path", default=DB_PATH,
                   help="path to TinyDB documents.json")
    args = p.parse_args()

    try:
        mongo_db = mongo.open_db()
    except Exception as e:
        print(f"Error: cannot connect to MongoDB: {e}", file=sys.stderr)
        return 1

    try:
        if args.dry_run:
            print("DRY RUN: showing what would be imported")

        counts = import_data(mongo_db, Path(args.db_path), dry_run=args.dry_run)

        if args.dry_run:
            print(f"Would import: {counts}")
        else:
            print(f"Imported: {counts}")

            # Verify counts
            stats = mongo.stats(mongo_db)
            print(f"MongoDB now contains:")
            print(f"  filings: {stats['filings']}")
            print(f"  filings_with_text: {stats['filings_with_text']}")
            print(f"  extractions: {stats['extractions']}")
            print(f"  conclusions: {stats['conclusions']}")
            print(f"  fundamentals: {stats['fundamentals']}")

        return 0

    finally:
        mongo_db.close()


if __name__ == "__main__":
    sys.exit(main())
