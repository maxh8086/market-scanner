"""Tests for collector settings: validation, updates, requests."""
import unittest
from unittest.mock import patch, MagicMock
import uuid

from scanner.collect import settings


class GetSettingsTests(unittest.TestCase):
    """Test get_settings()."""

    def test_get_settings_postgres_down(self):
        """Should return empty dict if Postgres is unreachable."""
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.side_effect = Exception("connection failed")
            result = settings.get_settings()
            self.assertEqual(result, {})

    def test_get_settings_success(self):
        """Should return dict with source as key."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {
                "source": "candles_eod",
                "mode": "scheduled",
                "cron": "35 18 * * 1-5",
                "params": {"note": "eod"},
                "updated_at": "2024-09-30T10:00:00+00:00",
            },
        ]
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = settings.get_settings()
            self.assertIn("candles_eod", result)
            self.assertEqual(result["candles_eod"]["mode"], "scheduled")


class UpdateSettingTests(unittest.TestCase):
    """Test update_setting() validation."""

    def test_unknown_source(self):
        """Should raise ValueError for unknown source."""
        with self.assertRaises(ValueError) as ctx:
            settings.update_setting("unknown_source", mode="scheduled")
        self.assertIn("unknown source", str(ctx.exception))

    def test_invalid_mode(self):
        """Should raise ValueError for invalid mode."""
        with self.assertRaises(ValueError) as ctx:
            settings.update_setting("candles_eod", mode="invalid_mode")
        self.assertIn("must be 'scheduled' or 'manual'", str(ctx.exception))

    def test_invalid_cron(self):
        """Should raise ValueError for invalid cron expression."""
        with self.assertRaises(ValueError) as ctx:
            settings.update_setting("candles_eod", cron="not_a_cron")
        self.assertIn("invalid cron", str(ctx.exception))

    def test_valid_cron(self):
        """Should accept valid cron expression."""
        mock_conn = MagicMock()
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            # Should not raise
            settings.update_setting("candles_eod", cron="35 18 * * 1-5")

    def test_invalid_params_type(self):
        """Should raise ValueError if params is not a dict."""
        with self.assertRaises(ValueError) as ctx:
            settings.update_setting("candles_eod", params="not_a_dict")
        self.assertIn("params must be a dict", str(ctx.exception))

    def test_unknown_params(self):
        """Should reject unknown parameter keys."""
        with self.assertRaises(ValueError) as ctx:
            settings.update_setting("candles_eod", params={"unknown_key": "value"})
        self.assertIn("unknown param keys", str(ctx.exception))

    def test_valid_params(self):
        """Should accept valid parameter keys."""
        mock_conn = MagicMock()
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            # Should not raise
            settings.update_setting("candles_eod", params={"after_close_minutes": 45})

    def test_multiple_updates(self):
        """Should support updating multiple fields at once."""
        mock_conn = MagicMock()
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            settings.update_setting(
                "candles_eod",
                mode="manual",
                cron="0 0 * * *",
                params={"after_close_minutes": 60}
            )
            # Should have called execute with all three updates
            calls = mock_conn.execute.call_args_list
            self.assertTrue(any("mode" in str(call) for call in calls))


class RequestRunTests(unittest.TestCase):
    """Test request_run() for "Run now" button."""

    def test_unknown_source(self):
        """Should raise ValueError for unknown source."""
        with self.assertRaises(ValueError) as ctx:
            settings.request_run("unknown_source")
        self.assertIn("unknown source", str(ctx.exception))

    def test_new_request(self):
        """Should return True when a new request is queued."""
        mock_conn = MagicMock()
        # Simulate: execute succeeds, and our ID is in the DB
        mock_conn.execute.return_value.fetchone.return_value = {"id": "some_id"}
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = settings.request_run("candles_eod")
            self.assertTrue(result)

    def test_existing_request(self):
        """Should return False when a request already exists."""
        mock_conn = MagicMock()
        # Simulate: our INSERT was ignored (conflict), ID not in DB
        mock_conn.execute.return_value.fetchone.return_value = None
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = settings.request_run("candles_eod")
            self.assertFalse(result)


class ListRunsTests(unittest.TestCase):
    """Test list_runs()."""

    def test_list_runs_empty(self):
        """Should return empty list if no runs exist."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = settings.list_runs()
            self.assertEqual(result, [])

    def test_list_runs_with_source_filter(self):
        """Should filter by source when provided."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {
                "id": str(uuid.uuid4()),
                "source": "candles_eod",
                "trigger": "schedule",
                "started_at": "2024-09-30T10:00:00+00:00",
                "finished_at": None,
                "status": "running",
                "from_date": None,
                "to_date": None,
                "rows_fetched": 0,
                "rows_new": 0,
                "message": "",
            }
        ]
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.return_value.__enter__.return_value = mock_conn
            result = settings.list_runs(source="candles_eod")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["source"], "candles_eod")

    def test_list_runs_postgres_error(self):
        """Should return empty list if Postgres fails."""
        with patch("scanner.collect.settings.db.connect") as mock_connect:
            mock_connect.side_effect = Exception("connection failed")
            result = settings.list_runs()
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
