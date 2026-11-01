"""Bhavcopy is unadjusted; the ATH window must stop at a split/bonus.

Found on the real 2026-09-28 data: PGIL and TDPOWERSYS (both 2:1) showed a
"recent high" double the scan's adjusted ATH, and the scan was right.
"""
import shutil
import tempfile
import unittest
from datetime import date

from scanner.crosscheck import NseBhavcopy, PriceSnapshot


def _src(days):
    """days: {date: (high, close)} placed straight into the in-memory day cache."""
    src = NseBhavcopy(cache_dir=tempfile.mkdtemp())
    for d, (high, close) in days.items():
        src._cache[d] = {"X": PriceSnapshot(d, close, high, close, close, close)}
    return src


class TestSplitAwareWindow(unittest.TestCase):
    def test_pre_split_highs_are_ignored(self):
        src = _src({
            date(2026, 9, 9): (2495.0, 2470.0),     # before a 2:1 split
            date(2026, 9, 10): (2378.4, 2378.4),
            date(2026, 9, 11): (1250.0, 1187.7),    # after: price halved
            date(2026, 9, 14): (1300.0, 1290.0),
        })
        self.assertEqual(src.high_between("X", date(2026, 9, 9), date(2026, 9, 14)), 1300.0)

    def test_ordinary_moves_do_not_truncate(self):
        src = _src({
            date(2026, 9, 9): (110.0, 100.0),
            date(2026, 9, 10): (125.0, 120.0),      # +20%: a circuit move, not a split
            date(2026, 9, 11): (130.0, 128.0),
        })
        self.assertEqual(src.high_between("X", date(2026, 9, 9), date(2026, 9, 11)), 130.0)

    def test_reverse_split_also_breaks_the_window(self):
        src = _src({
            date(2026, 9, 9): (10.0, 10.0),
            date(2026, 9, 10): (52.0, 50.0),        # 1:5 consolidation
        })
        self.assertEqual(src.high_between("X", date(2026, 9, 9), date(2026, 9, 10)), 52.0)


if __name__ == "__main__":
    unittest.main()
