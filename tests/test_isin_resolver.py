"""Offline tests for scanner.isin_resolver. No network and no database."""
import gzip
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from scanner import isin_resolver as ir

MASTER = {
    "by_symbol": {"CCAVENUE": "INE483S01038", "RELIANCE": "INE002A01018", "NEWNAME": "INEREN0100X"},
    "by_isin": {"INE483S01038": "CCAVENUE", "INE002A01018": "RELIANCE", "INEREN0100X": "NEWNAME"},
}


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))


def _master_rows():
    return [
        {"trading_symbol": "CCAVENUE", "isin": "INE483S01038", "segment": "NSE_EQ", "instrument_type": "EQ"},
        {"trading_symbol": "RELIANCE", "isin": "INE002A01018", "segment": "NSE_EQ", "instrument_type": "EQ"},
        {"trading_symbol": "NIFTY50", "isin": "INE999X01001", "segment": "NSE_INDEX", "instrument_type": "INDEX"},
        {"trading_symbol": "RELBOND", "isin": "INE002A08001", "segment": "NSE_EQ", "instrument_type": "BE"},
    ]


def _gz_bytes(rows):
    return gzip.compress(json.dumps(rows).encode("utf-8"))


class ResolveTests(unittest.TestCase):
    def test_unchanged_isin(self):
        r = ir.resolve("RELIANCE", "INE002A01018", MASTER)
        self.assertEqual((r.symbol, r.isin), ("RELIANCE", "INE002A01018"))
        self.assertFalse(r.changed)
        self.assertIsNone(r.renamed_from)
        self.assertTrue(r.resolved)

    def test_changed_isin_ccavenue(self):
        r = ir.resolve("CCAVENUE", "INE483S01020", MASTER)
        self.assertEqual(r.isin, "INE483S01038")
        self.assertTrue(r.changed)
        self.assertIsNone(r.renamed_from)
        self.assertIn("INE483S01020", r.reason)

    def test_rename_via_isin(self):
        r = ir.resolve("OLDNAME", "INEREN0100X", MASTER)
        self.assertEqual(r.symbol, "NEWNAME")
        self.assertEqual(r.isin, "INEREN0100X")
        self.assertEqual(r.renamed_from, "OLDNAME")
        self.assertTrue(r.changed)
        self.assertTrue(r.resolved)

    def test_unresolved_keeps_csv_values(self):
        r = ir.resolve("GHOST", "INE000000000", MASTER)
        self.assertEqual((r.symbol, r.isin), ("GHOST", "INE000000000"))
        self.assertFalse(r.changed)
        self.assertFalse(r.resolved)
        self.assertIn("not found in master", r.reason)

    def test_blank_isin_uses_master(self):
        r = ir.resolve("CCAVENUE", "", MASTER)
        self.assertEqual(r.isin, "INE483S01038")
        self.assertTrue(r.resolved)
        r_none = ir.resolve("CCAVENUE", None, MASTER)
        self.assertEqual(r_none.isin, "INE483S01038")

    def test_blank_isin_unknown_symbol_is_unresolved(self):
        r = ir.resolve("GHOST", "  ", MASTER)
        self.assertFalse(r.resolved)
        self.assertEqual(r.isin, "")

    def test_case_insensitive(self):
        r = ir.resolve("ccavenue", "ine483s01020", MASTER)
        self.assertEqual((r.symbol, r.isin), ("CCAVENUE", "INE483S01038"))
        self.assertTrue(r.changed)
        r2 = ir.resolve(" reliance ", "ine002a01018", MASTER)
        self.assertFalse(r2.changed)
        self.assertEqual(r2.symbol, "RELIANCE")


class RecordTests(unittest.TestCase):
    def test_record_upserts_history_and_alias(self):
        results = [
            ir.resolve("CCAVENUE", "INE483S01020", MASTER),
            ir.resolve("OLDNAME", "INEREN0100X", MASTER),
            ir.resolve("GHOST", "INE000000000", MASTER),
        ]
        conn = FakeConn()
        written = ir.record(conn, results, today=date(2026, 11, 2))
        self.assertEqual(written, 3)  # two history rows + one alias row; unresolved skipped
        history = [c for c in conn.calls if c[0].startswith("INSERT INTO isin_history")]
        alias = [c for c in conn.calls if c[0].startswith("INSERT INTO symbol_alias")]
        self.assertEqual(len(history), 2)
        self.assertEqual(len(alias), 1)
        self.assertIn("ON CONFLICT (symbol, isin)", history[0][0])
        self.assertNotIn("first_seen = EXCLUDED", history[0][0])  # first_seen is kept
        self.assertEqual(history[0][1], ("CCAVENUE", "INE483S01038", date(2026, 11, 2), date(2026, 11, 2), ir.SOURCE))
        self.assertIn("ON CONFLICT (old_symbol, new_symbol, isin)", alias[0][0])
        self.assertEqual(alias[0][1], ("OLDNAME", "NEWNAME", "INEREN0100X", date(2026, 11, 2)))

    def test_record_defaults_today(self):
        conn = FakeConn()
        ir.record(conn, [ir.resolve("RELIANCE", "INE002A01018", MASTER)])
        self.assertEqual(conn.calls[0][1][2], date.today())


class ResolveAllTests(unittest.TestCase):
    def test_loads_master_once_and_records_with_conn(self):
        pairs = [("CCAVENUE", "INE483S01020"), ("RELIANCE", "INE002A01018")]
        with mock.patch.object(ir, "load_master", return_value=MASTER) as lm:
            conn = FakeConn()
            out = ir.resolve_all(pairs, conn=conn)
        self.assertEqual(lm.call_count, 1)
        self.assertEqual([r.isin for r in out], ["INE483S01038", "INE002A01018"])
        self.assertEqual(len(conn.calls), 2)

    def test_no_conn_writes_nothing(self):
        with mock.patch.object(ir, "load_master", return_value=MASTER):
            out = ir.resolve_all([("RELIANCE", "INE002A01018")])
        self.assertEqual(len(out), 1)


class LoadMasterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.cache = self.dir / "data" / "upstox_nse_master.json.gz"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_cache(self, rows, age_seconds):
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_bytes(_gz_bytes(rows))
        mtime = 1_000_000_000 + 0  # arbitrary fixed epoch
        os.utime(self.cache, (mtime, mtime))
        return mtime + age_seconds  # "now" that makes the file this old

    def test_parse_keeps_only_nse_equity(self):
        m = ir._parse(_gz_bytes(_master_rows()))
        self.assertEqual(m["by_symbol"], {"CCAVENUE": "INE483S01038", "RELIANCE": "INE002A01018"})
        self.assertEqual(m["by_isin"], {"INE483S01038": "CCAVENUE", "INE002A01018": "RELIANCE"})

    def test_fresh_cache_used_without_download(self):
        now = self._write_cache(_master_rows(), age_seconds=60)
        with mock.patch.object(ir, "_download") as dl:
            m = ir.load_master(cache_path=self.cache, now=now)
        dl.assert_not_called()
        self.assertIn("CCAVENUE", m["by_symbol"])

    def test_stale_cache_triggers_download_and_refresh(self):
        now = self._write_cache([], age_seconds=ir.MAX_AGE_SECONDS + 1)
        with mock.patch.object(ir, "_download", return_value=_gz_bytes(_master_rows())) as dl:
            m = ir.load_master(cache_path=self.cache, now=now)
        dl.assert_called_once_with(ir.MASTER_URL)
        self.assertEqual(m["by_isin"]["INE483S01038"], "CCAVENUE")
        # cache rewritten with the fresh bytes
        self.assertEqual(ir._parse(self.cache.read_bytes())["by_symbol"]["RELIANCE"], "INE002A01018")

    def test_missing_cache_downloads(self):
        with mock.patch.object(ir, "_download", return_value=_gz_bytes(_master_rows())):
            m = ir.load_master(cache_path=self.cache, now=2_000_000_000)
        self.assertTrue(self.cache.exists())
        self.assertIn("RELIANCE", m["by_symbol"])

    def test_download_failure_with_stale_cache_uses_it_and_warns(self):
        now = self._write_cache(_master_rows(), age_seconds=ir.MAX_AGE_SECONDS * 3)
        with mock.patch.object(ir, "_download", side_effect=OSError("network down")):
            with self.assertLogs("scanner.isin_resolver", level="WARNING") as logs:
                m = ir.load_master(cache_path=self.cache, now=now)
        self.assertEqual(m["by_symbol"]["CCAVENUE"], "INE483S01038")
        self.assertTrue(any("stale cache" in line for line in logs.output))

    def test_download_failure_without_cache_raises(self):
        with mock.patch.object(ir, "_download", side_effect=OSError("network down")):
            with self.assertRaises(RuntimeError) as ctx:
                ir.load_master(cache_path=self.cache, now=2_000_000_000)
        self.assertNotIn("\n", str(ctx.exception))
        self.assertIn("no cache", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
