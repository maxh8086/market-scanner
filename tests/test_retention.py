import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scanner import docstore, retention
from scanner.retention import Retention


class LoadTests(unittest.TestCase):
    def test_defaults_when_missing(self):
        cfg = retention.load("nope.json", env={})
        self.assertEqual((cfg.years, cfg.purge, cfg.only_when_processed), (3, True, True))

    def test_file_and_env_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text(json.dumps({"years": 5, "purge": False}))
            self.assertEqual(retention.load(p, env={}).years, 5)
            self.assertFalse(retention.load(p, env={}).purge)
            cfg = retention.load(p, env={"RETENTION_YEARS": "1", "RETENTION_PURGE": "true"})
            self.assertEqual((cfg.years, cfg.purge), (1, True))

    def test_broken_file_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text("{not json")
            self.assertEqual(retention.load(p, env={}).years, 3)


class DateTests(unittest.TestCase):
    def test_parse_formats(self):
        self.assertEqual(retention.parse_date("2026-07-03"), date(2026, 7, 3))
        self.assertEqual(retention.parse_date("03-Jul-2026 10:11:12"), date(2026, 7, 3))
        self.assertEqual(retention.parse_date("2026-07-03T10:00:00+00:00"), date(2026, 7, 3))
        self.assertIsNone(retention.parse_date("garbage"))

    def test_expires_and_leap_day(self):
        cfg = Retention(years=3)
        self.assertEqual(retention.expires_at("2026-07-03", cfg), "2029-07-03")
        self.assertEqual(retention.expires_at("2024-02-29", cfg)[:4], "2027")
        self.assertTrue(retention.is_expired("2020-01-01", date(2026, 1, 1)))
        self.assertFalse(retention.is_expired("2030-01-01", date(2026, 1, 1)))
        self.assertFalse(retention.is_expired("", date(2026, 1, 1)))


class PurgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = docstore.open_db(Path(self.tmp.name) / "d.json")
        docstore.put_filing(self.db, {"seq_id": "1", "symbol": "A", "an_date": "2019-01-01"})
        docstore.put_filing(self.db, {"seq_id": "2", "symbol": "B", "an_date": "2019-01-01"})
        docstore.put_filing(self.db, {"seq_id": "3", "symbol": "C", "an_date": "2026-01-01"})
        docstore.put_extraction(self.db, "1", "orderbook", {"symbol": "A"})
        docstore.put_extraction(self.db, "3", "orderbook", {"symbol": "C"})

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_stamped(self):
        self.assertEqual(docstore.get_filing(self.db, "1")["expires_at"], "2022-01-01")

    def test_purges_only_expired_and_processed(self):
        today = date(2026, 9, 30)
        dry = retention.purge_docstore(self.db, Retention(), today, dry_run=True)
        self.assertEqual(dry["filings"], 1)
        self.assertEqual(len(docstore.all_filings(self.db)), 3)
        done = retention.purge_docstore(self.db, Retention(), today)
        self.assertEqual((done["filings"], done["extractions"]), (1, 1))
        left = {f["seq_id"] for f in docstore.all_filings(self.db)}
        self.assertEqual(left, {"2", "3"})           # 2 expired but never processed

    def test_unprocessed_purged_when_flag_off(self):
        cfg = Retention(only_when_processed=False)
        retention.purge_docstore(self.db, cfg, date(2026, 9, 30))
        self.assertEqual({f["seq_id"] for f in docstore.all_filings(self.db)}, {"3"})

    def test_purge_disabled(self):
        cfg = Retention(purge=False)
        self.assertEqual(sum(retention.purge_docstore(self.db, cfg, date(2030, 1, 1)).values()), 0)
        self.assertEqual(len(docstore.all_filings(self.db)), 3)


if __name__ == "__main__":
    unittest.main()
