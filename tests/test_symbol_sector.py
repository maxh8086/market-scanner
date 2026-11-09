"""Tests for scanner/symbol_sector.py. Offline: uses temporary CSV files and no database."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from scanner import symbol_sector as ss

HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"


def _write(text: str) -> Path:
    d = tempfile.mkdtemp()
    p = Path(d) / "list.csv"
    p.write_text(text, encoding="utf-8")
    return p


class ParseCsvTests(unittest.TestCase):
    def test_reads_symbol_isin_and_industry(self):
        p = _write(HEADER + "ABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022\n")
        self.assertEqual(ss.parse_csv(p), [("ABB", "INE117A01022", "Capital Goods")])

    def test_skips_dummy_rows(self):
        p = _write(HEADER + "Dummy,Capital Goods,DUMMYABC,EQ,INE000000009\n"
                           "ABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022\n")
        self.assertEqual([r[0] for r in ss.parse_csv(p)], ["ABB"])

    def test_missing_header_is_rejected(self):
        p = _write("Company Name,Symbol,Series,ISIN Code\nA,AAA,EQ,INE000000001\n")
        with self.assertRaises(ss.BadCsv):
            ss.parse_csv(p)

    def test_blank_industry_is_rejected(self):
        p = _write(HEADER + "A,,AAA,EQ,INE000000001\n")
        with self.assertRaises(ss.BadCsv):
            ss.parse_csv(p)

    def test_duplicate_symbol_is_rejected(self):
        p = _write(HEADER + "A,X,AAA,EQ,INE000000001\nB,X,AAA,EQ,INE000000002\n")
        with self.assertRaises(ss.BadCsv):
            ss.parse_csv(p)

    def test_duplicate_isin_is_rejected(self):
        p = _write(HEADER + "A,X,AAA,EQ,INE000000001\nB,X,BBB,EQ,INE000000001\n")
        with self.assertRaises(ss.BadCsv):
            ss.parse_csv(p)

    def test_empty_file_is_rejected(self):
        p = _write(HEADER)
        with self.assertRaises(ss.BadCsv):
            ss.parse_csv(p)


class TodayIstTests(unittest.TestCase):
    def test_utc_evening_is_next_day_in_ist(self):
        utc_evening = dt.datetime(2026, 11, 8, 20, 0, tzinfo=dt.timezone.utc)  # 01:30 IST on 9 Nov
        self.assertEqual(ss.today_ist(utc_evening), dt.date(2026, 11, 9))

    def test_ist_morning_stays_on_same_date(self):
        ist_morning = dt.datetime(2026, 11, 9, 1, 0, tzinfo=ss.IST)
        self.assertEqual(ss.today_ist(ist_morning), dt.date(2026, 11, 9))


class UpsertSqlTests(unittest.TestCase):
    def test_upsert_never_writes_user_mapping_columns(self):
        # The re-run safety guarantee: the NSE loader must not name sub_sector columns.
        self.assertNotIn("sub_sector", ss.UPSERT_SQL)

    def test_upsert_conflicts_on_symbol(self):
        self.assertIn("ON CONFLICT (symbol)", ss.UPSERT_SQL)


if __name__ == "__main__":
    unittest.main()
