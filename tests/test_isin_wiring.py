"""Offline tests for the ISIN resolver wiring in ath_scan.py and scripts/pull_upstox_5y.py.

No network, no database: the master, the Upstox client, the constituents and the
history loader are all patched.
"""
import gzip
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

import ath_scan
from scanner import isin_resolver as ir
from scanner.upstox import UpstoxError
from scripts import pull_upstox_5y as pull

TODAY = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 10, 0, 0)

# AAA's CSV ISIN is stale; the master has the new one. BBB is unchanged and in the master.
MASTER = {
    "by_symbol": {"AAA": "INE000000099", "BBB": "INE000000002"},
    "by_isin": {"INE000000099": "AAA", "INE000000002": "BBB"},
}
OLD_AAA = "INE000000001"
NEW_AAA = "INE000000099"


def _constituents():
    return pd.DataFrame([
        {"Company Name": "Alpha", "Industry": "X", "Symbol": "AAA", "Series": "EQ", "ISIN Code": OLD_AAA},
        {"Company Name": "Beta", "Industry": "X", "Symbol": "BBB", "Series": "EQ", "ISIN Code": "INE000000002"},
    ])


def _ath_patches(stack, master_result, backend="sqlite", record_side_effect=None):
    """Patch everything main() touches. Returns the list of keys sent to quote_ohlc."""
    seen: list[str] = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def quote_ohlc(self, keys_by_symbol):
            seen.extend(keys_by_symbol.values())
            return {s: SimpleNamespace(ltp=100.0, today_high=101.0) for s in keys_by_symbol}, []

        def stats(self):
            return {"requests_made": 0, "responses_429": 0, "seconds_waiting": 0}

    stack.enter_context(mock.patch.object(ath_scan, "UpstoxClient", _Client))
    stack.enter_context(mock.patch.object(ath_scan, "load_constituents", return_value=_constituents()))
    stack.enter_context(mock.patch.object(ath_scan.report, "write_outputs", return_value=("a.csv", "a.xlsx")))
    stack.enter_context(mock.patch.object(ath_scan.report, "print_summary"))
    stack.enter_context(mock.patch.object(ath_scan.report, "write_skipped"))
    stack.enter_context(mock.patch.object(ath_scan.isin_resolver, "try_load_master", return_value=master_result))
    stack.enter_context(mock.patch("scanner.marketdata.get_backend", return_value=backend))
    stack.enter_context(mock.patch("scanner.pg.db.connect", return_value=mock.MagicMock()))
    stack.enter_context(mock.patch.object(
        ath_scan.history, "get_history",
        side_effect=lambda *a, **k: SimpleNamespace(candles=pd.DataFrame(columns=["date", "high", "close"]))))
    stack.enter_context(mock.patch.object(ath_scan.ath, "scan_symbol", return_value=None))
    record = stack.enter_context(mock.patch.object(ath_scan.isin_resolver, "record", return_value=0,
                                                   side_effect=record_side_effect))
    return seen, record


def _run_ath(master_result, backend="sqlite", record_side_effect=None):
    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        argv = ["ath_scan.py", "--symbols", "AAA,BBB", "--no-factors", "--output-dir", tmp]
        stack.enter_context(mock.patch.object(ath_scan.sys, "argv", argv))
        seen, record = _ath_patches(stack, master_result, backend, record_side_effect)
        with redirect_stdout(out), redirect_stderr(err):
            code = ath_scan.main()
    return code, seen, out.getvalue(), err.getvalue(), record


class AthScanIsinWiringTests(unittest.TestCase):
    def test_instrument_key_uses_resolved_isin_and_keeps_symbol(self):
        code, seen, out, _, _ = _run_ath((MASTER, ""))
        self.assertEqual(code, 0)
        self.assertIn(f"NSE_EQ|{NEW_AAA}", seen)
        self.assertNotIn(f"NSE_EQ|{OLD_AAA}", seen)
        self.assertIn("NSE_EQ|INE000000002", seen)
        self.assertIn(f"AAA: ISIN {OLD_AAA} -> {NEW_AAA}", out)
        # BBB is unchanged, so no change line for it.
        self.assertNotIn("BBB: ISIN", out)

    def test_master_failure_keeps_csv_isins_and_scan_continues(self):
        code, seen, _, err, _ = _run_ath((None, "RuntimeError: master unavailable"))
        self.assertEqual(code, 0)
        self.assertIn(f"NSE_EQ|{OLD_AAA}", seen)
        self.assertEqual(err.count("Warning: ISIN master unavailable"), 1)
        self.assertIn("RuntimeError", err)

    def test_postgres_backend_records_isin_history(self):
        code, _, _, _, record = _run_ath((MASTER, ""), backend="postgres")
        self.assertEqual(code, 0)
        record.assert_called_once()
        resolutions = record.call_args[0][1]
        self.assertEqual({r.symbol for r in resolutions}, {"AAA", "BBB"})

    def test_record_failure_only_warns(self):
        code, _, _, err, _ = _run_ath((MASTER, ""), backend="postgres",
                                      record_side_effect=RuntimeError("db down"))
        self.assertEqual(code, 0)
        self.assertIn("Warning: ISIN history not recorded (RuntimeError)", err)

    def test_sqlite_backend_does_not_record(self):
        _, _, _, _, record = _run_ath((MASTER, ""), backend="sqlite")
        record.assert_not_called()


class _Client400:
    """Upstox stand-in: 400 for the bad key, empty candles for any other key."""

    def __init__(self, bad_key: str, status: int = 400):
        self.bad_key = bad_key
        self.status = status
        self.keys: list[str] = []

    def daily_candles(self, key, from_date, to_date):
        self.keys.append(key)
        if key == self.bad_key:
            raise UpstoxError(f"HTTP {self.status} from https://api.example -- Invalid instrument")
        return []


class PullUniverseWiringTests(unittest.TestCase):
    def _csv(self):
        return pd.DataFrame([
            {"Symbol": "AAA", "ISIN Code": OLD_AAA},
            {"Symbol": "BBB", "ISIN Code": "INE000000002"},
        ])

    def test_load_universe_applies_resolution(self):
        with mock.patch.object(pull, "load_constituents", return_value=self._csv()), \
             mock.patch.object(ir, "try_load_master", return_value=(MASTER, "")):
            pairs = pull.load_universe(None, None)
        self.assertEqual(pairs, [("AAA", NEW_AAA), ("BBB", "INE000000002")])

    def test_load_universe_falls_back_when_master_unavailable(self):
        with mock.patch.object(pull, "load_constituents", return_value=self._csv()), \
             mock.patch.object(ir, "try_load_master", return_value=(None, "RuntimeError: down")):
            out = io.StringIO()
            with redirect_stdout(out):
                pairs = pull.load_universe(None, None)
        self.assertEqual(pairs, [("AAA", OLD_AAA), ("BBB", "INE000000002")])
        self.assertIn("ISIN master unavailable", out.getvalue())


class PullSymbolRetryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"UPSTOX_PULL_LOG": "sqlite"})
        self._env.start()
        self.conn = pull.connect(Path(self._tmp.name) / "candles.db")

    def tearDown(self):
        self.conn.close()
        self._env.stop()
        self._tmp.cleanup()

    def _pull(self, client, isin=OLD_AAA):
        with redirect_stdout(io.StringIO()):
            return pull.pull_symbol(client, self.conn, "AAA", isin, 10, TODAY, NOW)

    def test_retries_once_on_400_when_isin_changed(self):
        client = _Client400(bad_key=f"NSE_EQ|{OLD_AAA}")
        with mock.patch.object(ir, "try_load_master", return_value=(MASTER, "")) as tlm:
            status = self._pull(client)
        self.assertEqual(status, "empty")
        self.assertEqual(client.keys, [f"NSE_EQ|{OLD_AAA}", f"NSE_EQ|{NEW_AAA}"])
        tlm.assert_called_once_with(refresh=True)

    def test_no_retry_when_isin_unchanged(self):
        same = {"by_symbol": {"AAA": OLD_AAA}, "by_isin": {OLD_AAA: "AAA"}}
        client = _Client400(bad_key=f"NSE_EQ|{OLD_AAA}")
        with mock.patch.object(ir, "try_load_master", return_value=(same, "")):
            with self.assertRaises(UpstoxError) as ctx:
                self._pull(client)
        self.assertEqual(client.keys, [f"NSE_EQ|{OLD_AAA}"])
        self.assertIn("HTTP 400", str(ctx.exception))

    def test_refresh_failure_raises_original_400(self):
        client = _Client400(bad_key=f"NSE_EQ|{OLD_AAA}")
        with mock.patch.object(ir, "try_load_master", return_value=(None, "RuntimeError: down")):
            with self.assertRaises(UpstoxError) as ctx:
                self._pull(client)
        self.assertEqual(client.keys, [f"NSE_EQ|{OLD_AAA}"])
        self.assertIn("HTTP 400 from https://api.example", str(ctx.exception))

    def test_no_master_lookup_for_other_status_codes(self):
        client = _Client400(bad_key=f"NSE_EQ|{OLD_AAA}", status=500)
        with mock.patch.object(ir, "try_load_master") as tlm:
            with self.assertRaises(UpstoxError):
                self._pull(client)
        tlm.assert_not_called()
        self.assertEqual(client.keys, [f"NSE_EQ|{OLD_AAA}"])


class LoadMasterRefreshTests(unittest.TestCase):
    def test_refresh_downloads_even_with_fresh_cache(self):
        rows = [{"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "AAA", "isin": NEW_AAA}]
        raw = gzip.compress(json.dumps(rows).encode("utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "master.json.gz"
            cache.write_bytes(gzip.compress(b"[]"))  # fresh, but stale content
            with mock.patch.object(ir, "_download", return_value=raw) as dl:
                master = ir.load_master(cache_path=cache, refresh=True)
        dl.assert_called_once()
        self.assertEqual(master["by_symbol"], {"AAA": NEW_AAA})


class DescribeChangeTests(unittest.TestCase):
    def test_isin_change_and_rename_lines(self):
        changed = ir.Resolution("AAA", NEW_AAA, changed=True)
        self.assertEqual(ir.describe_change("AAA", OLD_AAA, changed), f"AAA: ISIN {OLD_AAA} -> {NEW_AAA}")
        renamed = ir.Resolution("NEWNAME", OLD_AAA, changed=True, renamed_from="AAA")
        self.assertEqual(ir.describe_change("AAA", OLD_AAA, renamed),
                         f"AAA -> NEWNAME: renamed, ISIN {OLD_AAA}")


if __name__ == "__main__":
    unittest.main()
