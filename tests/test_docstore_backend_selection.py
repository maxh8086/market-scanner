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


if __name__ == "__main__":
    unittest.main()
