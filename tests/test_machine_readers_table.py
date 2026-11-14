"""The machine readers take the scan from ath_scan_candidates and get the candidates the CSV gave.

The table is faked: a read returns (frame, scan_date), or None when the table has no rows.
Frames come from the store test fixture, so the table-read frame and the CSV-read frame are
compared on the same candidates.
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import pandas as pd
import pytz

import crosscheck
import enrich
from scanner import ath_scan_store as store
from scanner.collect import sources
from scanner import docstore
from scanner.pg import db as pgdb
from tests.test_ath_scan_store import _FakeConn, _as_rows, _captured_records, _frame

NOW = datetime(2026, 11, 8, 10, 0, 0, tzinfo=pytz.UTC)
SCAN_DAY = date(2026, 9, 30)


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _TableMixin:
    def _table(self, found):
        """Fake the candidate table: found is (frame, date) or None."""
        patches = [
            mock.patch.object(store, "connect", return_value=_Conn()),
            mock.patch.object(store, "read_latest_scan", return_value=found),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


def _candidates():
    """The store fixture's frame, as a reader gets it back: NA and INFY, sorted."""
    frame, _ = store.read_latest_scan(_FakeConn(latest=SCAN_DAY, rows=_as_rows(_captured_records(_frame()))))
    return frame


class FilingsTableTests(_TableMixin, unittest.TestCase):

    def test_no_rows_skips_with_the_table_message(self):
        self._table(None)
        result = sources.Filings().run({}, NOW)
        self.assertEqual(result["message"], "skipped: no ath_scan_candidates rows")
        self.assertEqual(result["fetched"], 0)

    def test_passes_the_table_frame_with_isin_and_symbol_to_candidate_filings(self):
        self._table((_candidates(), SCAN_DAY))
        with mock.patch.object(docstore, "open_db"), \
             mock.patch.object(enrich, "_candidate_filings", return_value=([], {})) as cand:
            result = sources.Filings().run({}, NOW)
        frame = cand.call_args.args[0]
        self.assertEqual(list(frame["symbol"]), ["INFY", "NA"])
        self.assertEqual(list(frame["isin"]), ["", "INE000000001"])
        self.assertIn("all 0 candidates already fetched", result["message"])


class FundamentalsTableTests(_TableMixin, unittest.TestCase):

    def test_no_rows_skips_with_the_table_message(self):
        self._table(None)
        result = sources.Fundamentals().run({}, NOW)
        self.assertEqual(result["message"], "skipped: no ath_scan_candidates rows")

    def test_symbols_come_from_the_table(self):
        self._table((_candidates(), SCAN_DAY))
        with mock.patch.object(docstore, "open_db"), \
             mock.patch.object(docstore, "fundamentals_age_days", return_value=0) as age:
            result = sources.Fundamentals().run({}, NOW)
        self.assertEqual([c.args[1] for c in age.call_args_list], ["INFY", "NA"])
        self.assertEqual(result["message"], "skipped: all 2 symbols have fresh fundamentals")


class EnrichLatestScanTests(_TableMixin, unittest.TestCase):

    def test_table_scan_gives_frame_stem_and_label(self):
        self._table((_candidates(), SCAN_DAY))
        df, stem, label = enrich.latest_scan(None)
        self.assertEqual(stem, "2026-09-30")
        self.assertEqual(label, "ath_scan_candidates 2026-09-30")
        self.assertEqual(list(df["symbol"]), ["INFY", "NA"])

    def test_table_frame_is_not_refilled_with_isin(self):
        self._table((_candidates(), SCAN_DAY))
        with mock.patch.object(enrich, "_fill_isin") as fill:
            enrich.latest_scan(None)
        fill.assert_not_called()

    def test_empty_table_exits_with_the_run_ath_scan_message(self):
        self._table(None)
        err = io.StringIO()
        with mock.patch("sys.stderr", err), self.assertRaises(SystemExit):
            enrich.latest_scan(None)
        self.assertIn("no scan in ath_scan_candidates -- run ath_scan.py first, or pass --scan",
                      err.getvalue())


class CrosscheckTableTests(_TableMixin, unittest.TestCase):

    def test_find_latest_scan_gives_table_frame_and_date(self):
        self._table((_candidates(), SCAN_DAY))
        found = crosscheck.find_latest_scan()
        self.assertEqual(found[1], SCAN_DAY)
        self.assertEqual(list(found[0]["symbol"]), ["INFY", "NA"])

    def test_main_without_rows_exits_1(self):
        self._table(None)
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["crosscheck.py"]), mock.patch("sys.stdout", out):
            code = crosscheck.main()
        self.assertEqual(code, 1)
        self.assertIn("no scan in ath_scan_candidates", out.getvalue())


class PortfolioDtypeTests(unittest.TestCase):

    def test_boolean_text_columns_become_bool_only_when_all_values_are_boolean(self):
        frame = _candidates()
        out = store.as_csv_frame(frame)
        # INFY and NA: above_sma200 is 'False' and 'True' everywhere -> bool
        self.assertEqual(out["above_sma200"].dtype, bool)
        # above_ema50 has an empty cell, so read_csv would leave it text
        self.assertNotEqual(out["above_ema50"].dtype, bool)
        self.assertIn("", list(out["above_ema50"]))

    def test_as_csv_frame_matches_what_read_csv_gives(self):
        df = _frame()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "scan.csv"
        df.to_csv(path, index=False)
        csv = pd.read_csv(path, keep_default_na=False)
        table = store.as_csv_frame(_candidates())
        csv = csv.set_index("symbol").reindex(table["symbol"]).reset_index()
        for col in ("above_sma200", "above_ema50", "ath_date", "bucket"):
            self.assertEqual(table[col].dtype, csv[col].dtype, col)
            self.assertEqual(table[col].tolist(), csv[col].tolist(), col)


class SameCandidatesAsCsvTests(unittest.TestCase):

    def test_table_read_gives_the_candidates_the_csv_gave(self):
        df = _frame()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "scan.csv"
        df.to_csv(path, index=False)
        csv = pd.read_csv(path, keep_default_na=False).set_index("symbol")
        table = _candidates()
        self.assertEqual(sorted(table["symbol"]), sorted(csv.index))
        csv = csv.reindex(table["symbol"])
        for col in ("isin", "bucket", "ath_date", "company"):
            self.assertEqual(table[col].tolist(), csv[col].tolist(), col)
        self.assertEqual(table["ltp"].tolist(), csv["ltp"].astype(float).tolist())


class LatestCliTests(unittest.TestCase):

    def _run(self, argv, *, available=True, latest=SCAN_DAY, rows=2, connect_error=None):
        out, err = io.StringIO(), io.StringIO()
        patches = [
            mock.patch.object(pgdb, "available", return_value=available),
            mock.patch.object(store, "connect",
                              side_effect=connect_error, return_value=_Conn()),
            mock.patch.object(store, "latest_scan_date", return_value=latest),
            mock.patch.object(store, "scan_row_count", return_value=rows),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = store.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_prints_date_and_row_count_on_one_line(self):
        code, out, _ = self._run(["latest"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "2026-09-30 2\n")

    def test_no_rows_exits_2_with_empty_stdout(self):
        code, out, err = self._run(["latest"], latest=None, rows=0)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("no rows", err)

    def test_postgres_unreachable_exits_2_with_empty_stdout(self):
        code, out, err = self._run(["latest"], available=False)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err)

    def test_connection_error_exits_2_with_empty_stdout(self):
        code, out, err = self._run(["latest"], connect_error=OSError("refused"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("OSError", err)

    def test_unknown_command_exits_2(self):
        code, out, _ = self._run(["count"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
