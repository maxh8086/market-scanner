"""Source cooldown adapter (scanner/collect/cooldown.py, PgCooldown) and its SQL contract.

FakeConnectionTests run offline: a fake connection records the SQL and parameters, so the
validation, the strict boundary, the one-transaction-per-call shape and fail-closed behaviour are
checked without a database.

RealPostgresTests run the same adapter on a throwaway schema with every migration applied
(tests/pgschema.py, including 049) and prove the SQL semantics: keep the later cooldown, NULL after
reset, the host CHECK and the timestamptz round trip. It skips, through pgschema, when Postgres is
unreachable.
"""
import unittest
from datetime import datetime, timedelta, timezone

T = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
ONE_HOUR = timedelta(hours=1)


def _cooldown_module():
    from scanner.collect import cooldown
    return cooldown


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    """Context manager that records every execute and whether __exit__ saw an exception."""

    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.executed = []
        self.enter_count = 0
        self.exit_count = 0
        self.exit_saw_exception = False

    def __enter__(self):
        self.enter_count += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exit_count += 1
        self.exit_saw_exception = exc_type is not None
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.error is not None:
            raise self.error
        return _FakeResult(self.row)


class _FakeFactory:
    """Zero-argument connection factory that counts how often it is called."""

    def __init__(self, conn):
        self.conn = conn
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.conn


def _normal_sql(sql):
    return " ".join(sql.split()).upper()


class FakeConnectionTests(unittest.TestCase):
    def _adapter(self, row=None, error=None):
        cooldown = _cooldown_module()
        conn = _FakeConn(row=row, error=error)
        factory = _FakeFactory(conn)
        return cooldown.PgCooldown(connect=factory), conn, factory

    def test_block_until_is_now_plus_one_hour_with_reason(self):
        adapter, conn, _ = self._adapter()
        adapter.block("nse", T, "http_429")
        self.assertEqual(len(conn.executed), 1)
        _, params = conn.executed[0]
        self.assertIn(T + ONE_HOUR, params)
        self.assertIn("http_429", params)

    def test_block_is_one_upsert_statement(self):
        adapter, conn, _ = self._adapter()
        adapter.block("nse", T, "http_403")
        self.assertEqual(len(conn.executed), 1)
        sql, _ = conn.executed[0]
        normalised = " ".join(sql.split())
        self.assertIn("ON CONFLICT (host)", normalised)
        self.assertIn("GREATEST", normalised)

    def test_active_true_one_second_before_expiry(self):
        adapter, _, _ = self._adapter(row={"cooldown_until": T + timedelta(seconds=1)})
        self.assertTrue(adapter.active("nse", T))

    def test_active_false_exactly_at_expiry(self):
        adapter, _, _ = self._adapter(row={"cooldown_until": T})
        self.assertFalse(adapter.active("nse", T))

    def test_active_false_one_second_after_expiry(self):
        adapter, _, _ = self._adapter(row={"cooldown_until": T - timedelta(seconds=1)})
        self.assertFalse(adapter.active("nse", T))

    def test_active_false_without_row_or_with_null_cooldown(self):
        adapter, _, _ = self._adapter(row=None)
        self.assertFalse(adapter.active("nse", T))
        adapter, _, _ = self._adapter(row={"cooldown_until": None})
        self.assertFalse(adapter.active("nse", T))

    def test_active_issues_only_a_select(self):
        adapter, conn, _ = self._adapter(row={"cooldown_until": T + ONE_HOUR})
        adapter.active("nse", T)
        self.assertEqual(len(conn.executed), 1)
        sql, _ = conn.executed[0]
        normalised = _normal_sql(sql)
        self.assertTrue(normalised.startswith("SELECT"))
        for word in ("INSERT", "UPDATE", "DELETE"):
            self.assertNotIn(word, normalised)

    def test_reset_issues_one_update_clearing_the_host(self):
        adapter, conn, _ = self._adapter(row=None)
        adapter.reset("nse")
        self.assertEqual(len(conn.executed), 1)
        sql, params = conn.executed[0]
        normalised = _normal_sql(sql)
        self.assertIn("UPDATE SOURCE_COOLDOWN", normalised)
        self.assertIn("COOLDOWN_UNTIL = NULL", normalised)
        self.assertIn("nse", params)

    def test_reset_on_unknown_host_does_not_raise(self):
        adapter, conn, _ = self._adapter(row=None)
        adapter.reset("never_blocked")
        self.assertEqual(len(conn.executed), 1)

    def test_naive_now_rejected_before_connecting(self):
        naive = datetime(2026, 11, 14, 12, 0)
        adapter, _, factory = self._adapter()
        with self.assertRaises(ValueError):
            adapter.active("nse", naive)
        self.assertEqual(factory.calls, 0)
        adapter, _, factory = self._adapter()
        with self.assertRaises(ValueError):
            adapter.block("nse", naive, "http_403")
        self.assertEqual(factory.calls, 0)

    def test_invalid_host_rejected_before_connecting(self):
        calls = {
            "active": lambda a, h: a.active(h, T),
            "block": lambda a, h: a.block(h, T, "http_403"),
            "reset": lambda a, h: a.reset(h),
        }
        for bad in ("", " nse", "NSE"):
            for name, call in calls.items():
                with self.subTest(host=bad, method=name):
                    adapter, _, factory = self._adapter()
                    with self.assertRaises(ValueError):
                        call(adapter, bad)
                    self.assertEqual(factory.calls, 0)

    def test_db_errors_propagate_fail_closed(self):
        boom = RuntimeError("db down")
        calls = {
            "active": lambda a: a.active("nse", T),
            "block": lambda a: a.block("nse", T, "http_403"),
            "reset": lambda a: a.reset("nse"),
        }
        for name, call in calls.items():
            with self.subTest(method=name):
                adapter, conn, _ = self._adapter(error=boom)
                with self.assertRaises(RuntimeError):
                    call(adapter)
                self.assertTrue(conn.exit_saw_exception)

    def test_one_transaction_per_call(self):
        calls = {
            "active": lambda a: a.active("nse", T),
            "block": lambda a: a.block("nse", T, "http_403"),
            "reset": lambda a: a.reset("nse"),
        }
        for name, call in calls.items():
            with self.subTest(method=name):
                adapter, conn, factory = self._adapter(row={"cooldown_until": None})
                call(adapter)
                self.assertEqual(factory.calls, 1)
                self.assertEqual(conn.enter_count, 1)
                self.assertEqual(conn.exit_count, 1)
                self.assertFalse(conn.exit_saw_exception)

    def test_cooldown_constant_is_one_hour(self):
        cooldown = _cooldown_module()
        self.assertEqual(cooldown.COOLDOWN, timedelta(hours=1))


class RealPostgresTests(unittest.TestCase):
    def setUp(self):
        from tests import pgschema
        from scanner.pg import db
        self.schema = pgschema.create(self)
        import psycopg
        from scanner.collect import cooldown
        self.psycopg = psycopg
        self.db = db
        self.cooldown = cooldown
        self.cd = cooldown.PgCooldown(connect=db.connect)

    def _row(self, host):
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT cooldown_until, reason FROM source_cooldown WHERE host = %s", (host,)).fetchone()

    def test_table_exists_and_host_check_enforced(self):
        insert = ("INSERT INTO source_cooldown (host, cooldown_until, reason, updated_at) "
                  "VALUES (%s, %s, %s, %s)")
        with self.db.connect() as conn:
            conn.execute(insert, ("nse", T, "http_403", T))
        self.assertIsNotNone(self._row("nse"))
        for bad in ("NSE", ""):
            with self.subTest(host=bad):
                with self.assertRaises(self.psycopg.errors.CheckViolation):
                    with self.db.connect() as conn:
                        conn.execute(insert, (bad, T, "http_403", T))

    def test_active_window_is_one_hour_strict(self):
        self.cd.block("nse", T, "http_429")
        self.assertTrue(self.cd.active("nse", T + timedelta(minutes=59, seconds=59)))
        self.assertFalse(self.cd.active("nse", T + ONE_HOUR))
        self.assertFalse(self.cd.active("nse", T + ONE_HOUR + timedelta(seconds=1)))

    def test_block_creates_row_with_reason(self):
        self.assertFalse(self.cd.active("nse", T))
        self.cd.block("nse", T, "block_page")
        row = self._row("nse")
        self.assertEqual(row["reason"], "block_page")
        self.assertEqual(row["cooldown_until"], T + ONE_HOUR)
        self.assertTrue(self.cd.active("nse", T + timedelta(minutes=1)))

    def test_later_block_extends_to_later_until_and_takes_its_reason(self):
        self.cd.block("nse", T, "http_403")
        self.cd.block("nse", T + timedelta(minutes=10), "http_429")
        row = self._row("nse")
        self.assertEqual(row["cooldown_until"], T + timedelta(hours=1, minutes=10))
        self.assertEqual(row["reason"], "http_429")

    def test_earlier_block_never_shortens_and_keeps_its_reason(self):
        self.cd.block("nse", T, "http_403")
        self.cd.block("nse", T - timedelta(minutes=30), "block_page")
        row = self._row("nse")
        self.assertEqual(row["cooldown_until"], T + ONE_HOUR)
        self.assertEqual(row["reason"], "http_403")

    def test_block_after_expiry_starts_fresh_hour_and_updates_reason(self):
        self.cd.block("nse", T, "http_403")
        self.cd.block("nse", T + timedelta(hours=2), "http_429")
        row = self._row("nse")
        self.assertEqual(row["cooldown_until"], T + timedelta(hours=3))
        self.assertEqual(row["reason"], "http_429")

    def test_reset_clears_expired_cooldown_and_keeps_row(self):
        self.cd.block("nse", T, "http_403")
        self.cd.reset("nse", T + ONE_HOUR)
        self.assertFalse(self.cd.active("nse", T + ONE_HOUR + timedelta(minutes=1)))
        row = self._row("nse")
        self.assertIsNotNone(row)
        self.assertIsNone(row["cooldown_until"])

    def test_reset_does_not_erase_an_unexpired_block(self):
        # Container B blocks while container A is finishing its cycle; A's reset must keep it.
        self.cd.block("nse", T, "http_403")
        self.cd.reset("nse", T + timedelta(minutes=10))
        row = self._row("nse")
        self.assertEqual(row["cooldown_until"], T + ONE_HOUR)
        self.assertEqual(row["reason"], "http_403")
        self.assertTrue(self.cd.active("nse", T + timedelta(minutes=10)))

    def test_reset_unknown_host_does_not_raise(self):
        self.cd.reset("never_blocked")
        self.assertIsNone(self._row("never_blocked"))

    def test_block_after_reset_starts_fresh_hour(self):
        self.cd.block("nse", T, "http_403")
        self.cd.reset("nse", T + ONE_HOUR)
        self.cd.block("nse", T + ONE_HOUR + timedelta(minutes=10), "http_429")
        self.assertEqual(self._row("nse")["cooldown_until"],
                         T + ONE_HOUR + timedelta(hours=1, minutes=10))

    def test_hosts_are_independent(self):
        self.cd.block("nse", T, "http_403")
        self.assertFalse(self.cd.active("other", T + timedelta(minutes=1)))
        self.cd.reset("other")
        self.assertTrue(self.cd.active("nse", T + timedelta(minutes=1)))

    def test_two_instances_end_at_later_until_in_either_order(self):
        other = self.cooldown.PgCooldown(connect=self.db.connect)
        # later block first, then earlier
        self.cd.block("nse", T + timedelta(minutes=30), "http_429")
        other.block("nse", T, "http_403")
        self.assertEqual(self._row("nse")["cooldown_until"], T + timedelta(hours=1, minutes=30))
        # earlier block first, then later
        other.block("other", T, "http_403")
        self.cd.block("other", T + timedelta(minutes=30), "http_429")
        self.assertEqual(self._row("other")["cooldown_until"], T + timedelta(hours=1, minutes=30))

    def test_timestamptz_round_trip_is_aware_and_exact(self):
        self.cd.block("nse", T, "http_403")
        stored = self._row("nse")["cooldown_until"]
        self.assertIsNotNone(stored.tzinfo)
        self.assertEqual(stored, T + ONE_HOUR)
        with self.db.connect() as conn:
            same = conn.execute(
                "SELECT cooldown_until = %s AS same FROM source_cooldown WHERE host = %s",
                (T + ONE_HOUR, "nse")).fetchone()["same"]
        self.assertTrue(same)


if __name__ == "__main__":
    unittest.main()
