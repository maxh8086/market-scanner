"""Unit tests for feed coverage tracking and gap detection."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from scanner.coverage import required_start, missing_windows


class TestRequiredStart(unittest.TestCase):
    """Tests for required_start function."""

    def test_recent_listing_uses_listing_date(self):
        """Stock listed recently; required start is the listing date."""
        listing_date = date(2024, 6, 1)
        today = date(2026, 9, 30)
        result = required_start(listing_date, today, years=3)
        # today - 3 years = 2023-09-30, but listing is later
        self.assertEqual(result, listing_date)

    def test_old_listing_uses_3year_cutoff(self):
        """Stock listed long ago; required start is today - 3 years."""
        listing_date = date(2000, 1, 1)
        today = date(2026, 9, 30)
        result = required_start(listing_date, today, years=3)
        expected = date(2023, 9, 30)
        self.assertEqual(result, expected)

    def test_custom_years(self):
        """Custom lookback window."""
        listing_date = date(2000, 1, 1)
        today = date(2026, 9, 30)
        result = required_start(listing_date, today, years=2)
        expected = date(2024, 9, 30)
        self.assertEqual(result, expected)


class TestMissingWindows(unittest.TestCase):
    """Tests for missing_windows function."""

    class MockConnection:
        """Mock Postgres connection."""

        def __init__(self, coverage_windows=None):
            self.coverage = coverage_windows or []

        def execute(self, sql, params):
            # Simulate a fetchall that returns coverage rows
            return TestMissingWindows.MockCursor([(w[0], w[1]) for w in self.coverage])

    class MockCursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    def test_no_coverage_returns_full_window(self):
        """No coverage means entire window is missing."""
        conn = self.MockConnection([])
        gaps = missing_windows(conn, "test_feed", date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(gaps, [(date(2024, 1, 1), date(2024, 1, 31))])

    def test_complete_coverage_no_gaps(self):
        """Entire window covered returns no gaps."""
        conn = self.MockConnection([
            (date(2024, 1, 1), date(2024, 1, 31))
        ])
        gaps = missing_windows(conn, "test_feed", date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(gaps, [])

    def test_gap_at_start(self):
        """Gap before first coverage window."""
        conn = self.MockConnection([
            (date(2024, 1, 10), date(2024, 1, 31))
        ])
        gaps = missing_windows(conn, "test_feed", date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(gaps, [(date(2024, 1, 1), date(2024, 1, 9))])

    def test_gap_at_end(self):
        """Gap after last coverage window."""
        conn = self.MockConnection([
            (date(2024, 1, 1), date(2024, 1, 20))
        ])
        gaps = missing_windows(conn, "test_feed", date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(gaps, [(date(2024, 1, 21), date(2024, 1, 31))])

    def test_gap_in_middle(self):
        """Gap between two coverage windows."""
        conn = self.MockConnection([
            (date(2024, 1, 1), date(2024, 1, 10)),
            (date(2024, 1, 20), date(2024, 1, 31))
        ])
        gaps = missing_windows(conn, "test_feed", date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(gaps, [(date(2024, 1, 11), date(2024, 1, 19))])

    def test_multiple_gaps(self):
        """Multiple gaps at start, middle, and end."""
        conn = self.MockConnection([
            (date(2024, 1, 5), date(2024, 1, 10)),
            (date(2024, 1, 20), date(2024, 1, 25))
        ])
        gaps = missing_windows(conn, "test_feed", date(2024, 1, 1), date(2024, 1, 31))
        expected = [
            (date(2024, 1, 1), date(2024, 1, 4)),
            (date(2024, 1, 11), date(2024, 1, 19)),
            (date(2024, 1, 26), date(2024, 1, 31))
        ]
        self.assertEqual(gaps, expected)

    def test_overlapping_coverage_merges(self):
        """Overlapping coverage windows are merged."""
        conn = self.MockConnection([
            (date(2024, 1, 1), date(2024, 1, 10)),
            (date(2024, 1, 8), date(2024, 1, 20)),  # Overlaps
        ])
        gaps = missing_windows(conn, "test_feed", date(2024, 1, 1), date(2024, 1, 31))
        # Should see (1,20) as merged and gap (21,31)
        self.assertEqual(gaps, [(date(2024, 1, 21), date(2024, 1, 31))])

    def test_adjacent_coverage_merges(self):
        """Adjacent coverage windows are merged."""
        conn = self.MockConnection([
            (date(2024, 1, 1), date(2024, 1, 10)),
            (date(2024, 1, 11), date(2024, 1, 20)),
        ])
        gaps = missing_windows(conn, "test_feed", date(2024, 1, 1), date(2024, 1, 31))
        # Should see merged (1,20) and gap (21,31)
        self.assertEqual(gaps, [(date(2024, 1, 21), date(2024, 1, 31))])

    def test_recent_stock_gap_from_listing(self):
        """Recently listed stock: gap from listing date to today."""
        # Listed 2026-06-01, need data from 2026-06-01 to today (2026-09-30)
        # Only have data from 2026-07-01 to 2026-08-31
        conn = self.MockConnection([
            (date(2026, 7, 1), date(2026, 8, 31))
        ])
        gaps = missing_windows(conn, "candles_eod", date(2026, 6, 1), date(2026, 9, 30))
        expected = [
            (date(2026, 6, 1), date(2026, 6, 30)),
            (date(2026, 9, 1), date(2026, 9, 30))
        ]
        self.assertEqual(gaps, expected)


if __name__ == "__main__":
    unittest.main()
