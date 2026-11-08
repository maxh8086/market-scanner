"""Symbol-scoped cached announcement loading in scanner/marketdata/factors_postgres.py, offline.

Nothing reaches NSE or Postgres: the database connection and the coverage
lookups are replaced with mocks.
"""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from scanner.marketdata import factors_postgres as fp


def _fake_connect(fetchone_value=None):
    """Return (patched connect, conn mock). Every execute records its (sql, params)."""
    cursor = mock.MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = fetchone_value
    conn = mock.MagicMock()
    conn.execute.return_value = cursor
    cm = mock.MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    return mock.MagicMock(return_value=cm), conn


class SymbolScopedAnnouncementsTest(unittest.TestCase):
    def test_symbol_query_filters_by_symbol(self):
        fake_connect, conn = _fake_connect()
        with mock.patch.object(fp, "connect", fake_connect):
            fp._load_cached_announcements_pg(date(2026, 1, 1), date(2026, 1, 31), "RELIANCE")

        sql, params = conn.execute.call_args[0]
        self.assertIn("symbol = %s", sql)
        self.assertEqual(params, (date(2026, 1, 1), date(2026, 1, 31), "RELIANCE"))

    def test_no_symbol_query_is_unscoped(self):
        fake_connect, conn = _fake_connect()
        with mock.patch.object(fp, "connect", fake_connect):
            fp._load_cached_announcements_pg(date(2026, 1, 1), date(2026, 1, 31))

        sql, params = conn.execute.call_args[0]
        self.assertNotIn("symbol = %s", sql)
        self.assertEqual(params, (date(2026, 1, 1), date(2026, 1, 31)))

    def test_fetch_with_full_coverage_uses_symbol_scope(self):
        fake_connect, _conn = _fake_connect()
        cached = mock.MagicMock(return_value=[{"symbol": "X"}])
        with mock.patch.object(fp, "connect", fake_connect), \
                mock.patch.object(fp, "missing_windows", return_value=[]), \
                mock.patch.object(fp, "_load_cached_announcements_pg", cached):
            result = fp.fetch_announcements_pg(
                date(2026, 1, 1), date(2026, 1, 31), session=mock.MagicMock(), symbol="X"
            )

        cached.assert_called_once_with(date(2026, 1, 1), date(2026, 1, 31), "X")
        self.assertEqual(result, [{"symbol": "X"}])

    def test_collect_passes_symbol_through(self):
        fake_connect, _conn = _fake_connect(fetchone_value={"cnt": 0})
        fetch = mock.MagicMock(return_value=[])
        with mock.patch.object(fp, "connect", fake_connect), \
                mock.patch.object(fp, "fetch_announcements_pg", fetch):
            fp.collect_announcements("X", listing_date=date(2020, 1, 1), session=mock.MagicMock())

        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs.get("symbol"), "X")


if __name__ == "__main__":
    unittest.main()
