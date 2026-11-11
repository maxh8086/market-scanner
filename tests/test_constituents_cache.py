"""Offline tests for scanner/constituents.py after the move to the database.

No network and no database: the index read is patched, and override_path reads a temp file.
(The old download and 30-day cache were removed; this file replaces the cache-age tests.)
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scanner import company_reference as cr
from scanner import constituents as cons

CSV_TEXT = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Infosys Ltd,IT,INFY,EQ,INE009A01021\n"
    "DUMMY ROW,NA,DUMMYX,EQ,INE000000000\n"
)

DB_RECORDS = [
    {"Symbol": "INFY", "ISIN Code": "INE009A01021", "Company Name": "Infosys Ltd",
     "Industry": "IT", "Series": "EQ"},
]


class _FakeConnCM:
    """Stands in for scanner.pg.db.connect(): a context manager that yields a marker object."""

    def __init__(self):
        self.conn = object()

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


class LoadConstituentsTests(unittest.TestCase):
    def test_reads_named_index_from_database(self):
        fake = _FakeConnCM()
        with mock.patch("scanner.pg.db.connect", return_value=fake), \
             mock.patch.object(cr, "load_index_constituents", return_value=DB_RECORDS) as load:
            df = cons.load_constituents(index_name="NIFTY TOTAL MARKET")
        load.assert_called_once_with(fake.conn, "NIFTY TOTAL MARKET")
        self.assertEqual(list(df["Symbol"]), ["INFY"])
        self.assertEqual(list(df.columns), ["Company Name", "Industry", "Symbol", "Series", "ISIN Code"])

    def test_default_index_is_nifty_total_market(self):
        self.assertEqual(cons.DEFAULT_INDEX, "NIFTY TOTAL MARKET")
        with mock.patch("scanner.pg.db.connect", return_value=_FakeConnCM()), \
             mock.patch.object(cr, "load_index_constituents", return_value=DB_RECORDS) as load:
            cons.load_constituents()
        self.assertEqual(load.call_args[0][1], "NIFTY TOTAL MARKET")

    def test_empty_index_error_propagates(self):
        with mock.patch("scanner.pg.db.connect", return_value=_FakeConnCM()), \
             mock.patch.object(cr, "load_index_constituents",
                               side_effect=RuntimeError("index 'X' has no constituents in the database")):
            with self.assertRaises(RuntimeError):
                cons.load_constituents(index_name="X")

    def test_override_path_reads_file_and_drops_dummy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local.csv"
            path.write_text(CSV_TEXT, encoding="utf-8")
            with mock.patch("scanner.pg.db.connect", side_effect=AssertionError("no database")) as dbc:
                df = cons.load_constituents(override_path=str(path))
        dbc.assert_not_called()
        self.assertEqual(list(df["Symbol"]), ["INFY"])


if __name__ == "__main__":
    unittest.main()
