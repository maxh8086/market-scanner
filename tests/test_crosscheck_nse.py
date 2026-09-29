"""NseBhavcopy against the real file layout, and its request discipline.

The first version of this parser was written against an invented layout and
returned zero rows on NSE's actual file, which turned every symbol into a fresh
HTTP request. These tests pin the real layout and the request count.
"""
import shutil
import tempfile
import unittest
from datetime import date
from unittest import mock

from scanner.crosscheck import NseBhavcopy

# Verbatim shape of sec_bhavdata_full_DDMMYYYY.csv: padded headers, padded
# values, *_PRICE column names, DATE1 as DD-Mon-YYYY, mixed series.
REAL = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, "
    "LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, "
    "NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
    "20MICRONS, EQ, 28-Sep-2026, 217.58, 218.66, 220.80, 212.01, 212.03, "
    "212.94, 214.40, 65358, 140.13, 2034, 30278, 46.33\n"
    "21STCENMGM, EQ, 28-Sep-2026, 39.87, 40.27, 40.27, 39.10, 39.70, "
    "39.64, 39.43, 5424, 2.14, 40, 5345, 98.54\n"
    "ABCBOND, N1, 28-Sep-2026, 1000, 1001, 1002, 999, 1000, 1001, 1000, 1, 1, 1, -, -\n"
)


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class TestRealLayout(unittest.TestCase):
    def test_parses_padded_real_file(self):
        day = NseBhavcopy(cache_dir=tempfile.mkdtemp())._parse_bhavcopy_csv(REAL)
        self.assertEqual(sorted(day), ["20MICRONS", "21STCENMGM"])   # N1 dropped
        s = day["20MICRONS"]
        self.assertEqual((s.open, s.high, s.low, s.close), (218.66, 220.80, 212.01, 212.94))
        self.assertEqual(s.date, date(2026, 9, 28))


class TestRequestDiscipline(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_one_request_serves_every_symbol(self):
        src = NseBhavcopy(cache_dir=self.dir)
        with mock.patch("scanner.crosscheck.requests.get", return_value=_Resp(REAL)) as g:
            a = src.close_on("20MICRONS", date(2026, 9, 28))
            b = src.close_on("21STCENMGM", date(2026, 9, 28))
            c = src.close_on("NOSUCH", date(2026, 9, 28))
        self.assertEqual((a, b, c), (212.94, 39.64, None))
        self.assertEqual(g.call_count, 1)

    def test_failed_day_is_not_refetched_per_symbol(self):
        src = NseBhavcopy(cache_dir=self.dir)
        with mock.patch("scanner.crosscheck.requests.get",
                        side_effect=OSError("down")) as g:
            for sym in ("A", "B", "C", "D"):
                self.assertIsNone(src.close_on(sym, date(2026, 9, 28)))
        self.assertEqual(g.call_count, 1)

    def test_weekend_makes_no_request(self):
        src = NseBhavcopy(cache_dir=self.dir)
        with mock.patch("scanner.crosscheck.requests.get") as g:
            self.assertIsNone(src.close_on("A", date(2026, 9, 27)))   # Sunday
        g.assert_not_called()

    def test_disk_cache_means_no_request_on_a_new_instance(self):
        with mock.patch("scanner.crosscheck.requests.get", return_value=_Resp(REAL)):
            NseBhavcopy(cache_dir=self.dir).close_on("20MICRONS", date(2026, 9, 28))
        with mock.patch("scanner.crosscheck.requests.get") as g:
            self.assertEqual(
                NseBhavcopy(cache_dir=self.dir).close_on("20MICRONS", date(2026, 9, 28)), 212.94)
        g.assert_not_called()

    def test_high_between_is_bounded(self):
        src = NseBhavcopy(cache_dir=self.dir)
        with mock.patch("scanner.crosscheck.requests.get", side_effect=OSError("down")) as g:
            src.high_between("A", date(1990, 1, 1), date(2026, 9, 28))
        # 90 calendar days is at most ~65 weekdays, never the ~9,000 since 1990.
        self.assertLessEqual(g.call_count, 70)


if __name__ == "__main__":
    unittest.main()
