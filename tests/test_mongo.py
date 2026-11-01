"""Tests for scanner.mongo (MongoDB backend).

Skips gracefully if MongoDB is unreachable. Tests a throwaway database.
"""

import os
import unittest
from datetime import date

from dotenv import find_dotenv, load_dotenv
from pymongo import MongoClient

from scanner import docstore, mongo

load_dotenv(find_dotenv(usecwd=True))


def _build_mongo_uri():
    """Authenticated URI from SCANNER_MONGO_* in .env, or None when credentials are missing.

    Built by scanner/mongo.py (_uri_from_env); the auth source defaults to the project's
    database (SCANNER_MONGO_DB, default 'market_scanner').
    """
    db_name = os.environ.get("SCANNER_MONGO_DB", "market_scanner")
    try:
        return mongo._uri_from_env(db_name)
    except RuntimeError:
        return None


MONGO_URI = _build_mongo_uri()


def _mongo_available() -> bool:
    """True when MongoDB accepts writes to a throwaway database.

    A login may only write to its own database, so a login
    without rights to create test_* databases makes this return False and the tests skip.
    Missing credentials or an unreachable server also return False.
    """
    if MONGO_URI is None:
        return False
    client = None
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        probe = client["test_market_scanner_probe"]
        probe.t.insert_one({"x": 1})
        client.drop_database("test_market_scanner_probe")
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            client.close()


SKIP_MONGO = not _mongo_available()


@unittest.skipIf(SKIP_MONGO, "MongoDB not reachable")
class MongoDBBackendTests(unittest.TestCase):
    """Tests using MongoDB backend (skips if unreachable)."""

    @classmethod
    def setUpClass(cls):
        if SKIP_MONGO:
            raise unittest.SkipTest("MongoDB not reachable")
        cls.db = mongo.open_db(uri=MONGO_URI, db_name="test_market_scanner_mongo")

    @classmethod
    def tearDownClass(cls):
        # Drop the test database
        if hasattr(cls, 'db') and cls.db:
            cls.db.client.drop_database("test_market_scanner_mongo")
            cls.db.close()

    def setUp(self):
        """Clear collections before each test."""
        if not SKIP_MONGO:
            self.db.table("filings").delete_many({})
            self.db.table("extractions").delete_many({})
            self.db.table("conclusions").delete_many({})
            self.db.table("fundamentals").delete_many({})

    def test_filing_roundtrip(self):
        mongo.put_filing(self.db, {"seq_id": "9911", "symbol": "RAILTEL",
                                   "raw_text": "Order value Rs. 21 crore"})
        doc = mongo.get_filing(self.db, "9911")
        self.assertIsNotNone(doc)
        self.assertEqual(doc["symbol"], "RAILTEL")
        self.assertIn("21 crore", doc["raw_text"])
        self.assertIn("stored_at", doc)

    def test_filing_upsert_idempotent(self):
        for _ in range(3):
            mongo.put_filing(self.db, {"seq_id": "42", "symbol": "ABC"})
        self.assertEqual(len(mongo.all_filings(self.db)), 1)

    def test_filing_upsert_replaces_content(self):
        mongo.put_filing(self.db, {"seq_id": "42", "raw_text": ""})
        mongo.put_filing(self.db, {"seq_id": "42", "raw_text": "now fetched"})
        self.assertEqual(mongo.get_filing(self.db, "42")["raw_text"], "now fetched")

    def test_filing_integer_seq_id_matches_string(self):
        mongo.put_filing(self.db, {"seq_id": 7, "symbol": "ABC"})
        mongo.put_filing(self.db, {"seq_id": "7", "symbol": "ABC"})
        self.assertEqual(len(mongo.all_filings(self.db)), 1)
        self.assertIsNotNone(mongo.get_filing(self.db, 7))

    def test_filing_missing_seq_id_rejected(self):
        with self.assertRaises(ValueError):
            mongo.put_filing(self.db, {"symbol": "ABC"})
        with self.assertRaises(ValueError):
            mongo.put_filing(self.db, {"seq_id": "", "symbol": "ABC"})

    def test_has_filing_text(self):
        self.assertFalse(mongo.has_filing_text(self.db, "nope"))
        mongo.put_filing(self.db, {"seq_id": "1", "error": "timeout", "raw_text": ""})
        self.assertFalse(mongo.has_filing_text(self.db, "1"))
        mongo.put_filing(self.db, {"seq_id": "1", "raw_text": "text"})
        self.assertTrue(mongo.has_filing_text(self.db, "1"))

    def test_filings_for_and_by_kind(self):
        mongo.put_filing(self.db, {"seq_id": "1", "symbol": "A", "kind": "orderbook"})
        mongo.put_filing(self.db, {"seq_id": "2", "symbol": "A", "kind": "expansion"})
        mongo.put_filing(self.db, {"seq_id": "3", "symbol": "B", "kind": "orderbook"})
        self.assertEqual(len(mongo.filings_for(self.db, "A")), 2)
        self.assertEqual(len(mongo.filings_by_kind(self.db, "orderbook")), 2)
        self.assertEqual(mongo.filings_for(self.db, "ZZ"), [])

    def test_fundamentals_roundtrip(self):
        mongo.put_fundamentals(self.db, "ABC", {"mcap_cr": 1000})
        mongo.put_fundamentals(self.db, "ABC", {"mcap_cr": 1100})
        self.assertEqual(len(mongo.all_fundamentals(self.db)), 1)
        self.assertEqual(mongo.get_fundamentals(self.db, "ABC")["mcap_cr"], 1100)

    def test_fundamentals_age(self):
        mongo.put_fundamentals(self.db, "ABC", {"mcap_cr": 1000})
        age = mongo.fundamentals_age_days(self.db, "ABC")
        self.assertIsNotNone(age)
        self.assertLess(age, 0.01)

    def test_fundamentals_age_none_for_unknown(self):
        self.assertIsNone(mongo.fundamentals_age_days(self.db, "NOPE"))

    def test_extractions_keyed_on_seq_id_and_kind(self):
        mongo.put_extraction(self.db, "1", "capacity", {"existing": "1 MTPA"})
        mongo.put_extraction(self.db, "1", "orderval", {"rupees": 1e9})
        self.assertEqual(self.db.table("extractions").count_documents({}), 2)
        self.assertEqual(
            mongo.get_extraction(self.db, "1", "capacity")["existing"], "1 MTPA")

    def test_extractions_rerun_overwrites_kind_only(self):
        mongo.put_extraction(self.db, "1", "capacity", {"existing": "1 MTPA"})
        mongo.put_extraction(self.db, "1", "capacity", {"existing": "1.2 MTPA"})
        mongo.put_extraction(self.db, "1", "orderval", {"rupees": 1e9})
        self.assertEqual(len(mongo.extractions_by_kind(self.db, "capacity")), 1)
        self.assertEqual(
            mongo.get_extraction(self.db, "1", "capacity")["existing"], "1.2 MTPA")
        self.assertIsNotNone(mongo.get_extraction(self.db, "1", "orderval"))

    def test_conclusions_roundtrip(self):
        mongo.put_conclusion(self.db, "A", "2026-09-29", {"stance": "MIXED", "conclusion": "ok"})
        doc = mongo.get_conclusion(self.db, "A", "2026-09-29")
        self.assertIsNotNone(doc)
        self.assertEqual(doc["stance"], "MIXED")

    def test_conclusions_for_as_of(self):
        mongo.put_conclusion(self.db, "A", "2026-09-29", {"stance": "MIXED"})
        mongo.put_conclusion(self.db, "B", "2026-09-29", {"stance": "CONSTRUCTIVE"})
        mongo.put_conclusion(self.db, "A", "2026-09-30", {"stance": "CAUTIOUS"})
        self.assertEqual(len(mongo.conclusions_for(self.db, "2026-09-29")), 2)
        self.assertEqual(len(mongo.conclusions_for(self.db, "2026-09-30")), 1)

    def test_stats(self):
        mongo.put_filing(self.db, {"seq_id": "1", "raw_text": "text"})
        mongo.put_filing(self.db, {"seq_id": "2", "raw_text": ""})
        mongo.put_fundamentals(self.db, "A", {"mcap_cr": 100})
        s = mongo.stats(self.db)
        self.assertEqual(s["filings"], 2)
        self.assertEqual(s["filings_with_text"], 1)
        self.assertEqual(s["fundamentals"], 1)


class MongoImportTests(unittest.TestCase):
    """Tests for the mongo_import module."""

    @unittest.skipIf(SKIP_MONGO, "MongoDB not reachable")
    def test_import_is_idempotent(self):
        """Running import twice should add 0 rows on the second run."""
        from scanner import mongo_import
        import tempfile
        from pathlib import Path

        db = mongo.open_db(uri=MONGO_URI, db_name="test_import_idempotent")
        try:
            # Create a small test TinyDB
            with tempfile.TemporaryDirectory() as tmp:
                tinydb_path = Path(tmp) / "test.json"
                tinydb = docstore.open_db(tinydb_path)

                # Add some test data
                docstore.put_filing(tinydb, {"seq_id": "1", "symbol": "A"})
                docstore.put_fundamentals(tinydb, "B", {"mcap_cr": 100})

                tinydb.close()

                # First import
                counts1 = mongo_import.import_data(db, tinydb_path, dry_run=False)
                self.assertEqual(counts1["filings"], 1)
                self.assertEqual(counts1["fundamentals"], 1)

                # Second import (should be idempotent)
                counts2 = mongo_import.import_data(db, tinydb_path, dry_run=False)
                # Upserts don't add new documents if keys match
                # So counts should be 0 (no changes) or reflect updates
                stats = mongo.stats(db)
                self.assertEqual(stats["filings"], 1)
                self.assertEqual(stats["fundamentals"], 1)
        finally:
            db.client.drop_database("test_import_idempotent")
            db.close()


if __name__ == "__main__":
    unittest.main()
