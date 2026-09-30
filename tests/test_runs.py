"""Test run history and snapshots against real Postgres schema."""
import unittest
from datetime import date

import pandas as pd


class RunsIntegrationTests(unittest.TestCase):
    """Integration tests for runs module - require Postgres and migrations applied."""

    def setUp(self):
        """Each test gets its own throwaway schema with the real migrations applied."""
        from tests import pgschema
        self.schema = pgschema.create(self)

    def test_postgres_available(self):
        """Verify Postgres is reachable."""
        from scanner.pg import db
        self.assertTrue(db.available())

    def test_migrations_applied(self):
        """Verify migrations are applied."""
        from scanner.pg import db
        with db.connect() as conn:
            result = conn.execute(
                "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_name='runs'"
            ).fetchone()
            self.assertGreater(result['count'], 0, "runs table not found - migrations not applied")

    def test_start_run(self):
        """Test creating a run."""
        from scanner import runs

        run_id = runs.start_run(date(2026, 10, 1), trigger="manual")
        self.assertIsNotNone(run_id)
        self.assertEqual(len(run_id), 36)  # UUID4 string length

    def test_record_snapshots(self):
        """Test recording snapshots."""
        from scanner import runs

        run_id = runs.start_run(date(2026, 10, 1))

        enriched = pd.DataFrame({
            'symbol': ['TEST1', 'TEST2'],
            'company': ['Test Corp 1', 'Test Corp 2'],
            'industry': ['Tech', 'Finance'],
            'ltp': [100.0, 200.0],
            'ath_high': [110.0, 210.0],
            'ath_date': ['2026-09-20', '2026-09-15'],
            'distance_pct': [9.09, 4.76],
            'bucket': ['within_5', 'within_5'],
            'isin': ['INE001A01010', 'INE002B01020'],
            'yoy_growth_pct': [10.0, 5.0],
            'order_pct_of_sales': [50.0, 30.0],
        })

        count = runs.record_snapshots(run_id, enriched)
        self.assertEqual(count, 2)

    def test_same_run_written_twice(self):
        """Test that writing the same run twice updates, not duplicates."""
        from scanner import runs
        from scanner.pg import db

        run_id = runs.start_run(date(2026, 10, 1))

        enriched = pd.DataFrame({
            'symbol': ['ABC'],
            'company': ['ABC Corp'],
            'industry': ['Tech'],
            'ltp': [100.0],
            'ath_high': [110.0],
            'ath_date': ['2026-09-20'],
            'distance_pct': [9.09],
            'bucket': ['within_5'],
            'isin': ['INE001A01010'],
        })

        runs.record_snapshots(run_id, enriched)

        # Write again with different data
        enriched.loc[0, 'ltp'] = 105.0
        runs.record_snapshots(run_id, enriched)

        # Check only one row exists
        with db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as n FROM stock_snapshots WHERE run_id = %s",
                (run_id,)
            ).fetchone()['n']
            self.assertEqual(count, 1)

    def test_finish_run_complete_marks_current(self):
        """Test that finishing with status='complete' marks is_current=true."""
        from scanner import runs
        from scanner.pg import db

        run_id = runs.start_run(date(2026, 10, 1))
        enriched = pd.DataFrame({
            'symbol': ['ABC'],
            'company': ['ABC Corp'],
            'industry': ['Tech'],
            'ltp': [100.0],
            'ath_high': [110.0],
            'ath_date': ['2026-09-20'],
            'distance_pct': [9.09],
            'bucket': ['within_5'],
            'isin': ['INE001A01010'],
        })
        runs.record_snapshots(run_id, enriched)
        runs.finish_run(run_id, 'complete')

        with db.connect() as conn:
            row = conn.execute(
                "SELECT is_current, status FROM runs WHERE run_id = %s",
                (run_id,)
            ).fetchone()
            self.assertTrue(row['is_current'])
            self.assertEqual(row['status'], 'complete')

    def test_same_date_replace_only_on_complete(self):
        """Test that re-run replaces previous run only when marked complete."""
        from scanner import runs
        from scanner.pg import db

        # First run
        run_id_1 = runs.start_run(date(2026, 10, 2))
        enriched = pd.DataFrame({'symbol': ['ABC'], 'company': ['ABC'], 'industry': ['Tech'],
                                 'ltp': [100.0], 'ath_high': [110.0], 'ath_date': ['2026-09-20'],
                                 'distance_pct': [9.09], 'bucket': ['within_5'], 'isin': ['INE001']})
        runs.record_snapshots(run_id_1, enriched)
        runs.finish_run(run_id_1, 'complete')

        # Verify first run is current
        with db.connect() as conn:
            current = conn.execute(
                "SELECT run_id FROM runs WHERE run_date = %s AND is_current",
                (date(2026, 10, 2),)
            ).fetchone()
            self.assertEqual(str(current['run_id']), str(run_id_1))

        # Second run for same date
        run_id_2 = runs.start_run(date(2026, 10, 2))
        runs.record_snapshots(run_id_2, enriched)
        runs.finish_run(run_id_2, 'complete')

        # Verify only second run is current
        with db.connect() as conn:
            current_rows = list(conn.execute(
                "SELECT run_id FROM runs WHERE run_date = %s AND is_current",
                (date(2026, 10, 2),)
            ))
            self.assertEqual(len(current_rows), 1)
            self.assertEqual(str(current_rows[0]['run_id']), str(run_id_2))

    def test_crash_leaves_no_current(self):
        """Test that a failed run doesn't become current."""
        from scanner import runs
        from scanner.pg import db

        run_id = runs.start_run(date(2026, 10, 3))
        runs.finish_run(run_id, 'failed')

        with db.connect() as conn:
            current = list(conn.execute(
                "SELECT run_id FROM runs WHERE run_date = %s AND is_current",
                (date(2026, 10, 3),)
            ))
            self.assertEqual(len(current), 0)

    def test_entered_range(self):
        """Test detecting stocks entering the range."""
        from scanner import runs
        from scanner.pg import db

        # First run: empty
        run_id_1 = runs.start_run(date(2026, 10, 4))
        enriched_1 = pd.DataFrame({'symbol': [], 'company': [], 'industry': [],
                                   'ltp': [], 'ath_high': [], 'ath_date': [],
                                   'distance_pct': [], 'bucket': [], 'isin': []})
        runs.record_snapshots(run_id_1, enriched_1)
        runs.finish_run(run_id_1, 'complete')

        # Second run: stock enters
        run_id_2 = runs.start_run(date(2026, 10, 5))
        enriched_2 = pd.DataFrame({'symbol': ['ABC'], 'company': ['ABC Corp'],
                                   'industry': ['Tech'], 'ltp': [100.0], 'ath_high': [110.0],
                                   'ath_date': ['2026-09-20'], 'distance_pct': [9.09],
                                   'bucket': ['within_5'], 'isin': ['INE001']})
        runs.record_snapshots(run_id_2, enriched_2)
        count = runs.compute_changes(run_id_2)

        # Should have detected entered_range
        self.assertGreater(count, 0)

        with db.connect() as conn:
            changes = list(conn.execute(
                "SELECT kind FROM snapshot_changes WHERE run_id = %s AND kind = 'entered_range'",
                (run_id_2,)
            ))
            self.assertEqual(len(changes), 1)


    def test_left_range_is_reported_once(self):
        """A stock that left the range is not flagged as leaving again on the next run."""
        from scanner import runs
        from scanner.pg import db

        abc = pd.DataFrame({'symbol': ['ABC'], 'company': ['ABC Corp'], 'industry': ['Tech'],
                            'ltp': [100.0], 'ath_high': [110.0], 'ath_date': ['2026-09-20'],
                            'distance_pct': [9.09], 'bucket': ['5-15%'], 'isin': ['INE001']})
        empty = abc.iloc[0:0]
        for day, frame in ((6, abc), (7, empty), (8, empty)):
            rid = runs.start_run(date(2026, 10, day))
            runs.record_snapshots(rid, frame)
            runs.compute_changes(rid)
            runs.finish_run(rid, 'complete')
            last = rid
        with db.connect() as conn:
            rows = list(conn.execute(
                "SELECT COUNT(*) AS n FROM snapshot_changes WHERE run_id = %s AND kind = 'left_range'",
                (last,)))
        self.assertEqual(rows[0]['n'], 0)

    def test_begin_run_is_idempotent_and_not_current(self):
        from scanner import runs
        from scanner.pg import db
        rid = "5b0f0d57-58d0-4a51-8d0c-0f2b1a3c4d5e"
        runs.begin_run(rid, date(2026, 10, 1))
        runs.begin_run(rid, date(2026, 10, 1))
        with db.connect() as conn:
            rows = list(conn.execute("SELECT status, is_current FROM runs WHERE run_id = %s", (rid,)))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["status"], rows[0]["is_current"]), ("running", False))

    def test_llm_calls_tagged_with_begun_run_and_deduplicated(self):
        import os
        from unittest.mock import patch
        from scanner import metrics, runs
        rid = "7c1e1e68-69e1-4b62-9e1d-1a3c2b4d5e6f"
        runs.begin_run(rid, date(2026, 10, 1))
        metrics._connection, metrics._connection_failed = None, False
        with patch.dict(os.environ, {"RUN_ID": rid}):
            metrics.record_call("extract", "seq-1", "ABC", "m", 100, 10, 1.5, True)
            metrics.record_call("extract", "seq-1", "ABC", "m", 100, 10, 1.5, True)   # retry
            metrics.record_call("conclude", "hash-1", "ABC", "m", 200, 20, 2.5, True)
        summary = metrics.summarize(__import__("uuid").UUID(rid))
        metrics._connection = None
        self.assertEqual(summary["calls"], 2)
        self.assertEqual(summary["input_tokens"], 300)
        self.assertEqual(summary["seconds"], 4)


if __name__ == "__main__":
    unittest.main()
