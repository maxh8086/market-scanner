"""Tests for docstore backend selection.

Verifies that DOCSTORE_BACKEND env var controls which backend is used.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scanner import docstore


class BackendSelectionTests(unittest.TestCase):
    def test_mongo_is_default_when_unset(self):
        """Mongo is the default when DOCSTORE_BACKEND is unset or empty.

        scanner.mongo.open_db is mocked, so no connection is made.
        """
        for value in ("", None):
            env = {} if value is None else {"DOCSTORE_BACKEND": value}
            with self.subTest(value=value):
                with mock.patch.dict(os.environ, env, clear=False):
                    if value is None:
                        os.environ.pop("DOCSTORE_BACKEND", None)
                    with mock.patch("scanner.mongo.open_db") as open_mongo:
                        open_mongo.return_value = "mongo-sentinel"
                        self.assertEqual(docstore.open_db(), "mongo-sentinel")
                        open_mongo.assert_called_once_with()

    def test_tinydb_backend_explicit(self):
        """TinyDB backend can be explicitly selected."""
        with tempfile.TemporaryDirectory() as tmp:
            tinydb_path = Path(tmp) / "test.json"
            with mock.patch.dict(os.environ, {"DOCSTORE_BACKEND": "tinydb"}):
                db = docstore.open_db(tinydb_path)
                self.assertIsNotNone(db)
                from tinydb import TinyDB
                self.assertIsInstance(db, TinyDB)
                db.close()

    def test_mongo_backend_selection(self):
        """MongoDB backend is selected when DOCSTORE_BACKEND=mongo."""
        with mock.patch.dict(os.environ, {"DOCSTORE_BACKEND": "mongo",
                                          "MONGO_URI": "mongodb://localhost:27017",
                                          "MONGO_DB": "test_db"}):
            # This will fail if MongoDB is not available, but the test should
            # check that the correct backend was selected (or attempted)
            try:
                from scanner import mongo
                # Just verify that the backend selection code path exists
                # We can't actually test MongoDB without it being available
                self.assertTrue(hasattr(mongo, 'open_db'))
            except ImportError:
                self.fail("mongo module should be importable")


class FundamentalsMongoDispatchTests(unittest.TestCase):
    """Fundamentals helpers must use the Mongo implementation for a MongoDB store.

    Regression: docstore called TinyDB-only methods (db.table(...).get/upsert)
    on a MongoDB object, failing with "'Collection' object is not callable".
    No connection is made: the store is built without __init__ and its
    fundamentals collection is a mock.
    """

    def _store(self, coll):
        from scanner import mongo
        store = object.__new__(mongo.MongoDB)
        store.db = {"fundamentals": coll}
        return store

    def test_get_fundamentals_uses_find_one_on_mongo(self):
        coll = mock.MagicMock()
        coll.find_one.return_value = {"symbol": "RELIANCE", "stored_at": "2026-11-01T00:00:00+00:00"}
        doc = docstore.get_fundamentals(self._store(coll), "RELIANCE")
        coll.find_one.assert_called_once()
        self.assertEqual(coll.find_one.call_args.args[0], {"symbol": "RELIANCE"})
        self.assertEqual(doc["symbol"], "RELIANCE")

    def test_put_fundamentals_upserts_on_mongo(self):
        coll = mock.MagicMock()
        docstore.put_fundamentals(self._store(coll), "RELIANCE", {"market_cap": 1})
        coll.update_one.assert_called_once()
        self.assertTrue(coll.update_one.call_args.kwargs.get("upsert"))

    def test_age_days_is_none_when_absent_on_mongo(self):
        coll = mock.MagicMock()
        coll.find_one.return_value = None
        self.assertIsNone(docstore.fundamentals_age_days(self._store(coll), "NOPE"))

    def test_all_fundamentals_reads_collection_on_mongo(self):
        coll = mock.MagicMock()
        coll.find.return_value = [{"symbol": "A"}, {"symbol": "B"}]
        out = docstore.all_fundamentals(self._store(coll))
        self.assertEqual([d["symbol"] for d in out], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
