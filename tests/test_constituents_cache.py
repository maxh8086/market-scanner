"""Offline tests for the constituent cache age check in scanner/constituents.py.

No network: _download is patched and CACHE_PATH points into a temp directory.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scanner import constituents as cons

CSV_TEXT = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Infosys Ltd,IT,INFY,EQ,INE009A01021\n"
    "DUMMY ROW,NA,DUMMYX,EQ,INE000000000\n"
)


def _set_age_days(path: Path, days: float) -> None:
    ts = time.time() - days * 86400
    os.utime(path, (ts, ts))


class ConstituentsCacheAgeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "ind_niftytotalmarket_list.csv"
        self.cache.write_text(CSV_TEXT, encoding="utf-8")
        self._patch = mock.patch.object(cons, "CACHE_PATH", self.cache)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_fresh_cache_is_read_and_not_downloaded(self):
        _set_age_days(self.cache, 1)
        with mock.patch.object(cons, "_download", side_effect=AssertionError("should not download")) as dl:
            df = cons.load_constituents()
        dl.assert_not_called()
        self.assertEqual(list(df["Symbol"]), ["INFY"])

    def test_cache_older_than_max_age_triggers_download(self):
        _set_age_days(self.cache, 40)
        with mock.patch.object(cons, "_download", return_value=CSV_TEXT.encode("utf-8")) as dl:
            df = cons.load_constituents()
        dl.assert_called_once_with(cons.PRIMARY_URL)
        self.assertEqual(list(df["Symbol"]), ["INFY"])

    def test_both_downloads_fail_returns_stale_cache(self):
        _set_age_days(self.cache, 40)
        with mock.patch.object(cons, "_download", side_effect=OSError("network down")) as dl:
            df = cons.load_constituents()
        self.assertEqual(dl.call_count, 2)
        self.assertEqual(list(df["Symbol"]), ["INFY"])


if __name__ == "__main__":
    unittest.main()
