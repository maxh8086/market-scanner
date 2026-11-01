"""Unit tests for SQLite to Postgres import."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

# Only run these tests if Postgres is reachable: available() only checks that it is configured
try:
    from scanner.pg.db import available, connect
    POSTGRES_AVAILABLE = available()
    if POSTGRES_AVAILABLE:
        with connect() as conn:
            conn.execute("SELECT 1")  # Verify connection works
except Exception:
    POSTGRES_AVAILABLE = False

# Same relative path the importer reads; the file is not in every checkout
HISTORY_DB_EXISTS = Path("data/history.db").exists()


@unittest.skipUnless(POSTGRES_AVAILABLE, "Postgres is not reachable")
@unittest.skipUnless(HISTORY_DB_EXISTS, "data/history.db is missing (the importer's input file; not in this checkout)")
class TestImportSQLiteToPostgres(unittest.TestCase):
    """Tests for idempotent SQLite to Postgres import."""

    def test_import_candles_idempotent(self):
        """Importing twice inserts same number of rows."""
        from scanner.pg.import_sqlite import import_candles

        # First import
        result1 = import_candles(dry_run=False)
        # Second import (should be idempotent)
        result2 = import_candles(dry_run=False)

        # After second import, inserted count should be 0
        self.assertEqual(result2["inserted"], 0, "Second import should insert 0 rows")

    def test_import_candles_count_matches_sqlite(self):
        """Postgres holds every SQLite candle (it may hold more: the collector writes to it directly)."""
        import sqlite3

        from scanner.pg.import_sqlite import import_candles

        result = import_candles(dry_run=False)

        # Verify counts match
        history_db = Path("data/history.db")
        if history_db.exists():
            sqlite_conn = sqlite3.connect(history_db)
            sqlite_count = sqlite_conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
            sqlite_conn.close()

            self.assertGreaterEqual(result["postgres_after"], sqlite_count,
                           f"Expected at least {sqlite_count} candles in Postgres, got {result['postgres_after']}")

    def test_import_announcements_idempotent(self):
        """Importing announcements twice is idempotent."""
        from scanner.pg.import_sqlite import import_announcements

        result1 = import_announcements(dry_run=False)
        result2 = import_announcements(dry_run=False)

        self.assertEqual(result2["inserted"], 0, "Second import should insert 0 rows")

    def test_import_announcements_count_matches_sqlite(self):
        """Total Postgres announcements match SQLite exactly."""
        import sqlite3

        from scanner.pg.import_sqlite import import_announcements

        result = import_announcements(dry_run=False)

        factors_db = Path("data/factors.db")
        if factors_db.exists():
            sqlite_conn = sqlite3.connect(factors_db)
            sqlite_count = sqlite_conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
            sqlite_conn.close()

            self.assertEqual(result["postgres_after"], sqlite_count,
                           f"Expected {sqlite_count} announcements in Postgres, got {result['postgres_after']}")

    def test_import_corporate_actions_idempotent(self):
        """Importing corporate actions twice is idempotent."""
        from scanner.pg.import_sqlite import import_corporate_actions

        result1 = import_corporate_actions(dry_run=False)
        result2 = import_corporate_actions(dry_run=False)

        self.assertEqual(result2["inserted"], 0, "Second import should insert 0 rows")

    def test_import_corporate_actions_count_matches_sqlite(self):
        """Total Postgres corporate actions match SQLite exactly."""
        import sqlite3

        from scanner.pg.import_sqlite import import_corporate_actions

        result = import_corporate_actions(dry_run=False)

        factors_db = Path("data/factors.db")
        if factors_db.exists():
            sqlite_conn = sqlite3.connect(factors_db)
            sqlite_count = sqlite_conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
            sqlite_conn.close()

            self.assertEqual(result["postgres_after"], sqlite_count,
                           f"Expected {sqlite_count} corporate actions in Postgres, got {result['postgres_after']}")

    def test_import_symbol_stats_idempotent(self):
        """Importing symbol_stats twice is idempotent (upsert)."""
        from scanner.pg.import_sqlite import import_symbol_stats

        result1 = import_symbol_stats(dry_run=False)
        result2 = import_symbol_stats(dry_run=False)

        # With upsert, second run might still "insert" (overwrite), but row count stays the same
        self.assertEqual(result1["postgres_after"], result2["postgres_after"],
                        "Symbol stats count should be stable across runs")

    def test_dry_run_makes_no_changes(self):
        """Dry-run reports what would happen without changing anything."""
        from scanner.pg.import_sqlite import import_candles

        # Get before state
        with connect() as conn:
            before = conn.execute("SELECT COUNT(*) as cnt FROM candles").fetchone()["cnt"]

        # Dry run
        result = import_candles(dry_run=True)

        # Get after state
        with connect() as conn:
            after = conn.execute("SELECT COUNT(*) as cnt FROM candles").fetchone()["cnt"]

        # Counts should be unchanged
        self.assertEqual(before, after, "Dry-run should not change the database")

    def test_date_normalization(self):
        """Dates are normalized to ISO format during import."""
        import sqlite3

        from scanner.pg.import_sqlite import import_announcements

        # Import once to populate Postgres
        import_announcements(dry_run=False)

        # an_dt is a date column, so every stored value is already normalised
        with connect() as conn:
            rows = conn.execute(
                "SELECT an_dt FROM announcements WHERE an_dt IS NOT NULL LIMIT 10"
            ).fetchall()

        self.assertTrue(rows, "no announcements in Postgres after import")
        for row in rows:
            # a real date column: an un-normalised NSE text date would not have loaded
            self.assertIsInstance(row["an_dt"], date)
            self.assertGreater(row["an_dt"], date(1990, 1, 1))


if __name__ == "__main__":
    unittest.main()
