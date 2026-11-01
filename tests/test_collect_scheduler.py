"""Tests for collector scheduler logic: due sources, requests, running checks."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid

import pytz
from croniter import croniter

from scanner.collect import scheduler


class DueSourcesTests(unittest.TestCase):
    """Test due_sources() with various schedule states."""

    def test_no_scheduled_sources(self):
        """Only manual sources should never be due."""
        now = datetime(2024, 9, 30, 10, 0, 0, tzinfo=pytz.UTC)
        settings = {
            "candles_eod": {"mode": "manual", "cron": "35 18 * * 1-5"},
        }
        last_runs = {}
        due = scheduler.due_sources(now, settings, last_runs, tz="UTC")
        self.assertEqual(due, [])

    def test_scheduled_source_never_run(self):
        """A scheduled source never run should be due if its cron slot has passed."""
        # At 08:05, with a cron of "0 8 *", the 08:00 slot has passed
        now = datetime(2024, 9, 30, 8, 5, 0, tzinfo=pytz.UTC)
        settings = {
            "announcements": {
                "mode": "scheduled",
                "cron": "0 8 * * *",  # daily at 08:00
            }
        }
        last_runs = {}
        due = scheduler.due_sources(now, settings, last_runs, tz="UTC")
        self.assertIn("announcements", due)

    def test_scheduled_source_already_run_in_current_slot(self):
        """A source run in the current cron slot should not be due again."""
        now = datetime(2024, 9, 30, 8, 30, 0, tzinfo=pytz.UTC)
        last_run = datetime(2024, 9, 30, 8, 5, 0, tzinfo=pytz.UTC)  # ran in this 8:00 slot
        settings = {
            "announcements": {
                "mode": "scheduled",
                "cron": "0 8 * * *",  # daily at 08:00
            }
        }
        last_runs = {"announcements": last_run}
        due = scheduler.due_sources(now, settings, last_runs, tz="UTC")
        self.assertNotIn("announcements", due)

    def test_scheduled_source_missed_slot_on_restart(self):
        """A source with a missed slot (e.g., after service restart) should run once."""
        # Last run was yesterday at 08:00, now it's 10:00 next day
        now = datetime(2024, 10, 1, 10, 0, 0, tzinfo=pytz.UTC)
        last_run = datetime(2024, 9, 30, 8, 0, 0, tzinfo=pytz.UTC)
        settings = {
            "announcements": {
                "mode": "scheduled",
                "cron": "0 8 * * *",  # daily at 08:00
            }
        }
        last_runs = {"announcements": last_run}
        due = scheduler.due_sources(now, settings, last_runs, tz="UTC")
        self.assertIn("announcements", due)

    def test_multiple_sources(self):
        """With multiple sources, only the due ones are returned."""
        now = datetime(2024, 9, 30, 19, 0, 0, tzinfo=pytz.UTC)  # 19:00, AFTER 18:35
        settings = {
            "candles_eod": {
                "mode": "scheduled",
                "cron": "35 18 * * 1-5",  # 18:35 UTC
            },
            "announcements": {
                "mode": "scheduled",
                "cron": "0 2 * * *",  # 02:00 UTC
            },
        }
        last_runs = {
            "announcements": datetime(2024, 9, 30, 2, 0, 0, tzinfo=pytz.UTC),
        }
        due = scheduler.due_sources(now, settings, last_runs, tz="UTC")
        # candles_eod never ran, so it's due
        # announcements ran at 02:00 today; next slot is tomorrow 02:00, so NOT due
        self.assertEqual(set(due), {"candles_eod"})

    def test_weekday_cron(self):
        """Cron with weekday constraints (1-5) should respect them."""
        # Monday 2024-09-30 08:05 UTC
        monday = datetime(2024, 9, 30, 8, 5, 0, tzinfo=pytz.UTC)
        # Sunday 2024-10-06 08:05 UTC
        sunday = datetime(2024, 10, 6, 8, 5, 0, tzinfo=pytz.UTC)

        settings = {
            "candles_eod": {
                "mode": "scheduled",
                "cron": "0 8 * * 1-5",  # Mon-Fri only
            }
        }

        due_monday = scheduler.due_sources(monday, settings, {}, tz="UTC")
        self.assertIn("candles_eod", due_monday)

        due_sunday = scheduler.due_sources(sunday, settings, {}, tz="UTC")
        self.assertNotIn("candles_eod", due_sunday)


class SettingsLoadTests(unittest.TestCase):
    """Test get_settings() with a real (or mocked) Postgres."""

    def test_get_settings_empty(self):
        """get_settings() should return an empty dict if Postgres is unreachable."""
        with patch("scanner.collect.scheduler.db.connect") as mock_connect:
            mock_connect.side_effect = Exception("connection failed")
            settings = scheduler.get_settings(MagicMock())
            self.assertEqual(settings, {})

    def test_get_last_runs_empty(self):
        """get_last_runs() should return an empty dict if no runs exist."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        last_runs = scheduler.get_last_runs(mock_conn)
        self.assertEqual(last_runs, {})

    def test_get_last_runs_multiple_sources(self):
        """get_last_runs() should return one row per source."""
        mock_conn = MagicMock()
        now = datetime.now(pytz.UTC)
        mock_conn.execute.return_value.fetchall.return_value = [
            {"source": "candles_eod", "started_at": now - timedelta(hours=1)},
            {"source": "announcements", "started_at": now - timedelta(hours=2)},
        ]
        last_runs = scheduler.get_last_runs(mock_conn)
        self.assertEqual(len(last_runs), 2)
        self.assertIn("candles_eod", last_runs)
        self.assertIn("announcements", last_runs)


class IsRunningTests(unittest.TestCase):
    """Test is_running() to prevent double-running the same source."""

    def test_no_running_row(self):
        """is_running() should return False if no running row exists."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        running = scheduler.is_running(mock_conn, "candles_eod", timeout_seconds=3600)
        self.assertFalse(running)

    def test_old_running_row_expired(self):
        """is_running() should return False if the running row is older than timeout."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None  # Query finds nothing
        running = scheduler.is_running(mock_conn, "candles_eod", timeout_seconds=100)
        self.assertFalse(running)

    def test_recent_running_row(self):
        """is_running() should return True if a running row is recent."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"id": "some_id"}
        running = scheduler.is_running(mock_conn, "candles_eod", timeout_seconds=3600)
        self.assertTrue(running)


if __name__ == "__main__":
    unittest.main()
