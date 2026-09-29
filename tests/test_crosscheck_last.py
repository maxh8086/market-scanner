"""A scan LTP may match NSE's last traded price OR its close; only neither is a divergence.

Found on the real 2026-09-28 file: 14 scan prices "diverged" by up to 1.6% from
NSE's CLOSE_PRICE (a 30-minute VWAP) and every one matched LAST_PRICE exactly.
"""
import shutil
import tempfile
import unittest
from datetime import date
from unittest import mock

import pandas as pd

from scanner.crosscheck import NseBhavcopy, compare
from tests.test_crosscheck_nse import REAL, _Resp

ON = date(2026, 9, 28)


class TestLastPrice(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _verdicts(self, ltps):
        scan = pd.DataFrame({"symbol": list(ltps), "ltp": list(ltps.values())})
        src = NseBhavcopy(cache_dir=self.dir)
        with mock.patch("scanner.crosscheck.requests.get", return_value=_Resp(REAL)):
            out = compare(scan, src, ON, tol_pct=0.5)
        return dict(zip(out.symbol, out.verdict))

    def test_parser_keeps_last_price(self):
        day = NseBhavcopy(cache_dir=self.dir)._parse_bhavcopy_csv(REAL)
        self.assertEqual(day["20MICRONS"].last, 212.03)
        self.assertEqual(day["20MICRONS"].close, 212.94)

    def test_matching_last_but_not_close_is_ok(self):
        # 212.03 is the last trade; close is 212.94 (0.43% away, so make it clearly outside)
        v = self._verdicts({"21STCENMGM": 39.70})   # last 39.70, close 39.64
        self.assertEqual(v["21STCENMGM"], "OK")

    def test_matching_neither_is_diverged(self):
        v = self._verdicts({"21STCENMGM": 45.00})
        self.assertEqual(v["21STCENMGM"], "DIVERGED")

    def test_last_survives_the_disk_cache(self):
        with mock.patch("scanner.crosscheck.requests.get", return_value=_Resp(REAL)):
            NseBhavcopy(cache_dir=self.dir).close_on("20MICRONS", ON)
        fresh = NseBhavcopy(cache_dir=self.dir)
        self.assertEqual(fresh.last_on("20MICRONS", ON), 212.03)


if __name__ == "__main__":
    unittest.main()
