"""Offline tests for scanner/constituent_membership.py. No database is contacted."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scanner import constituent_membership as cm

GOOD = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Alpha Ltd.,Services,ALPHA,EQ,INE000A01010\n"
    "Beta Ltd.,Metals,BETA,EQ,INE000B01020\n"
)


class ParseCsvTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_parses_symbol_and_isin(self):
        path = self._write("nifty_bank.csv", GOOD)
        self.assertEqual(
            cm.parse_csv(path),
            [("INE000A01010", "ALPHA"), ("INE000B01020", "BETA")],
        )

    def test_bom_header_is_accepted(self):
        path = self._write("nifty_bank.csv", "﻿" + GOOD)
        self.assertEqual(len(cm.parse_csv(path)), 2)

    def test_header_without_symbol_or_isin_is_rejected(self):
        path = self._write("nifty_bank.csv", "Company Name,Industry,Series\nA,B,EQ\n")
        with self.assertRaises(cm.BadCsv) as ctx:
            cm.parse_csv(path)
        self.assertIn("Symbol", str(ctx.exception))

    def test_header_with_only_symbol_is_rejected(self):
        path = self._write("nifty_bank.csv", "Symbol,Series\nALPHA,EQ\n")
        with self.assertRaises(cm.BadCsv):
            cm.parse_csv(path)

    def test_zero_data_rows_is_rejected(self):
        path = self._write("nifty_bank.csv", "Company Name,Industry,Symbol,Series,ISIN Code\n")
        with self.assertRaises(cm.BadCsv) as ctx:
            cm.parse_csv(path)
        self.assertIn("zero data rows", str(ctx.exception))

    def test_duplicate_isin_is_rejected(self):
        dup = GOOD + "Gamma Ltd.,Services,GAMMA,EQ,INE000A01010\n"
        path = self._write("nifty_bank.csv", dup)
        with self.assertRaises(cm.BadCsv):
            cm.parse_csv(path)

    def test_load_all_fails_whole_when_one_file_is_bad(self):
        self._write("nifty_bank.csv", GOOD)
        self._write("nifty_50.csv", "Foo,Bar\n1,2\n")
        with self.assertRaises(cm.BadCsv):
            cm.load_all(self.dir)

    def test_load_all_maps_slugs_to_index_names(self):
        self._write("nifty_bank.csv", GOOD)
        data = cm.load_all(self.dir)
        self.assertEqual(set(data), {"NIFTY BANK"})
        self.assertEqual(len(data["NIFTY BANK"]), 2)


class MainDryRunTests(unittest.TestCase):
    def test_dry_run_does_not_connect_to_database(self):
        data = {"NIFTY BANK": [("INE000A01010", "ALPHA")]}
        with mock.patch.object(cm, "load_all", return_value=data), \
                mock.patch("scanner.pg.db.connect") as connect:
            code = cm.main(["--dry-run"])
        self.assertEqual(code, 0)
        connect.assert_not_called()

    def test_bad_csv_exits_1_without_connecting(self):
        with mock.patch.object(cm, "load_all", side_effect=cm.BadCsv("bad")), \
                mock.patch("scanner.pg.db.connect") as connect:
            code = cm.main([])
        self.assertEqual(code, 1)
        connect.assert_not_called()


class WriteRowsTests(unittest.TestCase):
    def test_upsert_never_deletes_and_keeps_as_of(self):
        data = {"NIFTY BANK": [("INE000A01010", "ALPHA"), ("INE000B01020", "BETA")]}
        as_of = dt.date(2026, 11, 8)
        cur = mock.MagicMock()
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cur
        with mock.patch("scanner.pg.db.connect", return_value=conn):
            sent = cm.write_rows(data, as_of)
        self.assertEqual(sent, 2)
        sql, params = cur.executemany.call_args[0]
        self.assertIn("ON CONFLICT (index_name, isin, as_of)", sql)
        self.assertIn("DO UPDATE SET symbol = EXCLUDED.symbol", sql)
        self.assertNotIn("DELETE", sql.upper())
        self.assertNotIn("index_membership", sql)
        self.assertEqual(params[0], ("NIFTY BANK", "INE000A01010", "ALPHA", as_of))


def _db_conn(rows):
    """A psycopg-like connection whose execute(...).fetchall() returns rows."""
    conn = mock.MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = rows
    return conn


# Tuple order matches load_index_constituents: symbol, isin, company_name, industry, series.
DB_ROWS = [
    ("ALPHA", "INE000A01010", "Alpha Ltd.", "Services", "EQ"),
    ("BETA", "INE000B01020", "Beta Ltd.", "Metals", "EQ"),
]


class MembershipFromDatabaseTests(unittest.TestCase):
    def test_membership_reads_database_rows(self):
        conn = _db_conn(DB_ROWS)
        with mock.patch("scanner.pg.db.connect", return_value=conn), \
                mock.patch.object(cm, "load_all") as csv_reader:
            data = cm.build_membership_from_db(["NIFTY BANK"])
        self.assertEqual(
            data,
            {"NIFTY BANK": [("INE000A01010", "ALPHA"), ("INE000B01020", "BETA")]},
        )
        csv_reader.assert_not_called()
        self.assertEqual(conn.execute.call_args[0][1], ("NIFTY BANK",))

    def test_zero_rows_raises(self):
        conn = _db_conn([])
        with mock.patch("scanner.pg.db.connect", return_value=conn):
            with self.assertRaises(RuntimeError):
                cm.build_membership_from_db(["NIFTY BANK"])
        conn.cursor.assert_not_called()

    def test_csv_reader_kept_as_rollback(self):
        path = mock.Mock(spec=Path)
        path.read_text.return_value = GOOD
        self.assertEqual(
            cm.parse_csv(path),
            [("INE000A01010", "ALPHA"), ("INE000B01020", "BETA")],
        )

    def test_each_index_name_round_trips(self):
        # INDEX_NAMES is the single name list planned in MT1 (scanner/index_sources.py).
        from scanner.index_sources import INDEX_NAMES

        self.assertEqual(len(INDEX_NAMES), 7)
        as_of = dt.date(2026, 11, 13)
        for name in INDEX_NAMES:
            with self.subTest(index=name):
                cur = mock.MagicMock()
                write_conn = mock.MagicMock()
                write_conn.__enter__.return_value = write_conn
                write_conn.cursor.return_value.__enter__.return_value = cur
                with mock.patch("scanner.pg.db.connect", return_value=write_conn):
                    cm.write_rows({name: [("INE000A01010", "ALPHA")]}, as_of)
                written = cur.executemany.call_args[0][1][0][0]

                read_conn = _db_conn([("ALPHA", "INE000A01010", "Alpha Ltd.", "Services", "EQ")])
                with mock.patch("scanner.pg.db.connect", return_value=read_conn):
                    membership = cm.build_membership_from_db([written])

                self.assertEqual(written, name)
                self.assertEqual(read_conn.execute.call_args[0][1], (name,))
                self.assertEqual(list(membership), [name])
                self.assertEqual(membership[name], [("INE000A01010", "ALPHA")])


if __name__ == "__main__":
    unittest.main()
