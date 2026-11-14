"""Tests for collector sources: time rules, dry-run, error handling."""
import unittest
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock

import os
import tempfile

import pandas as pd
import pytz
import requests

from scanner.collect.sources import CandlesEOD, Announcements, HomeFilings, SOURCES
from scanner.pg import db


ONE_SYMBOL = pd.DataFrame({"Symbol": ["AAA"], "ISIN Code": ["INE000000001"]})


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
        with patch("scanner.history.collect_eod") as mock_fetch, \
                patch("scanner.service_client.fetch_secret", return_value="test-token"):
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
        with patch("scanner.history.collect_eod") as mock_fetch, \
                patch("scanner.service_client.fetch_secret", return_value="test-token"):
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

        with patch("scanner.history.collect_eod") as mock_fetch, \
                patch("scanner.service_client.fetch_secret", return_value="test-token"):
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
        """The SOURCES dict should have the 5 feed sources, index_eod, ath_scan, company_reference and home_filings."""
        expected = {"candles_eod", "index_eod", "announcements", "corporate_actions", "filings", "fundamentals",
                    "ath_scan", "company_reference", "home_filings"}
        self.assertEqual(set(SOURCES.keys()), expected)

    def test_sources_are_source_instances(self):
        """Each source should be an instance of Source."""
        from scanner.collect.sources import Source
        for name, source in SOURCES.items():
            self.assertIsInstance(source, Source)


_FEED_COUNT = 8  # enabled NSE feeds by default (FEEDS with default_enabled True)


class HomeFilingsTests(unittest.TestCase):
    """HomeFilings (F-T4d): plan is offline; run wires run_cycle to the DB, token and API."""

    def setUp(self):
        self.source = HomeFilings()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token_path = os.path.join(self.tmp.name, "token")
        with open(self.token_path, "w", encoding="utf-8") as fh:
            fh.write("tok-123\n")
        env = patch.dict(os.environ, {"HOME_EVENTS_INGEST_TOKEN_FILE": self.token_path})
        env.start()
        self.addCleanup(env.stop)

    def _index(self):
        return MagicMock(universe={"AAA": "INE000000001"}, by_name={"AAA CO": ("AAA", "INE000000001")})

    def _run_cycle_ok(self, **overrides):
        result = {"status": "ok", "fetched": 3, "new": 2,
                  "from": "2026-11-13T10:00:00+05:30", "to": "2026-11-14T09:00:00+00:00", "message": ""}
        result.update(overrides)
        return MagicMock(return_value=result)

    def test_events_flag_and_name(self):
        self.assertTrue(self.source.events)
        self.assertEqual(self.source.name, "home_filings")

    def test_plan_makes_no_call_and_full_shape(self):
        """plan touches no DB, no network and no run_cycle; it reports the enabled feed count."""
        with patch.object(db, "connect", side_effect=AssertionError("db touched")), \
                patch("requests.Session", side_effect=AssertionError("session made")), \
                patch("scanner.home_events.run_cycle", side_effect=AssertionError("run_cycle called")):
            result = self.source.plan({})
        self.assertEqual(set(result.keys()), {"fetched", "new", "from", "to", "message"})
        self.assertEqual(result["fetched"], 0)
        self.assertEqual(result["new"], 0)
        self.assertIsNone(result["from"])
        self.assertIsNone(result["to"])
        self.assertEqual(result["message"], f"dry-run: would fetch {_FEED_COUNT} NSE feeds")

    def test_plan_counts_enabled_feeds_param(self):
        result = self.source.plan({"enabled_feeds": ["nse:Financial_Results", "nse:Sast_Regulation29"]})
        self.assertEqual(result["message"], "dry-run: would fetch 2 NSE feeds")

    def test_plan_bad_param_returns_config_key(self):
        result = self.source.plan({"post_timeout_s": 0})
        self.assertEqual(result["message"], "config:post_timeout_s")
        self.assertEqual(result["fetched"], 0)

    def test_run_dry_run_equals_plan(self):
        with patch("scanner.home_events.run_cycle", side_effect=AssertionError("run_cycle called")):
            self.assertEqual(self.source.run({}, dry_run=True), self.source.plan({}))

    def test_run_wiring(self):
        """run passes the index, FEEDS, a PgCooldown and a browser-like session; post reaches post_events."""
        from scanner import home_events
        from scanner.collect.cooldown import PgCooldown

        fake_cycle = self._run_cycle_ok()
        with patch.object(db, "connect", return_value=_CtxConn()), \
                patch("scanner.company_reference.load_index_for_source", return_value=self._index()) as load, \
                patch("scanner.home_events.run_cycle", fake_cycle), \
                patch("scanner.home_events.post_events", return_value={"inserted": 1}) as post_events, \
                patch("collect.api_base_url", return_value="http://api.test"), \
                patch.object(requests.Session, "request") as request:
            result = self.source.run({}, now=datetime(2026, 11, 14, 4, 0))
            fake_cycle.call_args.kwargs["post"]([{"dedupe_key": "k"}])
        self.assertEqual(load.call_args[0][1], "nse_csv")
        kwargs = fake_cycle.call_args.kwargs
        self.assertEqual(kwargs["universe"], {"AAA": "INE000000001"})
        self.assertEqual(kwargs["by_name"], {"AAA CO": ("AAA", "INE000000001")})
        self.assertIs(kwargs["feeds"], home_events.FEEDS)
        self.assertIs(kwargs["parse_fn"], home_events.parse)
        self.assertIsInstance(kwargs["cooldown"], PgCooldown)
        self.assertIsInstance(kwargs["session"], requests.Session)
        self.assertIn("Chrome/", kwargs["session"].headers["User-Agent"])
        self.assertEqual(kwargs["session"].headers["Accept-Language"], "en-US,en;q=0.9")
        request.assert_not_called()
        self.assertEqual(fake_cycle.call_args.args[1], pytz.UTC.localize(datetime(2026, 11, 14, 4, 0)))

        post_events.assert_called_once()
        self.assertEqual(post_events.call_args.kwargs["base_url"], "http://api.test")
        self.assertEqual(post_events.call_args.kwargs["token"], "tok-123")
        self.assertEqual(post_events.call_args.kwargs["timeout_s"], 15)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fetched"], 3)
        self.assertEqual(result["new"], 2)
        self.assertEqual(result["from"], date(2026, 11, 13))
        self.assertEqual(result["to"], date(2026, 11, 14))
        self.assertEqual(result["message"], "")

    def test_naive_now_is_treated_as_utc(self):
        fake_cycle = self._run_cycle_ok()
        with patch.object(db, "connect", return_value=_CtxConn()), \
                patch("scanner.company_reference.load_index_for_source", return_value=self._index()), \
                patch("scanner.home_events.run_cycle", fake_cycle), \
                patch("collect.api_base_url", return_value="http://api.test"):
            self.source.run({}, now=datetime(2026, 11, 14, 4, 0))
        passed = fake_cycle.call_args.args[1]
        self.assertEqual(passed.tzinfo, pytz.UTC)
        self.assertEqual(passed.hour, 4)

    def test_null_window_stays_none(self):
        fake_cycle = self._run_cycle_ok(**{"from": None, "to": None})
        with patch.object(db, "connect", return_value=_CtxConn()), \
                patch("scanner.company_reference.load_index_for_source", return_value=self._index()), \
                patch("scanner.home_events.run_cycle", fake_cycle), \
                patch("collect.api_base_url", return_value="http://api.test"):
            result = self.source.run({}, now=datetime(2026, 11, 14, 4, 0))
        self.assertIsNone(result["from"])
        self.assertIsNone(result["to"])

    def test_run_cycle_skipped_status_is_returned(self):
        fake_cycle = self._run_cycle_ok(status="skipped", fetched=0, new=0, message="exchange_cooldown",
                                        **{"from": None, "to": None})
        with patch.object(db, "connect", return_value=_CtxConn()), \
                patch("scanner.company_reference.load_index_for_source", return_value=self._index()), \
                patch("scanner.home_events.run_cycle", fake_cycle), \
                patch("collect.api_base_url", return_value="http://api.test"):
            result = self.source.run({}, now=datetime(2026, 11, 14, 4, 0))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["message"], "exchange_cooldown")

    def test_missing_token_file_fails_without_leaking(self):
        missing = os.path.join(self.tmp.name, "no-such-token")
        with patch.dict(os.environ, {"HOME_EVENTS_INGEST_TOKEN_FILE": missing}), \
                patch("scanner.home_events.run_cycle", side_effect=AssertionError("run_cycle called")):
            result = self.source.run({}, now=datetime(2026, 11, 14, 4, 0))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], "token_unavailable")
        self.assertNotIn(missing, result["message"])
        self.assertNotIn("tok-123", result["message"])

    def test_empty_token_file_fails(self):
        with open(self.token_path, "w", encoding="utf-8") as fh:
            fh.write("  \n")
        with patch("scanner.home_events.run_cycle", side_effect=AssertionError("run_cycle called")):
            result = self.source.run({}, now=datetime(2026, 11, 14, 4, 0))
        self.assertEqual(result["message"], "token_unavailable")

    def test_db_error_gives_index_unavailable(self):
        with patch.object(db, "connect", side_effect=ConnectionError("postgres down")), \
                patch("scanner.home_events.run_cycle", side_effect=AssertionError("run_cycle called")):
            result = self.source.run({}, now=datetime(2026, 11, 14, 4, 0))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], "index_unavailable: ConnectionError")

    def test_run_cycle_exception_gives_failed_with_class_name(self):
        with patch.object(db, "connect", return_value=_CtxConn()), \
                patch("scanner.company_reference.load_index_for_source", return_value=self._index()), \
                patch("scanner.home_events.run_cycle", side_effect=RuntimeError("boom")), \
                patch("collect.api_base_url", return_value="http://api.test"):
            result = self.source.run({}, now=datetime(2026, 11, 14, 4, 0))
        self.assertEqual(result["status"], "failed")
        self.assertIn("RuntimeError", result["message"])
        self.assertIsNone(result["from"])


class _CtxConn:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    unittest.main()
