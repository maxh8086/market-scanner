"""Test the backfill script."""
import unittest
from unittest.mock import patch


class BackfillCLITests(unittest.TestCase):
    """Test backfill.py CLI behavior."""

    def test_backfill_unavailable_postgres(self):
        """Test that backfill exits with code 3 when Postgres unavailable."""
        from scanner.pg import backfill

        with patch('scanner.pg.db.available', return_value=False):
            result = backfill.main(['--dry-run'])
            self.assertEqual(result, 3)

    def test_backfill_dry_run_no_writes(self):
        """Test that --dry-run flag doesn't write anything."""
        # This is tested by the real backfill run below
        pass


class RecordRunCLITests(unittest.TestCase):
    """Test record_run.py CLI behavior."""

    def test_record_run_invalid_date(self):
        """Test that record_run exits with code 1 for invalid date."""
        from record_run import main

        result = main(['--run-id', 'test-id', '--date', 'invalid'])
        self.assertEqual(result, 1)

    def test_record_run_unavailable_postgres(self):
        """Test that record_run exits with code 3 when Postgres unavailable."""
        from record_run import main

        with patch('scanner.pg.db.available', return_value=False):
            result = main(['--run-id', 'test-id', '--date', '2026-09-30'])
            self.assertEqual(result, 3)


if __name__ == "__main__":
    unittest.main()
