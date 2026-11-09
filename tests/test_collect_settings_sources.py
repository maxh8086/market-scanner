"""Offline tests for settings.ensure_sources: every SOURCES key gets a settings row, no migration needed."""
import unittest
from unittest.mock import MagicMock, patch

from scanner.collect import settings
from scanner.collect.sources import SOURCES


class _FakeConn:
    def __init__(self, existing):
        self.existing = existing
        self.inserted = []
        self.registered = []
        self.committed = False

    def execute(self, sql, params=()):
        result = MagicMock()
        if sql.startswith("SELECT source FROM collector_settings"):
            result.fetchall.return_value = [{"source": s} for s in self.existing]
        elif sql.startswith("INSERT INTO collector_settings"):
            self.inserted.append(params[0])
        elif sql.startswith("INSERT INTO collector_sources"):
            self.registered.append(params[0])
        return result

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class EnsureSourcesTests(unittest.TestCase):

    def _run(self, existing):
        conn = _FakeConn(existing)
        with patch.object(settings.db, "connect", return_value=conn):
            added = settings.ensure_sources()
        return conn, added

    def test_adds_only_missing_sources(self):
        conn, added = self._run(existing=["candles_eod"])
        self.assertNotIn("candles_eod", added)
        self.assertEqual(sorted(added), sorted(set(SOURCES) - {"candles_eod"}))
        self.assertTrue(conn.committed)

    def test_registers_ath_scan_when_absent(self):
        _, added = self._run(existing=[])
        self.assertIn("ath_scan", added)

    def test_no_insert_when_all_present(self):
        conn, added = self._run(existing=list(SOURCES))
        self.assertEqual(added, [])
        self.assertEqual(conn.inserted, [])
        self.assertEqual(conn.registered, [])

    def test_each_new_source_is_registered_before_its_settings_row(self):
        conn, added = self._run(existing=["candles_eod"])
        self.assertEqual(sorted(conn.registered), sorted(added))
        self.assertEqual(sorted(conn.inserted), sorted(added))


if __name__ == "__main__":
    unittest.main()
