"""Tests for collector sources: time rules, dry-run, error handling."""
import unittest
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock

import os
import pandas as pd
import pytz

from scanner.collect.sources import CandlesEOD, Announcements, SOURCES


ONE_SYMBOL = pd.DataFrame({"Symbol": ["AAA"]})


def _stub_world():
    """One symbol, a fake token and client: nothing reads .env or calls a provider."""
    return [
        patch("scanner.constituents.load_constituents", return_value=ONE_SYMBOL),
        patch("dotenv.load_dotenv"),
        patch.dict(os.environ, {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"}),
        patch("scanner.upstox.UpstoxClient"),
    ]


class _World:
    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()

    def __init__(self):
        self.patches = _stub_world()


class CandlesEODTests(unittest.TestCase):
    """Test candles_eod source: time rules, weekends, partial candles."""

    def setUp(self):
        self.source = CandlesEOD()
        world = _World()
        world.__enter__()
        self.addCleanup(world.__exit__)

    def test_refuses_before_close_plus_margin(self):
        """Refuses to run before 15:30 IST + margin."""
        # Monday 2024-09-30 14:00 IST = 08:30 UTC
        ist = pytz.timezone("Asia/Kolkata")
        before_close = ist.localize(datetime(2024, 9, 30, 14, 0, 0))
        utc_before_close = before_close.astimezone(pytz.UTC)

        result = self.source.run({}, now=utc_before_close)
        self.assertIn("before close", result["message"])
        self.assertEqual(result["fetched"], 0)

    def test_runs_after_close_plus_margin(self):
        """Should run (or attempt to) after 15:30 IST + margin."""
        # Monday 2024-09-30 16:30 IST = 11:00 UTC
        ist = pytz.timezone("Asia/Kolkata")
        after_close = ist.localize(datetime(2024, 9, 30, 16, 30, 0))
        utc_after_close = after_close.astimezone(pytz.UTC)

        # Mock history.collect_eod to avoid the real Upstox call
        with patch("scanner.history.collect_eod") as mock_fetch:
            mock_fetch.return_value = {"fetched": 10, "new": 5, "from": None, "to": None}
            result = self.source.run({}, now=utc_after_close)
            self.assertEqual(result["fetched"], 10)

    def test_skips_weekend(self):
        """Should skip on Saturday and Sunday."""
        # Saturday 2024-10-05 12:00 UTC (well after close)
        saturday = pytz.UTC.localize(datetime(2024, 10, 5, 12, 0, 0))
        result = self.source.run({}, now=saturday)
        self.assertIn("weekend", result["message"])

    def test_custom_margin(self):
        """Should respect custom after_close_minutes parameter."""
        # Monday 2024-09-30 15:45 IST = 10:15 UTC (15 minutes after 15:30 IST)
        ist = pytz.timezone("Asia/Kolkata")
        at_15_45 = ist.localize(datetime(2024, 9, 30, 15, 45, 0))
        utc_at_15_45 = at_15_45.astimezone(pytz.UTC)

        # With default 30-minute margin, should still refuse
        result = self.source.run({"after_close_minutes": 30}, now=utc_at_15_45)
        self.assertIn("before close", result["message"])

        # With 10-minute margin, should run
        with patch("scanner.history.collect_eod") as mock_fetch:
            mock_fetch.return_value = {"fetched": 5, "new": 2, "from": None, "to": None}
            result = self.source.run({"after_close_minutes": 10}, now=utc_at_15_45)
            self.assertEqual(result["fetched"], 5)

    def test_dry_run(self):
        """--dry-run should not fetch."""
        ist = pytz.timezone("Asia/Kolkata")
        after_close = ist.localize(datetime(2024, 9, 30, 16, 30, 0))
        utc_after_close = after_close.astimezone(pytz.UTC)

        result = self.source.run({}, now=utc_after_close, dry_run=True)
        self.assertIn("dry-run", result["message"])
        self.assertEqual(result["fetched"], 0)

    def test_fetch_error_recorded(self):
        """Fetch errors should be recorded in the message, not raised."""
        ist = pytz.timezone("Asia/Kolkata")
        after_close = ist.localize(datetime(2024, 9, 30, 16, 30, 0))
        utc_after_close = after_close.astimezone(pytz.UTC)

        with patch("scanner.history.collect_eod") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("Upstox unreachable")
            result = self.source.run({}, now=utc_after_close)
            self.assertEqual(result["fetched"], 0)
            self.assertIn("RuntimeError", result["message"])


class AnnouncementsTests(unittest.TestCase):
    """Test announcements source."""

    def setUp(self):
        self.source = Announcements()
        world = _World()
        world.__enter__()
        self.addCleanup(world.__exit__)

    @unittest.skipIf(
        not hasattr(__import__("scanner.factors", fromlist=["collect_announcements"]), "collect_announcements"),
        "scanner.factors.collect_announcements not yet implemented by agent A"
    )
    def test_run_calls_collect_announcements(self):
        """run() should call factors.collect_announcements()."""
        with patch("scanner.factors.collect_announcements") as mock_fetch:
            mock_fetch.return_value = {"fetched": 100, "new": 50, "from": None, "to": None}
            result = self.source.run({})
            self.assertEqual(result["fetched"], 100)
            mock_fetch.assert_called_once()

    @unittest.skipIf(
        not hasattr(__import__("scanner.factors", fromlist=["collect_announcements"]), "collect_announcements"),
        "scanner.factors.collect_announcements not yet implemented by agent A"
    )
    def test_dry_run_does_not_fetch(self):
        """dry_run=True should not call the fetch function."""
        with patch("scanner.factors.collect_announcements") as mock_fetch:
            result = self.source.run({}, dry_run=True)
            self.assertEqual(result["fetched"], 0)
            self.assertIn("dry-run", result["message"])
            mock_fetch.assert_not_called()

    @unittest.skipIf(
        not hasattr(__import__("scanner.factors", fromlist=["collect_announcements"]), "collect_announcements"),
        "scanner.factors.collect_announcements not yet implemented by agent A"
    )
    def test_error_handling(self):
        """Errors should be recorded, not raised."""
        with patch("scanner.factors.collect_announcements") as mock_fetch:
            mock_fetch.side_effect = ConnectionError("NSE unreachable")
            result = self.source.run({})
            self.assertEqual(result["fetched"], 0)
            self.assertIn("ConnectionError", result["message"])


class SourcesRegistryTests(unittest.TestCase):
    """Test that all expected sources are registered."""

    def test_all_sources_present(self):
        """The SOURCES dict should have all 5 sources."""
        expected = {"candles_eod", "announcements", "corporate_actions", "filings", "fundamentals"}
        self.assertEqual(set(SOURCES.keys()), expected)

    def test_sources_are_source_instances(self):
        """Each source should be an instance of Source."""
        from scanner.collect.sources import Source
        for name, source in SOURCES.items():
            self.assertIsInstance(source, Source)


if __name__ == "__main__":
    unittest.main()
