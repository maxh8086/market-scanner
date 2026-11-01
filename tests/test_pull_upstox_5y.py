"""Offline tests for scripts/pull_upstox_5y.py using a fake Upstox client."""
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from scanner.upstox import UpstoxError
from scripts import pull_upstox_5y as pull

TODAY = date(2026, 11, 1)


class FakeClient:
    """Serves one synthetic daily candle per calendar day, Upstox-shaped rows."""

    def __init__(self, first_day: date, last_day: date, fail: dict | None = None):
        self.first_day = first_day
        self.last_day = last_day
        self.fail = fail or {}  # key -> exception to raise
        self.calls: list[tuple[str, date, date]] = []

    def daily_candles(self, key, from_date, to_date):
        self.calls.append((key, from_date, to_date))
        if key in self.fail:
            raise self.fail[key]
        start = max(from_date, self.first_day)
        end = min(to_date, self.last_day)
        rows = []
        d = start
        while d <= end:
            ts = f"{d.isoformat()}T00:00:00+05:30"
            rows.append({"date": ts, "open": 1.0, "high": 2.0, "low": 0.5,
                         "close": 1.5, "volume": 100})
            # Duplicate row for the same day: must be deduped.
            rows.append({"date": ts, "open": 1.0, "high": 2.0, "low": 0.5,
                         "close": 1.5, "volume": 100})
            d += timedelta(days=1)
        return rows


class PullUpstox5yTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "upstox_5y.db"
        self.conn = pull.connect(self.db)

    def tearDown(self):
        self.conn.close()

    def _count(self, symbol):
        return self.conn.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol = ?", (symbol,)
        ).fetchone()[0]

    def test_first_pull_is_deduped_and_logged(self):
        client = FakeClient(TODAY - timedelta(days=9), TODAY)
        s = pull.run(client, self.conn, [("AAA", "INE000000001")], 10, TODAY,
                     datetime(2026, 11, 1, 9, 0))
        self.assertEqual(s["ok"], 1)
        self.assertEqual(self._count("AAA"), 10)  # 10 days, duplicates dropped
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1], TODAY - timedelta(days=9))
        status, rows, last = self.conn.execute(
            "SELECT status, rows, last_date FROM pull_log WHERE symbol='AAA'"
        ).fetchone()
        self.assertEqual((status, rows, last), ("ok", 10, TODAY.isoformat()))

    def test_resume_skips_when_recent_ok(self):
        client = FakeClient(TODAY - timedelta(days=9), TODAY)
        universe = [("AAA", "INE000000001")]
        pull.run(client, self.conn, universe, 10, TODAY, datetime(2026, 11, 1, 9))
        client.calls.clear()
        s = pull.run(client, self.conn, universe, 10, TODAY, datetime(2026, 11, 1, 10))
        self.assertEqual(s["skipped"], 1)
        self.assertEqual(client.calls, [])
        self.assertEqual(self._count("AAA"), 10)

    def test_incremental_fetch_starts_after_last_stored_date(self):
        client = FakeClient(TODAY - timedelta(days=9), TODAY)
        universe = [("AAA", "INE000000001")]
        pull.run(client, self.conn, universe, 10, TODAY, datetime(2026, 11, 1, 9))

        later = TODAY + timedelta(days=10)  # pull_log last_date now 10 days old
        client.last_day = later
        client.calls.clear()
        s = pull.run(client, self.conn, universe, 10, later, datetime(2026, 11, 11, 9))
        self.assertEqual(s["ok"], 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1], TODAY + timedelta(days=1))
        self.assertEqual(client.calls[0][2], later)
        self.assertEqual(self._count("AAA"), 20)  # no overlap duplicates

    def test_overlapping_refetch_does_not_duplicate_rows(self):
        client = FakeClient(TODAY - timedelta(days=9), TODAY)
        universe = [("AAA", "INE000000001")]
        pull.run(client, self.conn, universe, 10, TODAY, datetime(2026, 11, 1, 9))
        # Simulate a re-pull of an already-stored day with a revised close.
        df = pull._to_frame([{"date": f"{TODAY.isoformat()}T00:00:00+05:30",
                              "open": 1, "high": 2, "low": 0.5, "close": 9.9,
                              "volume": 5}])
        pull._write_candles(self.conn, "AAA", df)
        self.conn.commit()
        self.assertEqual(self._count("AAA"), 10)
        close = self.conn.execute(
            "SELECT close FROM candles WHERE symbol='AAA' AND date=?",
            (TODAY.isoformat(),),
        ).fetchone()[0]
        self.assertEqual(close, 9.9)

    def test_empty_symbol_logged_as_empty(self):
        client = FakeClient(TODAY + timedelta(days=5), TODAY + timedelta(days=5))
        s = pull.run(client, self.conn, [("NEW", "INE000000002")], 10, TODAY,
                     datetime(2026, 11, 1, 9))
        self.assertEqual(s["empty"], 1)
        status = self.conn.execute(
            "SELECT status FROM pull_log WHERE symbol='NEW'"
        ).fetchone()[0]
        self.assertEqual(status, "empty")

    def test_failure_is_isolated_and_retried_later(self):
        client = FakeClient(TODAY - timedelta(days=9), TODAY,
                            fail={"NSE_EQ|INE000000003": UpstoxError("HTTP 500 from x -- boom")})
        universe = [("BAD", "INE000000003"), ("AAA", "INE000000001")]
        s = pull.run(client, self.conn, universe, 10, TODAY, datetime(2026, 11, 1, 9))
        self.assertEqual(s["failed"], ["BAD"])
        self.assertEqual(s["ok"], 1)
        self.assertEqual(self._count("AAA"), 10)
        # A failed symbol is not skipped on the next run.
        client.fail = {}
        s2 = pull.run(client, self.conn, universe, 10, TODAY, datetime(2026, 11, 1, 10))
        self.assertEqual(s2["skipped"], 1)
        self.assertEqual(s2["ok"], 1)
        self.assertEqual(self._count("BAD"), 10)

    def test_failed_symbol_stores_error_text(self):
        client = FakeClient(TODAY - timedelta(days=9), TODAY,
                            fail={"NSE_EQ|INE000000003": UpstoxError("HTTP 400 from x -- bad input")})
        s = pull.run(client, self.conn, [("CCAVENUE", "INE000000003")], 10, TODAY,
                     datetime(2026, 11, 1, 9))
        self.assertEqual(s["failed"], ["CCAVENUE"])
        error = self.conn.execute(
            "SELECT error FROM pull_log WHERE symbol='CCAVENUE' AND status='failed'"
        ).fetchone()[0]
        self.assertIn("HTTP 400", error)
        self.assertIn("bad input", error)

    def test_error_text_is_redacted_and_capped(self):
        secret = "Bearer eyJsecret123"
        long_msg = f"HTTP 500 from x -- {secret} " + "x" * 1000
        client = FakeClient(TODAY - timedelta(days=9), TODAY,
                            fail={"NSE_EQ|INE000000003": UpstoxError(long_msg)})
        pull.run(client, self.conn, [("BAD", "INE000000003")], 10, TODAY,
                 datetime(2026, 11, 1, 9))
        error = self.conn.execute(
            "SELECT error FROM pull_log WHERE symbol='BAD'"
        ).fetchone()[0]
        self.assertLessEqual(len(error), pull.ERROR_MAX_CHARS)
        self.assertNotIn("eyJsecret123", error)
        self.assertIn("Bearer [redacted]", error)

    def test_connect_adds_error_column_to_old_db(self):
        old = self.tmp / "old.db"
        raw = sqlite3.connect(old)
        raw.execute("CREATE TABLE pull_log (symbol TEXT NOT NULL, rows INTEGER, "
                    "first_date TEXT, last_date TEXT, status TEXT NOT NULL, pulled_at TEXT NOT NULL)")
        raw.commit()
        raw.close()
        conn = pull.connect(old)  # migration adds the column
        conn.close()
        conn = pull.connect(old)  # second run: column exists, no error
        cols = [row[1] for row in conn.execute("PRAGMA table_info(pull_log)")]
        conn.close()
        self.assertIn("error", cols)

    def test_auth_error_stops_run(self):
        client = FakeClient(TODAY - timedelta(days=9), TODAY,
                            fail={"NSE_EQ|INE000000001": UpstoxError("HTTP 401 from x -- bad")})
        with self.assertRaises(pull.AuthError):
            pull.run(client, self.conn, [("AAA", "INE000000001"), ("BBB", "INE000000004")],
                     10, TODAY, datetime(2026, 11, 1, 9))
        self.assertEqual(len(client.calls), 1)  # no retry, no move to next symbol

    def test_never_writes_to_history_db(self):
        # The pull target is only the db passed in; a second connection to a
        # different file sees nothing written.
        other = self.tmp / "history.db"
        client = FakeClient(TODAY - timedelta(days=4), TODAY)
        pull.run(client, self.conn, [("AAA", "INE000000001")], 5, TODAY,
                 datetime(2026, 11, 1, 9))
        self.assertFalse(other.exists())
        check = sqlite3.connect(self.db)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM candles").fetchone()[0], 5)
        check.close()


if __name__ == "__main__":
    unittest.main()
