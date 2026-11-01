"""Tests for scanner.docstore.

Every test uses a throwaway file in a temp directory -- nothing here touches
data/documents.json.
"""

import json
import tempfile
import unittest
from pathlib import Path

from scanner import docstore as ds


class _TempDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "docs.json"
        self.db = ds.open_db(self.path)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()


class TestOpen(_TempDB):
    def test_creates_the_file_and_records_the_schema(self):
        self.assertTrue(self.path.exists())
        self.assertEqual(ds.schema_version(self.db), ds.SCHEMA_VERSION)

    def test_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "a" / "b" / "docs.json"
            db = ds.open_db(nested)
            db.close()
            self.assertTrue(nested.exists())

    def test_reopening_does_not_duplicate_the_meta_row(self):
        self.db.close()
        db = ds.open_db(self.path)
        try:
            self.assertEqual(len(db.table(ds._META).all()), 1)
        finally:
            db.close()

    def test_stored_json_is_compact(self):
        ds.put_filing(self.db, {"seq_id": "1", "raw_text": "x" * 500})
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("\n    ", text, "indent would bloat PDF text on disk")


class TestFilings(_TempDB):
    def test_roundtrip(self):
        ds.put_filing(self.db, {"seq_id": "9911", "symbol": "RAILTEL",
                                "raw_text": "Order value Rs. 21 crore"})
        doc = ds.get_filing(self.db, "9911")
        self.assertEqual(doc["symbol"], "RAILTEL")
        self.assertIn("21 crore", doc["raw_text"])
        self.assertIn("stored_at", doc)

    def test_upsert_is_idempotent_across_reruns(self):
        for _ in range(3):
            ds.put_filing(self.db, {"seq_id": "42", "symbol": "ABC"})
        self.assertEqual(len(ds.all_filings(self.db)), 1)

    def test_upsert_replaces_content_for_the_same_seq_id(self):
        ds.put_filing(self.db, {"seq_id": "42", "raw_text": ""})
        ds.put_filing(self.db, {"seq_id": "42", "raw_text": "now fetched"})
        self.assertEqual(ds.get_filing(self.db, "42")["raw_text"], "now fetched")

    def test_integer_seq_id_matches_the_string_form(self):
        """NSE sometimes hands back an int; the key must not fork."""
        ds.put_filing(self.db, {"seq_id": 7, "symbol": "ABC"})
        ds.put_filing(self.db, {"seq_id": "7", "symbol": "ABC"})
        self.assertEqual(len(ds.all_filings(self.db)), 1)
        self.assertIsNotNone(ds.get_filing(self.db, 7))

    def test_missing_seq_id_is_rejected(self):
        with self.assertRaises(ValueError):
            ds.put_filing(self.db, {"symbol": "ABC"})
        with self.assertRaises(ValueError):
            ds.put_filing(self.db, {"seq_id": "", "symbol": "ABC"})

    def test_has_filing_text_gates_the_download(self):
        self.assertFalse(ds.has_filing_text(self.db, "nope"))
        ds.put_filing(self.db, {"seq_id": "1", "error": "timeout", "raw_text": ""})
        self.assertFalse(ds.has_filing_text(self.db, "1"),
                         "a failed fetch must be retried on the next run")
        ds.put_filing(self.db, {"seq_id": "1", "raw_text": "text"})
        self.assertTrue(ds.has_filing_text(self.db, "1"))

    def test_queries_by_symbol_and_kind(self):
        ds.put_filing(self.db, {"seq_id": "1", "symbol": "A", "kind": "orderbook"})
        ds.put_filing(self.db, {"seq_id": "2", "symbol": "A", "kind": "expansion"})
        ds.put_filing(self.db, {"seq_id": "3", "symbol": "B", "kind": "orderbook"})
        self.assertEqual(len(ds.filings_for(self.db, "A")), 2)
        self.assertEqual(len(ds.filings_by_kind(self.db, "orderbook")), 2)
        self.assertEqual(ds.filings_for(self.db, "ZZ"), [])

    def test_unicode_survives_the_roundtrip(self):
        ds.put_filing(self.db, {"seq_id": "1", "raw_text": "₹ 340 crore"})
        self.assertIn("₹", ds.get_filing(self.db, "1")["raw_text"])


class TestFundamentals(_TempDB):
    def test_roundtrip_and_upsert(self):
        ds.put_fundamentals(self.db, "ABC", {"mcap_cr": 1000})
        ds.put_fundamentals(self.db, "ABC", {"mcap_cr": 1100})
        self.assertEqual(len(ds.all_fundamentals(self.db)), 1)
        self.assertEqual(ds.get_fundamentals(self.db, "ABC")["mcap_cr"], 1100)

    def test_age_is_near_zero_right_after_writing(self):
        ds.put_fundamentals(self.db, "ABC", {"mcap_cr": 1000})
        age = ds.fundamentals_age_days(self.db, "ABC")
        self.assertIsNotNone(age)
        self.assertLess(age, 0.01)

    def test_age_none_for_an_unknown_symbol(self):
        self.assertIsNone(ds.fundamentals_age_days(self.db, "NOPE"))

    def test_age_none_when_the_timestamp_is_unparseable(self):
        self.db.table(ds.FUNDAMENTALS).insert({"symbol": "X", "stored_at": "junk"})
        self.assertIsNone(ds.fundamentals_age_days(self.db, "X"))


class TestExtractions(_TempDB):
    def test_keyed_on_seq_id_and_kind_together(self):
        ds.put_extraction(self.db, "1", "capacity", {"existing": "1 MTPA"})
        ds.put_extraction(self.db, "1", "orderval", {"rupees": 1e9})
        self.assertEqual(len(self.db.table(ds.EXTRACTIONS).all()), 2)
        self.assertEqual(
            ds.get_extraction(self.db, "1", "capacity")["existing"], "1 MTPA")

    def test_rerunning_a_prompt_overwrites_that_kind_only(self):
        ds.put_extraction(self.db, "1", "capacity", {"existing": "1 MTPA"})
        ds.put_extraction(self.db, "1", "capacity", {"existing": "1.2 MTPA"})
        ds.put_extraction(self.db, "1", "orderval", {"rupees": 1e9})
        self.assertEqual(len(ds.extractions_by_kind(self.db, "capacity")), 1)
        self.assertEqual(
            ds.get_extraction(self.db, "1", "capacity")["existing"], "1.2 MTPA")
        self.assertIsNotNone(ds.get_extraction(self.db, "1", "orderval"))

    def test_missing_extraction_is_none(self):
        self.assertIsNone(ds.get_extraction(self.db, "1", "capacity"))


class TestStats(_TempDB):
    def test_counts_and_size(self):
        ds.put_filing(self.db, {"seq_id": "1", "raw_text": "text"})
        ds.put_filing(self.db, {"seq_id": "2", "raw_text": ""})
        ds.put_fundamentals(self.db, "ABC", {"mcap_cr": 1})
        ds.put_extraction(self.db, "1", "capacity", {})
        s = ds.stats(self.db, self.path)
        self.assertEqual(s["filings"], 2)
        self.assertEqual(s["filings_with_text"], 1)
        self.assertEqual(s["fundamentals"], 1)
        self.assertEqual(s["extractions"], 1)
        self.assertGreater(s["bytes_on_disk"], 0)
        self.assertEqual(s["schema_version"], ds.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
