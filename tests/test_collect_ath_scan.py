"""Offline tests for the ath_scan collector source. ath_scan.main() is stubbed and the candidate
table is faked; nothing is fetched and no database is needed."""
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import pytz

from scanner import ath_scan_store
from scanner.collect import sources

NOW = datetime(2026, 11, 8, 10, 0, 0, tzinfo=pytz.UTC)
SCAN_DATE = date(2026, 11, 8)


def _stub_ath_scan(code=0):
    """A fake ath_scan module. main() records its argv and returns code."""
    calls = []
    module = types.ModuleType("ath_scan")

    def main():
        calls.append(list(sys.argv))
        return code

    module.main = main
    module.calls = calls
    return module


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class AthScanSourceTests(unittest.TestCase):

    def _use(self, stub):
        # Set the stub directly. mock.patch.dict(sys.modules) would drop numpy/pandas on exit.
        sys.modules["ath_scan"] = stub
        self.addCleanup(sys.modules.pop, "ath_scan", None)

    def _table(self, scan_date=SCAN_DATE, rows=0):
        """Fake the candidate table: the newest scan date and its row count."""
        patches = [
            mock.patch.object(ath_scan_store, "connect", return_value=_FakeConnection()),
            mock.patch.object(ath_scan_store, "latest_scan_date", return_value=scan_date),
            mock.patch.object(ath_scan_store, "scan_row_count", return_value=rows),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return ath_scan_store

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_registered_as_collector_source(self):
        self.assertIn("ath_scan", sources.SOURCES)
        self.assertIsInstance(sources.SOURCES["ath_scan"], sources.AthScan)

    def test_run_calls_scan_with_no_export_and_reports_rows(self):
        stub = _stub_ath_scan(code=0)
        self._use(stub)
        self._table(rows=2)
        result = sources.AthScan().run({}, NOW)
        self.assertEqual(stub.calls, [["ath_scan.py", "--no-export"]])
        self.assertEqual(result["fetched"], 2)
        self.assertEqual(result["new"], 2)
        self.assertIsNone(result["from"])
        self.assertIsNone(result["to"])
        self.assertEqual(result["message"], "wrote 2 candidates for 2026-11-08")

    def test_run_writes_no_output_directory(self):
        stub = _stub_ath_scan(code=0)
        self._use(stub)
        self._table(rows=1)
        sources.AthScan().run({}, NOW)
        self.assertFalse(Path("output").exists())

    def test_run_restores_argv(self):
        stub = _stub_ath_scan(code=0)
        self._use(stub)
        self._table(rows=1)
        before = list(sys.argv)
        sources.AthScan().run({}, NOW)
        self.assertEqual(sys.argv, before)

    def test_nonzero_exit_raises_so_run_is_failed(self):
        stub = _stub_ath_scan(code=3)
        self._use(stub)
        self._table(rows=5)
        with self.assertRaisesRegex(RuntimeError, "exited with code 3"):
            sources.AthScan().run({}, NOW)

    def test_zero_rows_raises(self):
        stub = _stub_ath_scan(code=0)
        self._use(stub)
        self._table(rows=0)
        with self.assertRaisesRegex(RuntimeError, "zero candidates"):
            sources.AthScan().run({}, NOW)

    def test_no_scan_date_raises(self):
        stub = _stub_ath_scan(code=0)
        self._use(stub)
        self._table(scan_date=None, rows=0)
        with self.assertRaisesRegex(RuntimeError, "zero candidates"):
            sources.AthScan().run({}, NOW)

    def test_dry_run_does_not_call_scan_or_touch_table(self):
        stub = _stub_ath_scan(code=0)
        self._use(stub)
        table = self._table(rows=1)
        with mock.patch.object(table, "scan_row_count") as count:
            result = sources.AthScan().run({}, NOW, dry_run=True)
        self.assertEqual(stub.calls, [])
        count.assert_not_called()
        self.assertEqual(result["fetched"], 0)
        self.assertIn("dry-run", result["message"])


if __name__ == "__main__":
    unittest.main()
