"""A scan with nothing in range is a result, not an error.

The scan comes from ath_scan_candidates. The table is faked here: a read returns the newest scan
(frame, date), or None when the table has no rows. A --scan CSV that a person supplies is the
one place a CSV is still read; its empty-file case is kept below.
"""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

import enrich
import record_run
from scanner import ath_scan_store

HEADER = "symbol,company,industry,ltp,ath_high,distance_pct,bucket\n"
SCAN_DAY = date(2026, 9, 30)


class _Db:
    def close(self):
        pass


class _Conn:
    """Stands in for the connection from ath_scan_store.connect(): a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _table_frame():
    return pd.DataFrame([
        {"symbol": "INFY", "company": "Infosys", "industry": "IT", "isin": "INE009A01021",
         "ltp": 1500.0, "ath_high": 1600.0, "distance_pct": 6.2, "bucket": "5-15%"},
    ])


class _TableMixin:
    def _table(self, found):
        """Fake the candidate table: found is (frame, date) or None (no rows)."""
        patches = [
            mock.patch.object(ath_scan_store, "connect", return_value=_Conn()),
            mock.patch.object(ath_scan_store, "read_latest_scan", return_value=found),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class EnrichScanSourceTests(_TableMixin, unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _scan(self, body=""):
        p = self.tmp / "ath_scan_2026-09-30.csv"
        p.write_text(HEADER + body, encoding="utf-8")
        return p

    def test_enrich_exits_cleanly_with_a_clear_message(self):
        # A manual --scan CSV with no rows: the existing message, no ISIN complaint.
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

    def test_no_scan_flag_reads_the_table_and_dates_by_scan_date(self):
        self._table((_table_frame(), SCAN_DAY))
        out = io.StringIO()
        with mock.patch.object(enrich.docstore, "open_db", return_value=_Db()), \
             mock.patch.object(sys, "argv", ["enrich.py", "--filings"]), \
             mock.patch.object(enrich, "stage_filings") as filings, \
             mock.patch.object(enrich, "stage_report") as report, \
             redirect_stdout(out):
            enrich.main()
        self.assertIn("ath_scan_candidates 2026-09-30", out.getvalue())
        filings.assert_called_once()
        self.assertEqual(list(filings.call_args.args[1]["symbol"]), ["INFY"])
        report.assert_not_called()

    def test_report_stage_gets_the_scan_date_as_its_stem(self):
        self._table((_table_frame(), SCAN_DAY))
        with mock.patch.object(enrich.docstore, "open_db", return_value=_Db()), \
             mock.patch.object(sys, "argv", ["enrich.py", "--report", "--no-forecast"]), \
             mock.patch.object(enrich, "stage_report") as report, \
             redirect_stdout(io.StringIO()):
            enrich.main()
        self.assertEqual(report.call_args.args[2], "2026-09-30")

    def test_empty_table_says_run_ath_scan_first(self):
        self._table(None)
        with mock.patch.object(sys, "argv", ["enrich.py", "--filings"]), \
             mock.patch.object(enrich.docstore, "open_db", return_value=_Db()), \
             redirect_stdout(io.StringIO()), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            with self.assertRaises(SystemExit):
                enrich.main()
        self.assertIn("no scan in ath_scan_candidates -- run ath_scan.py first, or pass --scan",
                      err.getvalue())


class RecordRunEmptyScanTests(_TableMixin, unittest.TestCase):
    RUN = "6f1c2a4e-9b1d-4c3e-8f5a-1234567890ab"

    def _argv(self, *extra):
        return ["--run-id", self.RUN, "--date", "2026-09-30", *extra]

    def _run(self, rows, *extra):
        """Run record_run.main with the table reporting rows for the run date."""
        finish = mock.Mock(return_value=0)
        with mock.patch.object(record_run.db, "available", return_value=True), \
             mock.patch("scanner.pg.migrate.apply"), \
             mock.patch.object(ath_scan_store, "connect", return_value=_Conn()), \
             mock.patch.object(ath_scan_store, "scan_row_count", return_value=rows) as count, \
             mock.patch.object(record_run, "_finish", finish), \
             redirect_stdout(io.StringIO()) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            code = record_run.main(self._argv(*extra))
        return code, finish, count, out.getvalue()

    def test_no_candidate_rows_for_the_day_records_an_empty_run(self):
        code, finish, count, out = self._run(0)
        self.assertEqual(code, 0)
        count.assert_called_once()
        self.assertEqual(count.call_args.args[1], date(2026, 9, 30))
        self.assertIn("has no stocks in range: recording an empty run", out)
        finish.assert_called_once()
        self.assertEqual(finish.call_args.kwargs.get("status"), "complete")

    def test_candidate_rows_go_on_to_the_enriched_file(self):
        enriched = Path(tempfile.mkdtemp()) / "ath_enriched_2026-09-30.csv"
        enriched.write_text("symbol\nINFY\n", encoding="utf-8")
        code, finish, _, out = self._run(3, "--enriched", str(enriched))
        self.assertEqual(code, 0)
        self.assertNotIn("recording an empty run", out)
        finish.assert_called_once()
        self.assertEqual(list(finish.call_args.args[1]["symbol"]), ["INFY"])


if __name__ == "__main__":
    unittest.main()
