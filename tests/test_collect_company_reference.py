"""Offline tests for the company_reference collector source (monthly NSE and Upstox refresh).

Nothing touches the network or a database: the loader DSN, the Postgres connection and the
refresh job are patched.
"""
import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytz

from scanner.collect.sources import SOURCES, CompanyReference, Source


class CompanyReferenceSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = CompanyReference()

    def test_registered_under_company_reference(self):
        self.assertIn("company_reference", SOURCES)
        self.assertIsInstance(SOURCES["company_reference"], CompanyReference)
        self.assertIsInstance(SOURCES["company_reference"], Source)
        self.assertEqual(self.source.name, "company_reference")

    def test_dry_run_fetches_nothing(self):
        with patch("scanner.company_reference_job.run_refresh") as refresh, \
                patch("psycopg.connect") as connect:
            result = self.source.run({}, dry_run=True)
        refresh.assert_not_called()
        connect.assert_not_called()
        self.assertEqual(result["fetched"], 0)
        self.assertTrue(result["message"].startswith("dry-run:"))

    def test_success_sums_rows_and_reports_ist_date(self):
        # 2026-12-11 20:00 UTC is 2026-12-12 01:30 IST, so the window date is the 12th in IST.
        now = datetime(2026, 12, 11, 20, 0, tzinfo=pytz.UTC)
        conn = MagicMock()
        counts = {"nse_csv": 2633, "upstox_master": 2757, "NIFTY TOTAL MARKET": 752}
        with patch("scanner.company_reference_job.loader_dsn", return_value="dsn-text") as dsn, \
                patch("psycopg.connect", return_value=conn) as connect, \
                patch("scanner.company_reference_job.run_refresh", return_value=counts) as refresh:
            result = self.source.run({}, now=now)
        dsn.assert_called_once_with()
        connect.assert_called_once_with("dsn-text")
        refresh.assert_called_once_with(conn, today=date(2026, 12, 12))
        conn.close.assert_called_once_with()
        self.assertEqual(result["fetched"], 2633 + 2757 + 752)
        self.assertEqual(result["new"], 0)
        self.assertEqual(result["to"], date(2026, 12, 12))
        self.assertIsNone(result["from"])
        self.assertEqual(result["message"], "")

    def test_refresh_failure_reports_message_and_closes_connection(self):
        conn = MagicMock()
        with patch("scanner.company_reference_job.loader_dsn", return_value="dsn-text"), \
                patch("psycopg.connect", return_value=conn), \
                patch("scanner.company_reference_job.run_refresh",
                      side_effect=RuntimeError("NSE equity list download failed: timeout")):
            result = self.source.run({}, now=datetime(2026, 12, 12, 4, 0, tzinfo=pytz.UTC))
        conn.close.assert_called_once_with()
        self.assertEqual(result["fetched"], 0)
        self.assertIsNone(result["to"])
        self.assertIn("NSE equity list download failed", result["message"])

    def test_missing_loader_password_is_reported_not_raised(self):
        with patch("scanner.company_reference_job.loader_dsn",
                   side_effect=RuntimeError("POSTGRES_LOADER_PASSWORD_FILE is unset")), \
                patch("psycopg.connect") as connect, \
                patch("scanner.company_reference_job.run_refresh") as refresh:
            result = self.source.run({}, now=datetime(2026, 12, 12, 4, 0, tzinfo=pytz.UTC))
        connect.assert_not_called()
        refresh.assert_not_called()
        self.assertEqual(result["fetched"], 0)
        self.assertIn("POSTGRES_LOADER_PASSWORD_FILE", result["message"])

    def test_connection_failure_is_reported_not_raised(self):
        with patch("scanner.company_reference_job.loader_dsn", return_value="dsn-text"), \
                patch("psycopg.connect", side_effect=OSError("connection refused")), \
                patch("scanner.company_reference_job.run_refresh") as refresh:
            result = self.source.run({}, now=datetime(2026, 12, 12, 4, 0, tzinfo=pytz.UTC))
        refresh.assert_not_called()
        self.assertEqual(result["fetched"], 0)
        self.assertIn("connection refused", result["message"])


if __name__ == "__main__":
    unittest.main()
