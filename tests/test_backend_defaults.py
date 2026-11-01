"""Backend defaults: Postgres and Mongo by default, sqlite/tinydb only when
explicitly selected, invalid values fail loudly.

No test here connects to a database or starts a container. Postgres
availability is patched to False to prove there is no auto-detect, and
scanner.mongo.open_db is mocked.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scanner import docstore
from scanner.marketdata import get_backend, get_factors_impl, get_history_impl


class MarketDataBackendDefaultTests(unittest.TestCase):
    def test_unset_defaults_to_postgres_without_probing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MARKETDATA_BACKEND", None)
            with mock.patch("scanner.pg.db.available", return_value=False) as probe:
                self.assertEqual(get_backend(), "postgres")
                probe.assert_not_called()

    def test_empty_defaults_to_postgres(self):
        with mock.patch.dict(os.environ, {"MARKETDATA_BACKEND": ""}, clear=False):
            self.assertEqual(get_backend(), "postgres")

    def test_sqlite_explicit_case_insensitive(self):
        with mock.patch.dict(os.environ, {"MARKETDATA_BACKEND": "SQLITE"}, clear=False):
            self.assertEqual(get_backend(), "sqlite")

    def test_postgres_explicit_case_insensitive(self):
        with mock.patch.dict(os.environ, {"MARKETDATA_BACKEND": "PostgreS"}, clear=False):
            self.assertEqual(get_backend(), "postgres")

    def test_invalid_value_raises_naming_variable(self):
        with mock.patch.dict(os.environ, {"MARKETDATA_BACKEND": "parquet"}, clear=False):
            with self.assertRaises(ValueError) as ctx:
                get_backend()
        self.assertIn("MARKETDATA_BACKEND", str(ctx.exception))
        self.assertIn("postgres", str(ctx.exception))
        self.assertIn("sqlite", str(ctx.exception))

    def test_sqlite_impl_raises_not_implemented(self):
        with mock.patch.dict(os.environ, {"MARKETDATA_BACKEND": "sqlite"}, clear=False):
            with self.assertRaises(NotImplementedError):
                get_history_impl()
            with self.assertRaises(NotImplementedError):
                get_factors_impl()


class DocstoreBackendDefaultTests(unittest.TestCase):
    def test_empty_defaults_to_mongo(self):
        with mock.patch.dict(os.environ, {"DOCSTORE_BACKEND": ""}, clear=False), \
                mock.patch("scanner.mongo.open_db", return_value="mongo-sentinel") as open_mongo:
            self.assertEqual(docstore.open_db(), "mongo-sentinel")
            open_mongo.assert_called_once_with()

    def test_unset_defaults_to_mongo(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DOCSTORE_BACKEND", None)
            with mock.patch("scanner.mongo.open_db", return_value="mongo-sentinel") as open_mongo:
                self.assertEqual(docstore.open_db(), "mongo-sentinel")
                open_mongo.assert_called_once_with()

    def test_mongo_failure_propagates_without_tinydb_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"DOCSTORE_BACKEND": ""}, clear=False), \
                mock.patch("scanner.mongo.open_db", side_effect=RuntimeError("down")):
            target = Path(tmp) / "fallback.json"
            with self.assertRaises(RuntimeError):
                docstore.open_db(target)
            self.assertFalse(target.exists())

    def test_tinydb_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "explicit.json"
            with mock.patch.dict(os.environ, {"DOCSTORE_BACKEND": "tinydb"}, clear=False), \
                    mock.patch("scanner.mongo.open_db") as open_mongo:
                db = docstore.open_db(target)
                try:
                    from tinydb import TinyDB
                    self.assertIsInstance(db, TinyDB)
                finally:
                    db.close()
                open_mongo.assert_not_called()
                self.assertTrue(target.exists())

    def test_invalid_value_raises_naming_variable(self):
        with mock.patch.dict(os.environ, {"DOCSTORE_BACKEND": "couchdb"}, clear=False), \
                mock.patch("scanner.mongo.open_db") as open_mongo:
            with self.assertRaises(ValueError) as ctx:
                docstore.open_db()
            open_mongo.assert_not_called()
        self.assertIn("DOCSTORE_BACKEND", str(ctx.exception))
        self.assertIn("mongo", str(ctx.exception))
        self.assertIn("tinydb", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
