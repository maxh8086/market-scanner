"""record_coverage merge path, offline.

Regression: the merge read rows by position (row[0]) although scanner.pg.db
returns dict rows, and deleted with "from_date IN (%s)" given a Python list.
Either one raised on the second adjacent month, so later months were never
recorded. This fake connection returns dict rows, as Postgres does.
"""
from __future__ import annotations

import unittest
from datetime import date

from scanner.coverage import missing_windows, record_coverage


class _FakeConn:
    def __init__(self):
        self.rows: list[dict] = []  # {"feed", "from_date", "to_date"}

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("INSERT INTO feed_coverage"):
            feed, f, t = params
            self.rows.append({"feed": feed, "from_date": f, "to_date": t})
            return _Result([])
        if sql_norm.startswith("SELECT from_date, to_date FROM feed_coverage WHERE feed = %s AND NOT"):
            feed, lo, hi = params
            hit = [r for r in self.rows
                   if r["feed"] == feed and not (r["to_date"] < lo or r["from_date"] > hi)]
            return _Result(sorted(hit, key=lambda r: r["from_date"]))
        if sql_norm.startswith("DELETE FROM feed_coverage WHERE feed = %s AND from_date = ANY(%s)"):
            feed, froms = params
            # Postgres would reject a non-array right-hand side; a list means an array here.
            assert isinstance(froms, list), "ANY needs one array parameter"
            self.rows = [r for r in self.rows
                         if not (r["feed"] == feed and r["from_date"] in froms)]
            return _Result([])
        if sql_norm.startswith("SELECT from_date, to_date FROM feed_coverage WHERE feed = %s ORDER BY"):
            (feed,) = params
            return _Result(sorted((r for r in self.rows if r["feed"] == feed),
                                  key=lambda r: (r["from_date"], r["to_date"])))
        raise AssertionError(f"unexpected SQL: {sql_norm}")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class RecordCoverageMergeTest(unittest.TestCase):
    def test_adjacent_months_merge_into_one_window(self):
        conn = _FakeConn()
        record_coverage(conn, "announcements", date(2026, 1, 1), date(2026, 1, 31))
        record_coverage(conn, "announcements", date(2026, 2, 1), date(2026, 2, 28))
        record_coverage(conn, "announcements", date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(conn.rows, [{"feed": "announcements",
                                      "from_date": date(2026, 1, 1),
                                      "to_date": date(2026, 3, 31)}])

    def test_gap_after_merged_months_is_still_reported(self):
        conn = _FakeConn()
        record_coverage(conn, "announcements", date(2026, 1, 1), date(2026, 1, 31))
        record_coverage(conn, "announcements", date(2026, 2, 1), date(2026, 2, 28))
        self.assertEqual(
            missing_windows(conn, "announcements", date(2026, 1, 1), date(2026, 4, 30)),
            [(date(2026, 3, 1), date(2026, 4, 30))],
        )

    def test_other_feeds_are_untouched(self):
        conn = _FakeConn()
        record_coverage(conn, "corporate_actions", date(2026, 1, 1), date(2026, 1, 31))
        record_coverage(conn, "announcements", date(2026, 1, 1), date(2026, 1, 31))
        record_coverage(conn, "announcements", date(2026, 2, 1), date(2026, 2, 28))
        feeds = sorted(r["feed"] for r in conn.rows)
        self.assertEqual(feeds, ["announcements", "corporate_actions"])


if __name__ == "__main__":
    unittest.main()
