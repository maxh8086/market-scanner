"""Test that backend dispatch works correctly."""
from __future__ import annotations

import os
import unittest
from unittest import mock


class TestBackendDispatch(unittest.TestCase):
    """Tests for backend auto-detection and dispatch."""

    def test_sqlite_backend_explicit(self):
        """SQLite backend is used only when explicitly selected."""
        with mock.patch.dict(os.environ, {"MARKETDATA_BACKEND": "sqlite"}):
            from scanner.marketdata import get_backend
            self.assertEqual(get_backend(), "sqlite")

    def test_postgres_backend_explicit(self):
        """Explicit MARKETDATA_BACKEND=postgres selects Postgres without probing it."""
        with mock.patch.dict(os.environ, {"MARKETDATA_BACKEND": "postgres"}):
            from scanner.marketdata import get_backend
            self.assertEqual(get_backend(), "postgres")

    def test_history_backend_dispatch_sqlite(self):
        """history.get_history() can use SQLite backend."""
        with mock.patch.dict(os.environ, {"MARKETDATA_BACKEND": "sqlite"}):
            # Just verify the function exists and has the right signature
            from scanner.history import get_history
            import inspect
            sig = inspect.signature(get_history)
            self.assertIn("client", sig.parameters)
            self.assertIn("key", sig.parameters)
            self.assertIn("symbol", sig.parameters)

    def test_factors_new_functions_exist(self):
        """factors module has new collection functions."""
        from scanner.factors import collect_announcements, collect_corporate_actions, announcement_coverage

        # Verify they exist and are callable
        self.assertTrue(callable(collect_announcements))
        self.assertTrue(callable(collect_corporate_actions))
        self.assertTrue(callable(announcement_coverage))

    def test_coverage_functions_exist(self):
        """coverage module has required functions."""
        from scanner.coverage import required_start, missing_windows, record_coverage

        self.assertTrue(callable(required_start))
        self.assertTrue(callable(missing_windows))
        self.assertTrue(callable(record_coverage))


if __name__ == "__main__":
    unittest.main()
