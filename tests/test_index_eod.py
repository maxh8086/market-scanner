"""Tests for the index_eod source (IDX:<NAME> closes) and its scheduler slot."""
import unittest
from datetime import date, datetime
from unittest.mock import patch

import pytz

from scanner.collect import scheduler
from scanner.collect.sources import IndexEOD, SOURCES

IST = pytz.timezone("Asia/Kolkata")


def ist(y, m, d, hh, mm):
    return IST.localize(datetime(y, m, d, hh, mm, 0)).astimezone(pytz.UTC)


class IndexEODTests(unittest.TestCase):
    def setUp(self):
        self.source = IndexEOD()

    def test_registered_under_index_eod(self):
        self.assertIs(SOURCES["index_eod"].__class__, IndexEOD)

    def test_weekend_is_skipped(self):
        # Saturday 2026-11-07 10:00 IST
        result = self.source.run({}, now=ist(2026, 11, 7, 10, 0))
        self.assertEqual(result["message"], "weekend (2026-11-07)")
        self.assertEqual(result["fetched"], 0)

    def test_market_hours_are_skipped(self):
        # Monday 2026-11-09 11:00 IST, bar is still partial
        result = self.source.run({}, now=ist(2026, 11, 9, 11, 0))
        self.assertEqual(result["message"], "market open, waiting for 15:30 IST")
        self.assertEqual(result["fetched"], 0)

    def test_1529_is_still_skipped(self):
        # Monday 2026-11-09 15:29 IST, one minute before the close
        result = self.source.run({}, now=ist(2026, 11, 9, 15, 29))
        self.assertEqual(result["message"], "market open, waiting for 15:30 IST")
        self.assertEqual(result["fetched"], 0)

    def test_1535_is_not_skipped_by_market_gate(self):
        # Monday 2026-11-09 15:35 IST: a manual refresh after the close must pass the gate.
        # Stored data is behind the target and the token is blanked, so the run stops at the
        # token check without any network call.
        with patch("scanner.index_candles.last_stored_date", return_value=date(2026, 11, 6)),                 patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": ""}):
            result = self.source.run({}, now=ist(2026, 11, 9, 15, 35))
        self.assertEqual(result["message"], "skipped: UPSTOX_ANALYTICS_ACCESS_TOKEN not set")
        self.assertNotIn("market open", result["message"])

    def test_already_stored_through_target_is_skipped(self):
        # After 15:30 the target is today, so a store through today means nothing to do.
        with patch("scanner.index_candles.last_stored_date", return_value=date(2026, 11, 9)):
            result = self.source.run({}, now=ist(2026, 11, 9, 16, 0))
        self.assertEqual(result["message"], "already stored through 2026-11-09")
        self.assertEqual(result["fetched"], 0)
        self.assertEqual(result["new"], 0)

    def test_morning_retry_targets_previous_weekday(self):
        # Monday 08:45 IST: the target is Friday 2026-11-06, so a store through Friday is enough.
        with patch("scanner.index_candles.last_stored_date", return_value=date(2026, 11, 6)):
            result = self.source.run({}, now=ist(2026, 11, 9, 8, 45))
        self.assertEqual(result["message"], "already stored through 2026-11-06")

    def test_dry_run_reports_plan_without_fetching(self):
        result = self.source.run({}, now=ist(2026, 11, 9, 16, 0), dry_run=True)
        self.assertEqual(result["fetched"], 0)
        self.assertTrue(result["message"].startswith("dry-run:"))


class IndexEODSchedulerTests(unittest.TestCase):
    SETTINGS = {"index_eod": {"mode": "scheduled", "cron": "45 8,15 * * 1-5"}}

    def test_due_at_1550_after_morning_run(self):
        # Monday 2026-11-09 15:50 IST, last run 08:50 that morning: the 15:45 slot is new.
        now = ist(2026, 11, 9, 15, 50)
        last_runs = {"index_eod": ist(2026, 11, 9, 8, 50)}
        due = scheduler.due_sources(now, self.SETTINGS, last_runs)
        self.assertIn("index_eod", due)

    def test_not_due_when_15_45_slot_already_ran(self):
        now = ist(2026, 11, 9, 15, 50)
        last_runs = {"index_eod": ist(2026, 11, 9, 15, 46)}
        due = scheduler.due_sources(now, self.SETTINGS, last_runs)
        self.assertNotIn("index_eod", due)


if __name__ == "__main__":
    unittest.main()
