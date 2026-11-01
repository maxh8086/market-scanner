"""A scan with nothing in range is a result, not an error."""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import enrich
import record_run

HEADER = "symbol,company,industry,ltp,ath_high,distance_pct,bucket\n"


class _Db:
    def close(self):
        pass


class EmptyScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _scan(self, body=""):
        p = self.tmp / "ath_scan_2026-09-30.csv"
        p.write_text(HEADER + body, encoding="utf-8")
        return p

    def test_enrich_exits_cleanly_with_a_clear_message(self):
        scan = self._scan()
        out = io.StringIO()
        with mock.patch.object(enrich.docstore, "open_db", return_value=_Db()), \
             mock.patch.object(sys, "argv", ["enrich.py", "--all", "--scan", str(scan)]), \
             mock.patch.object(enrich, "stage_filings") as filings, \
             mock.patch.object(enrich, "stage_fundamentals") as fundamentals, \
             redirect_stdout(out):
            enrich.main()          # returns, no SystemExit, no ISIN complaint
        self.assertIn("nothing to enrich", out.getvalue())
        self.assertNotIn("isin", out.getvalue().lower())
        filings.assert_not_called()
        fundamentals.assert_not_called()

    def test_enrich_still_runs_when_there_are_rows(self):
        scan = self._scan("INFY,Infosys,IT,1500,1600,6.2,5-15%\n")
        with mock.patch.object(enrich.docstore, "open_db", return_value=_Db()), \
             mock.patch.object(sys, "argv", ["enrich.py", "--filings", "--scan", str(scan)]), \
             mock.patch.object(enrich, "stage_filings") as filings, \
             redirect_stdout(io.StringIO()):
            enrich.main()
        filings.assert_called_once()

    def test_scan_is_empty_detection(self):
        self.assertTrue(record_run._scan_is_empty(self._scan()))
        self.assertFalse(record_run._scan_is_empty(self._scan("INFY,Infosys,IT,1500,1600,6.2,5-15%\n")))
        self.assertFalse(record_run._scan_is_empty(self.tmp / "missing.csv"))


if __name__ == "__main__":
    unittest.main()
