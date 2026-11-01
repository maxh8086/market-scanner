"""ath_scan.py fails fast on a dead Postgres backend (exit 3) and still skips
a single bad symbol. Everything is patched: no network, no DB, no containers."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import psycopg

import ath_scan


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


class _FakeConn:
    def execute(self, sql):
        return self

    def fetchone(self):
        return {"?column?": 1}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class BackendCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _run_main(self, extra_patches=()):
        argv = ["ath_scan.py", "--symbols", "AAA,BBB", "--no-factors", "--output-dir", self.tmp]
        out, err = io.StringIO(), io.StringIO()
        self.write_skipped = mock.MagicMock()
        patches = [
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(ath_scan, "UpstoxClient", _Client),
            mock.patch.object(ath_scan, "load_constituents", return_value=_constituents()),
            mock.patch.object(ath_scan.report, "write_outputs", return_value=("a.csv", "a.xlsx")),
            mock.patch.object(ath_scan.report, "print_summary"),
            mock.patch.object(ath_scan.report, "write_skipped", self.write_skipped),
            # No network for the ISIN master in these tests: CSV ISINs are used.
            mock.patch.object(ath_scan.isin_resolver, "try_load_master", return_value=(None, "offline test")),
        ] + list(extra_patches)
        with contextlib_stack(patches), redirect_stdout(out), redirect_stderr(err):
            code = ath_scan.main()
        return code, out.getvalue(), err.getvalue()

    def test_dead_postgres_exits_3_without_skipping_every_symbol(self):
        hist = mock.MagicMock()
        patches = [
            mock.patch("scanner.marketdata.get_backend", return_value="postgres"),
            mock.patch("scanner.pg.db.connect",
                       side_effect=psycopg.OperationalError(
                           "connection refused: host=db password=hunter2")),
            mock.patch.object(ath_scan.history, "get_history", return_value=hist),
        ]
        code, _, err = self._run_main(patches)
        self.assertEqual(code, 3)
        self.write_skipped.assert_not_called()
        self.assertIn("Backend check failed: OperationalError", err)
        self.assertIn("password=***", err)
        self.assertNotIn("hunter2", err)
        self.assertIn("scripts/ensure_postgres.ps1", err)
        self.assertIn("MARKETDATA_BACKEND=sqlite", err)

    def test_per_symbol_value_error_skips_only_that_symbol(self):
        def fake_history(client, key, sym, force_refresh=False, today=None):
            if sym == "AAA":
                raise ValueError("bad candles")
            return SimpleNamespace(candles=pd.DataFrame(columns=["date", "high", "close"]))

        patches = [
            mock.patch("scanner.marketdata.get_backend", return_value="postgres"),
            mock.patch("scanner.pg.db.connect", return_value=_FakeConn()),
            mock.patch.object(ath_scan.history, "get_history", side_effect=fake_history),
            # BBB is a valid symbol outside the max-dist cutoff: no row, no skip.
            mock.patch.object(ath_scan.ath, "scan_symbol", return_value=None),
        ]
        code, _, _ = self._run_main(patches)
        self.assertEqual(code, 0)
        self.write_skipped.assert_called_once()
        skipped = self.write_skipped.call_args[0][0]
        self.assertEqual([r["symbol"] for r in skipped], ["AAA"])
        self.assertIn("history fetch failed: bad candles", skipped[0]["reason"])

    def test_sqlite_backend_does_no_check(self):
        with mock.patch("scanner.marketdata.get_backend", return_value="sqlite"), \
             mock.patch("scanner.pg.db.connect") as connect:
            self.assertIsNone(ath_scan._check_backend())
        connect.assert_not_called()

    def test_invalid_backend_value_exits_3(self):
        with mock.patch("scanner.marketdata.get_backend", side_effect=ValueError("MARKETDATA_BACKEND='x' is not valid")):
            line = ath_scan._check_backend()
        self.assertIn("ValueError", line)
        self.assertIn("is not valid", line)

    def test_mid_run_operational_error_aborts_with_3(self):
        patches = [
            mock.patch("scanner.marketdata.get_backend", return_value="postgres"),
            mock.patch("scanner.pg.db.connect", return_value=_FakeConn()),
            mock.patch.object(ath_scan.history, "get_history",
                              side_effect=psycopg.OperationalError("server closed the connection")),
        ]
        code, _, err = self._run_main(patches)
        self.assertEqual(code, 3)
        self.write_skipped.assert_not_called()
        self.assertIn("Backend failure mid-run", err)


def contextlib_stack(patches):
    from contextlib import ExitStack
    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


if __name__ == "__main__":
    unittest.main()
