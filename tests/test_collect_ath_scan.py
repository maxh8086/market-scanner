"""Offline tests for the ath_scan collector source. ath_scan.main() is stubbed; nothing is fetched."""
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path

import pytz

from scanner.collect import sources

NOW = datetime(2026, 11, 8, 10, 0, 0, tzinfo=pytz.UTC)


def _stub_ath_scan(code=0, write_rows=None):
    """A fake ath_scan module. main() writes a scan CSV (unless write_rows is None) and returns code."""
    calls = []
    module = types.ModuleType("ath_scan")

    def main():
        calls.append(list(sys.argv))
        if write_rows is not None:
            out = Path("output")
            out.mkdir(exist_ok=True)
            lines = ["Symbol,Close"] + [f"S{i},1.0" for i in range(write_rows)]
            (out / "ath_scan_2026-11-08.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return code

    module.main = main
    module.calls = calls
    return module


class AthScanSourceTests(unittest.TestCase):

    def _use(self, stub):
        # Set the stub directly. mock.patch.dict(sys.modules) would drop numpy/pandas on exit.
        sys.modules["ath_scan"] = stub
        self.addCleanup(sys.modules.pop, "ath_scan", None)

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

    def test_run_calls_scan_and_reports_rows(self):
        stub = _stub_ath_scan(code=0, write_rows=2)
        self._use(stub)
        result = sources.AthScan().run({}, NOW)
        self.assertEqual(stub.calls, [["ath_scan.py", "--output-dir", "output"]])
        self.assertEqual(result["fetched"], 2)
        self.assertEqual(result["new"], 2)
        self.assertIn("ath_scan_2026-11-08.csv", result["message"])

    def test_run_restores_argv(self):
        stub = _stub_ath_scan(code=0, write_rows=1)
        self._use(stub)
        before = list(sys.argv)
        sources.AthScan().run({}, NOW)
        self.assertEqual(sys.argv, before)

    def test_nonzero_exit_raises_so_run_is_failed(self):
        stub = _stub_ath_scan(code=3, write_rows=None)
        self._use(stub)
        with self.assertRaisesRegex(RuntimeError, "exited with code 3"):
            sources.AthScan().run({}, NOW)

    def test_success_without_output_raises(self):
        stub = _stub_ath_scan(code=0, write_rows=None)
        self._use(stub)
        with self.assertRaisesRegex(RuntimeError, "wrote no output"):
            sources.AthScan().run({}, NOW)

    def test_dry_run_does_not_call_scan(self):
        stub = _stub_ath_scan(code=0, write_rows=1)
        self._use(stub)
        result = sources.AthScan().run({}, NOW, dry_run=True)
        self.assertEqual(stub.calls, [])
        self.assertEqual(result["fetched"], 0)
        self.assertIn("dry-run", result["message"])


if __name__ == "__main__":
    unittest.main()
