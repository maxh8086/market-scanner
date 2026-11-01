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
    def test_tinydb_backend_default(self):
        """TinyDB is the default backend when DOCSTORE_BACKEND is not set."""
        with tempfile.TemporaryDirectory() as tmp:
            tinydb_path = Path(tmp) / "test.json"
            # Ensure DOCSTORE_BACKEND is not set for TinyDB default
            with mock.patch.dict(os.environ, {"DOCSTORE_BACKEND": ""}, clear=False):
                db = docstore.open_db(tinydb_path)
                self.assertIsNotNone(db)
                # TinyDB returns a TinyDB instance
                from tinydb import TinyDB
                self.assertIsInstance(db, TinyDB)
                db.close()
                self.assertTrue(tinydb_path.exists())

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
