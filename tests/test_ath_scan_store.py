"""Tests for scanner/ath_scan_store.py (ath_scan_candidates, migration 060).

FakeConnectionTests run offline: a fake connection records the SQL and parameters, and a
captured write is turned back into database rows, so the round trip is checked without a database.

RealPostgresTests run the same functions on a throwaway schema with every migration applied
(tests/pgschema.py). They skip when Postgres is unreachable.
"""
import unittest
import uuid
from datetime import date, timedelta

import numpy as np
import pandas as pd

from scanner import ath_scan_store as store
from scanner import report

SCAN_DAY = date(2026, 11, 8)
RUN_ID = "6f1c2a4e-9b1d-4c3e-8f5a-1234567890ab"


def _frame(rows=None):
    """A frame shaped like ath_scan's output. NA is a real symbol; INSUFFICIENT_HISTORY is a bucket."""
    if rows is None:
        rows = [
            {
                "symbol": "NA", "company": "N A Ltd", "industry": "", "ltp": 10.5,
                "today_high": np.nan, "ath_high": 12.0, "ath_date": date(2026, 1, 2),
                "ath_close": 11.0, "distance_pct": 12.5, "bucket": "INSUFFICIENT_HISTORY",
                "days_since_ath": 3, "listed_days": 20, "recent_ipo": True,
                "ema50": None, "sma200": np.nan, "above_ema50": None, "above_sma200": False,
                "trend": "", "bonus_issue": "", "demerger": "", "orderbook_signal": "",
                "expansion_signal": "", "factors_matched": 0, "isin": "INE000000001",
            },
            {
                "symbol": "INFY", "company": "Infosys", "industry": "IT", "ltp": 1500.0,
                "today_high": 1510.0, "ath_high": 1600.0, "ath_date": date(2026, 9, 30),
                "ath_close": 1590.0, "distance_pct": 6.2, "bucket": "5-15%",
                "days_since_ath": 30, "listed_days": 4000, "recent_ipo": False,
                "ema50": 1450.5, "sma200": 1300.25, "above_ema50": True, "above_sma200": True,
                "trend": "UP", "bonus_issue": "BONUS 1:1", "demerger": "",
                "orderbook_signal": "STRONG", "expansion_signal": "", "factors_matched": 2,
            },
        ]
    return pd.DataFrame(rows)


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, records):
        self.log.append(("executemany", sql, list(records)))


class _FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.transactions += 1
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    """Records statements. Reads answer from the canned latest date, rows and count."""

    def __init__(self, latest=None, rows=None, count=0):
        self.latest = latest
        self.rows = rows or []
        self.count = count
        self.log = []
        self.transactions = 0

    def execute(self, sql, params=None):
        self.log.append(("execute", sql, params))
        if "max(scan_date)" in sql:
            return _Result(row={"d": self.latest})
        if "count(*)" in sql:
            return _Result(row={"n": self.count})
        return _Result(rows=self.rows)

    def cursor(self):
        return _FakeCursor(self.log)

    def transaction(self):
        return _FakeTransaction(self)

    def executed_sql(self):
        return [entry for entry in self.log if entry[0] == "execute"]


def _captured_records(df, scan_date=SCAN_DAY, run_id=None):
    conn = _FakeConn()
    store.write_scan(conn, scan_date, df, run_id=run_id)
    (_, _, records), = [e for e in conn.log if e[0] == "executemany"]
    return records


def _as_rows(records):
    """Turn the captured insert records into the dict rows a select would return."""
    cols = ["scan_date", "run_id", *store.ATH_SCAN_COLUMNS]
    return [dict(zip(cols, rec)) for rec in records]


class FakeConnectionTests(unittest.TestCase):

    def test_empty_frame_writes_nothing_and_returns_zero(self):
        conn = _FakeConn()
        self.assertEqual(store.write_scan(conn, SCAN_DAY, pd.DataFrame()), 0)
        self.assertEqual(conn.log, [])
        self.assertEqual(conn.transactions, 0)

    def test_write_is_one_transaction_delete_insert_prune(self):
        conn = _FakeConn()
        n = store.write_scan(conn, SCAN_DAY, _frame())
        self.assertEqual(n, 2)
        self.assertEqual(conn.transactions, 1)
        kinds = [entry[0] for entry in conn.log]
        self.assertEqual(kinds, ["execute", "executemany", "execute"])
        first_sql, first_params = conn.log[0][1], conn.log[0][2]
        self.assertIn("DELETE FROM ath_scan_candidates WHERE scan_date = %s", first_sql)
        self.assertEqual(first_params, (SCAN_DAY,))
        last_sql, last_params = conn.log[2][1], conn.log[2][2]
        self.assertIn("DELETE FROM ath_scan_candidates WHERE scan_date < %s", last_sql)
        self.assertEqual(last_params, (SCAN_DAY - timedelta(days=90),))

    def test_retention_default_is_ninety_days_and_is_a_parameter(self):
        conn = _FakeConn()
        store.write_scan(conn, SCAN_DAY, _frame(), retention_days=30)
        self.assertEqual(conn.log[2][2], (SCAN_DAY - timedelta(days=30),))

    def test_insert_uses_placeholders_only_and_names_every_column(self):
        conn = _FakeConn()
        store.write_scan(conn, SCAN_DAY, _frame())
        sql = [e for e in conn.log if e[0] == "executemany"][0][1]
        self.assertNotIn("NA", sql.split("VALUES")[1])
        self.assertEqual(sql.count("%s"), 2 + len(store.ATH_SCAN_COLUMNS))
        for col in store.ATH_SCAN_COLUMNS:
            self.assertIn(col, sql)

    def test_missing_values_become_empty_text_or_null(self):
        records = dict(zip(["scan_date", "run_id", *store.ATH_SCAN_COLUMNS],
                           _captured_records(_frame())[0]))
        self.assertEqual(records["symbol"], "NA")
        self.assertEqual(records["isin"], "INE000000001")
        self.assertEqual(records["industry"], "")
        self.assertIsNone(records["today_high"])
        self.assertIsNone(records["sma200"])
        self.assertIsNone(records["ema50"])
        self.assertEqual(records["above_ema50"], "")
        self.assertEqual(records["above_sma200"], "False")
        self.assertEqual(records["recent_ipo"], "True")
        self.assertEqual(records["ath_date"], "2026-01-02")
        self.assertEqual(records["bucket"], "INSUFFICIENT_HISTORY")
        self.assertEqual(records["days_since_ath"], 3)
        self.assertIsInstance(records["days_since_ath"], int)
        self.assertIsInstance(records["ltp"], float)

    def test_missing_columns_are_filled(self):
        df = _frame().drop(columns=["trend", "bonus_issue"])
        records = dict(zip(["scan_date", "run_id", *store.ATH_SCAN_COLUMNS],
                           _captured_records(df)[1]))
        self.assertEqual(records["trend"], "")
        self.assertEqual(records["bonus_issue"], "")

    def test_isin_is_stored_and_a_missing_isin_is_empty(self):
        records = _captured_records(_frame())
        self.assertEqual(len(records[0]), 2 + len(store.ATH_SCAN_COLUMNS))
        isin_at = 2 + store.ATH_SCAN_COLUMNS.index("isin")
        self.assertEqual(records[0][isin_at], "INE000000001")
        self.assertEqual(records[1][isin_at], "")  # the INFY row: isin missing from the frame

    def test_run_id_is_converted_to_uuid(self):
        records = _captured_records(_frame(), run_id=RUN_ID)
        self.assertEqual(records[0][1], uuid.UUID(RUN_ID))
        self.assertIsNone(_captured_records(_frame())[0][1])

    def test_bad_run_id_raises(self):
        with self.assertRaises(ValueError):
            store.write_scan(_FakeConn(), SCAN_DAY, _frame(), run_id="not-a-uuid")

    def test_round_trip_through_fake_rows_gives_the_same_frame(self):
        df = _frame()
        records = _captured_records(df)
        conn = _FakeConn(latest=SCAN_DAY, rows=_as_rows(records))
        frame, scan_date = store.read_latest_scan(conn)
        self.assertEqual(scan_date, SCAN_DAY)
        self.assertEqual(list(frame.columns), store.ATH_SCAN_COLUMNS)
        self._assert_same_candidates(df, frame)

    def test_read_returns_none_when_no_rows(self):
        self.assertIsNone(store.read_latest_scan(_FakeConn(latest=None)))

    def test_read_asks_for_newest_date_at_or_before_as_of(self):
        conn = _FakeConn(latest=SCAN_DAY, rows=[])
        store.read_latest_scan(conn, as_of=date(2026, 11, 10))
        max_sql, params = conn.executed_sql()[0][1], conn.executed_sql()[0][2]
        self.assertIn("scan_date <= %s", max_sql)
        self.assertEqual(params, (date(2026, 11, 10),))

    def _assert_same_candidates(self, df, frame):
        self.assertEqual(list(frame["symbol"]), list(report.sort_results(df)["symbol"]))
        by_symbol = df.set_index("symbol")
        for col in store.TEXT_COLUMNS:
            if col == "symbol":
                continue
            expected = by_symbol[col].reindex(frame["symbol"]).map(
                lambda v: "" if pd.isna(v) else str(v)).tolist()
            self.assertEqual(frame[col].tolist(), expected, col)
        for col in store.NUMERIC_COLUMNS:
            expected = by_symbol[col].reindex(frame["symbol"]).astype("float64").to_numpy()
            np.testing.assert_array_equal(frame[col].to_numpy(dtype="float64"), expected, err_msg=col)


class RealPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import pgschema
        cls.schema = pgschema.create(cls)

    def setUp(self):
        from scanner.pg import db
        with db.connect() as conn:
            conn.execute("DELETE FROM ath_scan_candidates")

    def _conn(self):
        from scanner.pg import db
        return db.connect()

    def test_write_then_read_round_trip(self):
        df = _frame()
        with self._conn() as conn:
            self.assertEqual(store.write_scan(conn, SCAN_DAY, df), 2)
            frame, scan_date = store.read_latest_scan(conn)
        self.assertEqual(scan_date, SCAN_DAY)
        self.assertEqual(list(frame.columns), store.ATH_SCAN_COLUMNS)
        self.assertEqual(frame.loc[frame["symbol"] == "NA", "bucket"].item(), "INSUFFICIENT_HISTORY")
        na = frame[frame["symbol"] == "NA"].iloc[0]
        self.assertEqual(na["industry"], "")
        self.assertEqual(na["above_ema50"], "")
        self.assertTrue(np.isnan(na["sma200"]))
        self.assertTrue(np.isnan(na["today_high"]))
        self.assertEqual(na["recent_ipo"], "True")
        self.assertEqual(na["isin"], "INE000000001")
        self.assertEqual(na["ath_date"], "2026-01-02")
        infy = frame[frame["symbol"] == "INFY"].iloc[0]
        self.assertEqual(infy["bonus_issue"], "BONUS 1:1")
        self.assertEqual(infy["ema50"], 1450.5)
        self.assertEqual(int(infy["factors_matched"]), 2)

    def test_same_day_rewrite_replaces_rows(self):
        with self._conn() as conn:
            store.write_scan(conn, SCAN_DAY, _frame())
            store.write_scan(conn, SCAN_DAY, _frame().iloc[:1])
            self.assertEqual(store.scan_row_count(conn, SCAN_DAY), 1)

    def test_rows_older_than_retention_are_pruned(self):
        old = SCAN_DAY - timedelta(days=91)
        edge = SCAN_DAY - timedelta(days=90)
        with self._conn() as conn:
            store.write_scan(conn, old, _frame().iloc[:1])
            store.write_scan(conn, edge, _frame().iloc[:1])
            store.write_scan(conn, SCAN_DAY, _frame().iloc[:1])
            self.assertEqual(store.scan_row_count(conn, old), 0)
            self.assertEqual(store.scan_row_count(conn, edge), 1)

    def test_empty_frame_keeps_earlier_rows_of_the_day(self):
        with self._conn() as conn:
            store.write_scan(conn, SCAN_DAY, _frame())
            self.assertEqual(store.write_scan(conn, SCAN_DAY, pd.DataFrame()), 0)
            self.assertEqual(store.scan_row_count(conn, SCAN_DAY), 2)

    def test_latest_honours_as_of_and_none_when_empty(self):
        earlier = SCAN_DAY - timedelta(days=1)
        with self._conn() as conn:
            self.assertIsNone(store.read_latest_scan(conn))
            self.assertIsNone(store.latest_scan_date(conn))
            store.write_scan(conn, earlier, _frame().iloc[:1])
            store.write_scan(conn, SCAN_DAY, _frame())
            _, newest = store.read_latest_scan(conn)
            self.assertEqual(newest, SCAN_DAY)
            _, before = store.read_latest_scan(conn, as_of=earlier)
            self.assertEqual(before, earlier)
            self.assertIsNone(store.read_latest_scan(conn, as_of=earlier - timedelta(days=1)))

    def test_run_id_is_cleared_when_the_run_is_deleted(self):
        from scanner.pg import db
        run_id = uuid.uuid4()
        with self._conn() as conn:
            conn.execute("INSERT INTO collector_runs (id, source, trigger, status) "
                         "VALUES (%s, 'ath_scan', 'manual', 'ok')", (run_id,))
            store.write_scan(conn, SCAN_DAY, _frame().iloc[:1], run_id=str(run_id))
            conn.execute("DELETE FROM collector_runs WHERE id = %s", (run_id,))
            row = conn.execute("SELECT run_id FROM ath_scan_candidates").fetchone()
        self.assertIsNone(row["run_id"])


if __name__ == "__main__":
    unittest.main()
