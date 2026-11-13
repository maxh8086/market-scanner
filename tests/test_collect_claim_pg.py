"""collector_requests claim, request link and per-source advisory lock against real Postgres.

The offline suites (test_collect_init, test_collect_execute) only check the SQL text. This module
runs scheduler.claim_requests, link_request_to_run, try_lock and unlock on a throwaway schema with
every migration applied (tests/pgschema.py). It skips, through pgschema, when Postgres is unreachable.
"""
import unittest
import uuid


class ClaimPgTests(unittest.TestCase):
    def setUp(self):
        from tests import pgschema
        from scanner.pg import db
        self.schema = pgschema.create(self)
        self.db = db
        # Unique names: advisory locks are database-wide, so fixed names could clash with a live run.
        self.a = f"pgt_a_{uuid.uuid4().hex[:10]}"
        self.b = f"pgt_b_{uuid.uuid4().hex[:10]}"
        with db.connect() as conn:
            for source in (self.a, self.b):
                conn.execute("INSERT INTO collector_sources (source) VALUES (%s)", (source,))
                conn.execute(
                    "INSERT INTO collector_settings (source, mode, cron) VALUES (%s, 'manual', '0 0 1 1 *')",
                    (source,))
            conn.commit()

    def _request(self, conn, source):
        request_id = uuid.uuid4()
        conn.execute("INSERT INTO collector_requests (id, source) VALUES (%s, %s)", (request_id, source))
        conn.commit()
        return request_id

    def _claimed_at(self, conn, request_id):
        return conn.execute(
            "SELECT claimed_at FROM collector_requests WHERE id = %s", (request_id,)).fetchone()["claimed_at"]

    def test_claim_returns_one_row_per_source(self):
        from scanner.collect import scheduler
        with self.db.connect() as conn:
            ra = self._request(conn, self.a)
            rb = self._request(conn, self.b)
            rows = [r for r in scheduler.claim_requests(conn) if r["source"] in (self.a, self.b)]
            self.assertEqual(sorted(r["source"] for r in rows), sorted([self.a, self.b]))
            self.assertEqual({r["id"] for r in rows}, {ra, rb})
            self.assertIsNotNone(self._claimed_at(conn, ra))
            self.assertIsNotNone(self._claimed_at(conn, rb))

    def test_excluded_source_stays_open(self):
        from scanner.collect import scheduler
        with self.db.connect() as conn:
            ra = self._request(conn, self.a)
            rb = self._request(conn, self.b)
            rows = [r for r in scheduler.claim_requests(conn, [self.a]) if r["source"] in (self.a, self.b)]
            self.assertEqual([r["source"] for r in rows], [self.b])
            self.assertEqual(rows[0]["id"], rb)
            self.assertIsNone(self._claimed_at(conn, ra))
            self.assertIsNotNone(self._claimed_at(conn, rb))

    def test_second_claim_returns_nothing_for_claimed_rows(self):
        from scanner.collect import scheduler
        with self.db.connect() as conn:
            self._request(conn, self.a)
            self._request(conn, self.b)
            first = [r for r in scheduler.claim_requests(conn) if r["source"] in (self.a, self.b)]
            second = [r for r in scheduler.claim_requests(conn) if r["source"] in (self.a, self.b)]
            self.assertEqual(len(first), 2)
            self.assertEqual(second, [])

    def test_link_sets_run_and_claimed_at_on_unclaimed_row(self):
        from scanner.collect import scheduler
        with self.db.connect() as conn:
            rid = self._request(conn, self.a)
            run_id = scheduler.start_run(conn, self.a, "manual")
            scheduler.link_request_to_run(conn, rid, run_id)
            row = conn.execute(
                "SELECT collector_run, claimed_at FROM collector_requests WHERE id = %s", (rid,)).fetchone()
            self.assertEqual(row["collector_run"], run_id)
            self.assertIsNotNone(row["claimed_at"])

    def test_link_keeps_the_claim_time_of_a_serve_claimed_row(self):
        from scanner.collect import scheduler
        with self.db.connect() as conn:
            rid = self._request(conn, self.a)
            scheduler.claim_requests(conn)
            claimed = self._claimed_at(conn, rid)
            run_id = scheduler.start_run(conn, self.a, "manual")
            scheduler.link_request_to_run(conn, rid, run_id)
            self.assertEqual(self._claimed_at(conn, rid), claimed)

    def test_advisory_lock_is_exclusive_until_unlock(self):
        from scanner.collect import scheduler
        conn1 = self.db.connect()
        conn2 = self.db.connect()
        try:
            self.assertTrue(scheduler.try_lock(conn1, self.a))
            self.assertFalse(scheduler.try_lock(conn2, self.a))
            scheduler.unlock(conn1, self.a)
            self.assertTrue(scheduler.try_lock(conn2, self.a))
            scheduler.unlock(conn2, self.a)
        finally:
            conn1.close()
            conn2.close()


if __name__ == "__main__":
    unittest.main()
