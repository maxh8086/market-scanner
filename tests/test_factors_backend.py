"""Factor cache and intensity reader on the Postgres backend, offline.

The suite forces MARKETDATA_BACKEND=sqlite, so these tests patch get_backend to
"postgres" and replace the connection with a recorder. Nothing reaches a server.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scanner import factors, intensity

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"


class _Pg:
    """Stand-in for a psycopg connection: records statements, returns canned rows."""

    def __init__(self, rows=None, one=None):
        self.statements: list[tuple[str, object]] = []
        self.many: list[tuple[str, list]] = []
        self.rows = rows or []
        self.one = one

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    def executemany(self, sql, data):
        self.many.append((sql, list(data)))

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows

    def commit(self):
        pass


def _pg_backend():
    return mock.patch("scanner.marketdata.get_backend", return_value="postgres")


class MigrationFileTest(unittest.TestCase):
    def test_011_declares_both_tables_idempotently(self):
        sql = (MIGRATIONS / "011_fetch_metadata_pull_log.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS fetch_metadata", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS upstox_pull_log", sql)
        self.assertIn("feed_name text PRIMARY KEY", sql)
        self.assertIn("id bigserial PRIMARY KEY", sql)
        self.assertIn("status text NOT NULL", sql)
        self.assertIn("pulled_at timestamptz NOT NULL", sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS upstox_pull_log_symbol_idx", sql)


class FetchMetadataPostgresTest(unittest.TestCase):
    def test_mark_then_was_fetched_today_round_trip(self):
        start, end = date(2026, 10, 1), date(2026, 11, 1)
        pg = _Pg()
        with _pg_backend(), mock.patch(
            "scanner.marketdata.factors_postgres.connect", return_value=pg
        ):
            factors._mark_fetched("announcements", start, end)
            # The INSERT carries real dates and a timezone-aware timestamp.
            sql, params = pg.statements[-1]
            self.assertIn("INSERT INTO fetch_metadata", sql)
            feed, f_from, f_to, fetched_at = params
            self.assertEqual((feed, f_from, f_to), ("announcements", start, end))
            self.assertIsInstance(fetched_at, datetime)
            self.assertIsNotNone(fetched_at.tzinfo)

            # Feed the stored row back, as the table would return it.
            pg.one = {"from_date": f_from, "to_date": f_to, "fetched_at": fetched_at}
            self.assertTrue(factors._was_fetched_today("announcements", start, end))
            self.assertFalse(
                factors._was_fetched_today("announcements", start, end + timedelta(days=1))
            )

    def test_fetched_yesterday_is_not_fetched_today(self):
        start, end = date(2026, 10, 1), date(2026, 11, 1)
        yesterday = datetime.now().astimezone() - timedelta(days=1)
        pg = _Pg(one={"from_date": start, "to_date": end, "fetched_at": yesterday})
        with _pg_backend(), mock.patch(
            "scanner.marketdata.factors_postgres.connect", return_value=pg
        ):
            self.assertFalse(factors._was_fetched_today("announcements", start, end))

    def test_no_row_means_not_fetched(self):
        with _pg_backend(), mock.patch(
            "scanner.marketdata.factors_postgres.connect", return_value=_Pg(one=None)
        ):
            self.assertFalse(
                factors._was_fetched_today("corporate_actions", date(2026, 1, 1), date(2026, 2, 1))
            )


class AnnouncementCachePostgresTest(unittest.TestCase):
    def test_save_writes_date_objects_and_skips_undated_rows(self):
        rows = [
            {"sm_isin": "INE1", "symbol": "ACME", "an_dt": "15-Mar-2026 10:00:00",
             "desc": "BAGGING/RECEIVING OF ORDERS/CONTRACTS", "attchmntText": "won",
             "sort_date": "15-Mar-2026 10:00:00", "seqId": "123",
             "attchmntFile": "a.pdf", "attFileSize": "1.5 MB"},
            {"sm_isin": "INE1", "symbol": "ACME", "an_dt": "", "desc": "x"},
        ]
        pg = _Pg()
        with _pg_backend(), mock.patch(
            "scanner.marketdata.factors_postgres.connect", return_value=pg
        ):
            factors._save_announcements(rows)
        self.assertEqual(len(pg.many), 1)
        sql, data = pg.many[0]
        self.assertEqual(len(data), 1, "the row without an_dt must be skipped")
        isin, symbol, an_dt, desc, text, sort_date, seq, fname, size = data[0]
        self.assertEqual(an_dt, date(2026, 3, 15))
        self.assertEqual(sort_date, date(2026, 3, 15))
        self.assertEqual((isin, symbol, seq, fname), ("INE1", "ACME", "123", "a.pdf"))
        self.assertEqual(size, int(1.5 * 1024 * 1024))
        # One-way backfill is kept, and "desc" is quoted in the upsert.
        self.assertIn("COALESCE(NULLIF(excluded.seq_id, ''), seq_id)", sql)
        self.assertIn('ON CONFLICT (isin, an_dt, "desc") DO UPDATE', sql)

    def test_load_returns_iso_strings_and_quotes_desc(self):
        pg = _Pg(rows=[{
            "isin": "INE1", "symbol": "ACME", "an_dt": date(2026, 3, 15), "desc": "BONUS",
            "attchmnt_text": None, "sort_date": date(2026, 3, 16), "seq_id": "9",
            "attchmnt_file": "f.pdf", "att_file_size": 10,
        }])
        with _pg_backend(), mock.patch(
            "scanner.marketdata.factors_postgres.connect", return_value=pg
        ):
            out = factors._load_cached_announcements(date(2026, 3, 1), date(2026, 3, 31))
        self.assertIn('"desc"', pg.statements[-1][0])
        self.assertEqual(out, [{
            "sm_isin": "INE1", "symbol": "ACME", "an_dt": "2026-03-15", "desc": "BONUS",
            "attchmntText": "", "sort_date": "2026-03-16", "seqId": "9",
            "attchmntFile": "f.pdf", "attFileSize": 10,
        }])


class CorporateActionCachePostgresTest(unittest.TestCase):
    def test_save_skips_rows_without_ex_date_and_uses_do_nothing(self):
        rows = [
            {"isin": "INE2", "symbol": "BETA", "subject": "Bonus 1:1", "exDate": "27-Aug-2025"},
            {"isin": "INE2", "symbol": "BETA", "subject": "Dividend", "exDate": ""},
        ]
        pg = _Pg()
        with _pg_backend(), mock.patch(
            "scanner.marketdata.factors_postgres.connect", return_value=pg
        ):
            factors._save_corporate_actions(rows)
        sql, data = pg.many[0]
        self.assertEqual(data, [("INE2", "BETA", "Bonus 1:1", date(2025, 8, 27), None)])
        self.assertIn("ON CONFLICT (isin, ex_date, subject) DO NOTHING", sql)

    def test_load_returns_iso_ex_date(self):
        pg = _Pg(rows=[{"isin": "INE2", "symbol": "BETA", "subject": "Bonus 1:1",
                        "ex_date": date(2025, 8, 27)}])
        with _pg_backend(), mock.patch(
            "scanner.marketdata.factors_postgres.connect", return_value=pg
        ):
            out = factors._load_cached_corporate_actions(date(2025, 1, 1), date(2025, 12, 31))
        self.assertEqual(out, [{"isin": "INE2", "symbol": "BETA", "subject": "Bonus 1:1",
                                "exDate": "2025-08-27"}])


class PostgresNeverOpensFactorsDbTest(unittest.TestCase):
    def test_cache_helpers_do_not_create_factors_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope" / "factors.db"
            pg = _Pg()
            with _pg_backend(), mock.patch.object(factors, "DB_PATH", missing), \
                    mock.patch("scanner.marketdata.factors_postgres.connect", return_value=pg), \
                    mock.patch.object(factors, "_connect", side_effect=AssertionError("sqlite opened")):
                factors._save_announcements([{"an_dt": "2026-03-15", "sm_isin": "I", "symbol": "S",
                                              "desc": "d"}])
                factors._save_corporate_actions([{"isin": "I", "symbol": "S", "subject": "s",
                                                  "exDate": "2026-03-15"}])
                factors._mark_fetched("announcements", date(2026, 1, 1), date(2026, 1, 31))
                factors._was_fetched_today("announcements", date(2026, 1, 1), date(2026, 1, 31))
                factors._load_cached_announcements(date(2026, 1, 1), date(2026, 1, 31))
                factors._load_cached_corporate_actions(date(2026, 1, 1), date(2026, 1, 31))
            self.assertFalse(missing.exists())
            self.assertFalse(missing.parent.exists())


class LoadAnnouncementsPostgresTest(unittest.TestCase):
    def test_maps_rows_to_the_shared_keys_with_iso_dates(self):
        pg = _Pg(rows=[{"symbol": "ACME", "desc": "BAGGING/RECEIVING OF ORDERS/CONTRACTS",
                        "attchmnt_text": "won an order", "an_dt": date(2026, 3, 15),
                        "sort_date": None}])
        with _pg_backend(), mock.patch("scanner.pg.db.connect", return_value=pg):
            rows = intensity.load_announcements()
        self.assertEqual(rows, [{"symbol": "ACME",
                                 "desc": "BAGGING/RECEIVING OF ORDERS/CONTRACTS",
                                 "attchmntText": "won an order",
                                 "an_dt": "2026-03-15", "sort_date": None}])
        self.assertIn('"desc"', pg.statements[-1][0])
        self.assertIsNotNone(intensity._row_date(rows[0]))

    def test_postgres_errors_propagate(self):
        with _pg_backend(), mock.patch("scanner.pg.db.connect",
                                       side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                intensity.load_announcements()

    def test_explicit_path_still_reads_sqlite_under_postgres(self):
        with _pg_backend(), tempfile.TemporaryDirectory() as tmp, \
                mock.patch("scanner.pg.db.connect") as connect:
            self.assertEqual(intensity.load_announcements(Path(tmp) / "nope.db"), [])
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
