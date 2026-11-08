"""Offline tests for the incremental mode of scanner/index_candles.py. No database or network."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from scanner import index_candles as ic


class FakeClient:
    """Records every daily_candles request and returns one candle dated at the window end."""

    def __init__(self, empty: bool = False):
        self.calls: list[tuple[str, dt.date, dt.date]] = []
        self.empty = empty

    def daily_candles(self, key, frm, to):
        self.calls.append((key, frm, to))
        if self.empty:
            return []
        return [{"date": f"{to.isoformat()}T00:00:00+05:30", "open": 1, "high": 1,
                 "low": 1, "close": 1, "volume": 1}]


class LastStoredDateTests(unittest.TestCase):
    def _conn_returning(self, row):
        conn = mock.MagicMock()
        conn.execute.return_value.fetchone.return_value = row
        ctx = mock.MagicMock()
        ctx.__enter__.return_value = conn
        ctx.__exit__.return_value = False
        return ctx, conn

    def test_returns_max_date_for_the_index_symbol(self):
        ctx, conn = self._conn_returning({"last_date": dt.date(2026, 11, 6)})
        with mock.patch.object(ic, "connect", return_value=ctx):
            self.assertEqual(ic.last_stored_date("Nifty 50"), dt.date(2026, 11, 6))
        sql, params = conn.execute.call_args[0]
        self.assertIn("FROM candles", sql)
        self.assertEqual(params, ("IDX:NIFTY 50",))

    def test_none_when_no_candles(self):
        ctx, _ = self._conn_returning({"last_date": None})
        with mock.patch.object(ic, "connect", return_value=ctx):
            self.assertIsNone(ic.last_stored_date("Nifty Bank"))


class IncrementalWindowTests(unittest.TestCase):
    def _run_main(self, argv, last_date, client):
        with mock.patch.object(ic, "UpstoxClient", return_value=client), \
                mock.patch.object(ic, "last_stored_date", return_value=last_date), \
                mock.patch.object(ic, "store", return_value=1):
            return ic.main(argv)

    def test_no_stored_date_triggers_full_fetch_from_start_date(self):
        client = FakeClient()
        with mock.patch("builtins.print"):
            code = self._run_main(["--incremental"], None, client)
        self.assertEqual(code, 0)
        nifty_50_calls = [c for c in client.calls if c[0] == "NSE_INDEX|Nifty 50"]
        # The walk goes back in chunks until it reaches START_DATE.
        self.assertEqual(nifty_50_calls[-1][1], ic.START_DATE)
        # The full walk ends yesterday, as in the default mode.
        self.assertEqual(nifty_50_calls[0][2], dt.date.today() - dt.timedelta(days=1))
        self.assertGreater(len(nifty_50_calls), 1)

    def test_stored_date_requests_only_recent_range_through_yesterday(self):
        last = dt.date(2026, 11, 1)
        client = FakeClient()
        with mock.patch("builtins.print"):
            code = self._run_main(["--incremental"], last, client)
        self.assertEqual(code, 0)
        yesterday = dt.date.today() - dt.timedelta(days=1)
        expected_from = last - dt.timedelta(days=ic.INCREMENTAL_OVERLAP_DAYS)
        self.assertTrue(client.calls)
        for key, frm, to in client.calls:
            self.assertGreaterEqual(frm, expected_from)
            self.assertLessEqual(to, yesterday)
        nifty_50_calls = [c for c in client.calls if c[0] == "NSE_INDEX|Nifty 50"]
        # One window covers the whole range, so the walk stops after one request.
        self.assertEqual(nifty_50_calls, [("NSE_INDEX|Nifty 50", expected_from, yesterday)])

    def test_incremental_mode_never_requests_a_window_ending_today(self):
        last = dt.date(2026, 11, 1)
        client = FakeClient()
        with mock.patch("builtins.print"):
            self._run_main(["--incremental"], last, client)
        today = dt.date.today()
        self.assertTrue(client.calls)
        self.assertFalse(any(to == today for _, _, to in client.calls))

    def test_default_mode_ignores_stored_date_and_does_full_fetch(self):
        client = FakeClient()
        with mock.patch("builtins.print"), \
                mock.patch.object(ic, "last_stored_date", side_effect=AssertionError("not called")):
            # Patch again so the assertion can fire if the default mode queried the DB.
            with mock.patch.object(ic, "UpstoxClient", return_value=client), \
                    mock.patch.object(ic, "store", return_value=1):
                code = ic.main([])
        self.assertEqual(code, 0)
        nifty_50_calls = [c for c in client.calls if c[0] == "NSE_INDEX|Nifty 50"]
        self.assertEqual(nifty_50_calls[-1][1], ic.START_DATE)


if __name__ == "__main__":
    unittest.main()
