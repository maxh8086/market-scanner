"""ath_scan.main() branches for the candidate table and the export switch.

Everything is patched: no network, no database, no report files outside a temp dir.
The table store is a MagicMock, as in tests/test_ath_scan_backend.py.
"""
import io
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import pandas as pd

import ath_scan

IST = timezone(timedelta(hours=5, minutes=30))
FIXED_NOW = datetime(2026, 11, 13, 15, 30, tzinfo=IST)
SCAN_DATE = date(2026, 11, 13)
ZERO_MSG = "ath_scan found zero candidates"


def _constituents():
    return pd.DataFrame([
        {"Company Name": "Alpha", "Industry": "X", "Symbol": "AAA", "Series": "EQ", "ISIN Code": "INE000000001"},
        {"Company Name": "Beta", "Industry": "X", "Symbol": "BBB", "Series": "EQ", "ISIN Code": "INE000000002"},
    ])


class _Client:
    """Stands in for UpstoxClient: two quotes, no network."""

    def __init__(self, *a, **kw):
        pass

    def quote_ohlc(self, keys_by_symbol):
        snap = SimpleNamespace(ltp=100.0, today_high=101.0)
        return {s: snap for s in keys_by_symbol}, []

    def stats(self):
        return {"requests_made": 0, "responses_429": 0, "seconds_waiting": 0}


def _candidate(*_args, **_kwargs):
    """ath.scan_symbol result for a symbol inside max_dist."""
    return SimpleNamespace(ath_high=110.0, ath_date="2026-10-01", ath_close=109.0,
                           distance_pct=-5.0, bucket="NEAR", days_since_ath=30,
                           listed_days=500, recent_ipo=False)


def _no_candidate(*_args, **_kwargs):
    """ath.scan_symbol result outside max_dist: excluded, not an error."""
    return None


def _stack(patches):
    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


class MainBranchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = mock.MagicMock()
        self.write_outputs = mock.MagicMock(return_value=("a.csv", "a.xlsx"))
        self.write_skipped = mock.MagicMock()

    def _run(self, extra_argv, scan_symbol, rows_written):
        self.store.write_scan.return_value = rows_written
        argv = ["ath_scan.py", "--no-factors", "--output-dir", self.tmp] + list(extra_argv)
        empty_candles = SimpleNamespace(candles=pd.DataFrame(columns=["date", "high", "close"]))
        patches = [
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(ath_scan, "now_ist", return_value=FIXED_NOW),
            mock.patch.object(ath_scan, "UpstoxClient", _Client),
            mock.patch.object(ath_scan, "load_constituents", return_value=_constituents()),
            mock.patch.object(ath_scan, "ath_scan_store", self.store),
            mock.patch.object(ath_scan.report, "write_outputs", self.write_outputs),
            mock.patch.object(ath_scan.report, "write_skipped", self.write_skipped),
            mock.patch.object(ath_scan.report, "print_summary"),
            mock.patch.object(ath_scan.isin_resolver, "try_load_master", return_value=(None, "offline test")),
            mock.patch("scanner.marketdata.get_backend", return_value="sqlite"),  # no DB check
            mock.patch.object(ath_scan.history, "get_history", return_value=empty_candles),
            mock.patch.object(ath_scan.ath, "scan_symbol", side_effect=scan_symbol),
            mock.patch.object(ath_scan.indicators, "compute_trend",
                              return_value={"ema50": None, "sma200": None, "above_ema50": "",
                                            "above_sma200": "", "trend": ""}),
        ]
        out, err = io.StringIO(), io.StringIO()
        with _stack(patches), redirect_stdout(out), redirect_stderr(err):
            code = ath_scan.main()
        return code, out.getvalue(), err.getvalue()

    def test_normal_run_writes_scan_once_with_date_and_frame(self):
        code, _, _ = self._run(["--symbols", "AAA,BBB"], _candidate, rows_written=2)
        self.assertEqual(code, 0)
        self.store.write_scan.assert_called_once()
        conn, scan_date, frame = self.store.write_scan.call_args[0]
        self.assertIs(conn, self.store.connect.return_value.__enter__.return_value)
        self.assertEqual(scan_date, SCAN_DATE)
        self.assertIsInstance(frame, pd.DataFrame)
        self.assertEqual(sorted(frame["symbol"]), ["AAA", "BBB"])
        self.assertEqual(sorted(frame["isin"]), ["INE000000001", "INE000000002"])

    def test_no_export_skips_report_files_but_still_writes_the_table(self):
        code, out, _ = self._run(["--symbols", "AAA,BBB", "--no-export"], _candidate, rows_written=2)
        self.assertEqual(code, 0)
        self.write_outputs.assert_not_called()
        self.write_skipped.assert_not_called()
        self.store.write_scan.assert_called_once()
        self.assertIn("(no file export)", out)

    def test_default_run_calls_write_outputs_and_write_skipped(self):
        code, _, _ = self._run(["--symbols", "AAA,BBB"], _candidate, rows_written=2)
        self.assertEqual(code, 0)
        self.write_outputs.assert_called_once()
        self.write_skipped.assert_called_once()

    def test_full_universe_zero_candidates_returns_4_with_message(self):
        code, _, err = self._run([], _no_candidate, rows_written=0)
        self.assertEqual(code, 4)
        self.assertIn(ZERO_MSG, err)
        self.store.write_scan.assert_called_once()

    def test_symbols_run_with_zero_candidates_returns_0(self):
        code, _, err = self._run(["--symbols", "AAA,BBB"], _no_candidate, rows_written=0)
        self.assertEqual(code, 0)
        self.assertNotIn(ZERO_MSG, err)


if __name__ == "__main__":
    unittest.main()
