"""collect.execute_source and its callers: one run row per path, lock, skip rules, ok-only last runs.

Offline: no Postgres. The collector_runs writes are replaced by an in-memory store.
"""
import argparse
import contextlib
import io
import unittest
import uuid
from datetime import datetime
from unittest import mock

import pytz

import collect
from scanner.collect import first_run
from scanner.collect import scheduler
from scanner.collect import settings as collect_settings
from scanner.collect import sources as sources_module

NOW = datetime(2026, 11, 13, 4, 0, tzinfo=pytz.UTC)


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


class _FakeRuns:
    """In-memory stand-in for the collector_runs writes in scheduler.py."""

    def __init__(self):
        self.rows = []
        self.lock_ok = True
        self.unlocked = []

    def try_lock(self, conn, source):
        return self.lock_ok

    def unlock(self, conn, source):
        self.unlocked.append(source)

    def get_settings(self, conn):
        return {}

    def start_run(self, conn, source, trigger):
        self.rows.append({"source": source, "trigger": trigger, "status": "running", "message": ""})
        return len(self.rows) - 1

    def finish_run(self, conn, run_id, status, fetched, new, from_date, to_date, message=""):
        self.rows[run_id].update(status=status, message=message, fetched=fetched, new=new)

    def record_skipped(self, conn, source, trigger, message):
        self.rows.append({"source": source, "trigger": trigger, "status": "skipped", "message": message})
        return len(self.rows) - 1


class _FakeSource(sources_module.Source):
    def __init__(self, name="fake_src", fail=False):
        super().__init__(name)
        self.fail = fail
        self.run_calls = 0
        self.plan_calls = 0

    def run(self, params, now=None, dry_run=False):
        self.run_calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        return {"fetched": 3, "new": 2, "from": None, "to": None, "message": ""}

    def plan(self, params, now=None):
        self.plan_calls += 1
        return {"fetched": 0, "new": 0, "from": None, "to": None, "message": "would fetch 3 rows"}


class _FakeEventsSource(_FakeSource):
    events = True


class _CollectorTestCase(unittest.TestCase):
    def setUp(self):
        self.store = _FakeRuns()
        self.source = _FakeSource()
        self._patch(collect.db, "connect", lambda *a, **k: _FakeConn())
        self._patch(scheduler, "try_lock", self.store.try_lock)
        self._patch(scheduler, "unlock", self.store.unlock)
        self._patch(scheduler, "get_settings", self.store.get_settings)
        self._patch(scheduler, "start_run", self.store.start_run)
        self._patch(scheduler, "finish_run", self.store.finish_run)
        self._patch(scheduler, "record_skipped", self.store.record_skipped)
        patched = mock.patch.dict(sources_module.SOURCES, {"fake_src": self.source})
        patched.start()
        self.addCleanup(patched.stop)

    def _patch(self, target, attribute, new):
        p = mock.patch.object(target, attribute, new)
        p.start()
        self.addCleanup(p.stop)

    def _cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = collect.main(argv)
        return rc, out.getvalue(), err.getvalue()


class RunOnceTests(_CollectorTestCase):
    def test_unknown_source_is_rejected(self):
        rc, _, err = self._cli(["run-once", "--source", "no_such_source"])
        self.assertEqual(rc, 1)
        self.assertIn("unknown source: no_such_source", err)
        self.assertEqual(self.store.rows, [])

    def test_run_once_runs_one_source_and_writes_one_row(self):
        rc, _, _ = self._cli(["run-once", "--source", "fake_src"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.source.run_calls, 1)
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.store.rows[0]["status"], "ok")
        self.assertEqual(self.store.rows[0]["trigger"], "manual")
        self.assertEqual(self.store.unlocked, ["fake_src"])

    def test_run_also_writes_one_row(self):
        rc, _, _ = self._cli(["run", "fake_src"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.store.rows[0]["status"], "ok")

    def test_dry_run_is_honoured(self):
        rc, _, _ = self._cli(["run-once", "--source", "fake_src", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.source.run_calls, 0)
        self.assertEqual(self.source.plan_calls, 1)
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.store.rows[0]["status"], "skipped")
        self.assertTrue(self.store.rows[0]["message"].startswith("dry_run: would fetch"))

    def test_failed_run_writes_failed_row(self):
        self.source.fail = True
        rc, _, _ = self._cli(["run-once", "--source", "fake_src"])
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.store.rows[0]["status"], "failed")
        self.assertIn("provider down", self.store.rows[0]["message"])

    def test_trigger_accepts_schedule(self):
        outcome = collect.execute_source("fake_src", "schedule")
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(self.store.rows[0]["trigger"], "schedule")

    def test_trigger_rejects_other_values(self):
        with self.assertRaises(ValueError):
            collect.execute_source("fake_src", "bogus")
        with self.assertRaises(SystemExit):
            self._cli(["run-once", "--source", "fake_src", "--trigger", "bogus"])
        self.assertEqual(self.store.rows, [])

    def test_postgres_down_raises_and_writes_nothing(self):
        with mock.patch.object(collect.db, "connect", side_effect=OSError("refused")):
            with self.assertRaises(collect.PostgresUnavailable):
                collect.execute_source("fake_src", "manual")
            rc, _, err = self._cli(["run-once", "--source", "fake_src"])
        self.assertEqual(rc, 3)
        self.assertIn("Postgres unreachable", err)
        self.assertEqual(self.store.rows, [])


class LockTests(_CollectorTestCase):
    def test_lock_held_writes_skipped_already_running(self):
        self.store.lock_ok = False
        rc, _, _ = self._cli(["run-once", "--source", "fake_src"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.source.run_calls, 0)
        self.assertEqual(self.source.plan_calls, 0)
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.store.rows[0]["status"], "skipped")
        self.assertEqual(self.store.rows[0]["message"], "already_running")
        self.assertEqual(self.store.unlocked, [])


class EventsSourceTests(_CollectorTestCase):
    def setUp(self):
        super().setUp()
        self.events = _FakeEventsSource("events_src")
        patched = mock.patch.dict(sources_module.SOURCES, {"events_src": self.events})
        patched.start()
        self.addCleanup(patched.stop)

    def test_events_source_skipped_when_api_down(self):
        with mock.patch.object(collect, "api_is_up", return_value=False):
            outcome = collect.execute_source("events_src", "manual")
        self.assertEqual(outcome["status"], "skipped")
        self.assertEqual(outcome["reason"], "api_unavailable")
        self.assertEqual(self.events.run_calls, 0)
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.store.rows[0]["status"], "skipped")
        self.assertEqual(self.store.rows[0]["message"], "api_unavailable")

    def test_events_source_runs_when_api_up(self):
        with mock.patch.object(collect, "api_is_up", return_value=True):
            outcome = collect.execute_source("events_src", "manual")
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(self.events.run_calls, 1)
        self.assertEqual(self.store.rows[0]["status"], "ok")

    def test_non_events_source_does_not_check_api(self):
        check = mock.Mock(return_value=False)
        with mock.patch.object(collect, "api_is_up", check):
            outcome = collect.execute_source("fake_src", "manual")
        self.assertEqual(outcome["status"], "ok")
        check.assert_not_called()


class ApiHealthTests(unittest.TestCase):
    def test_api_is_up_true_on_200(self):
        with mock.patch.object(collect.requests, "get", return_value=mock.Mock(status_code=200)) as get:
            self.assertTrue(collect.api_is_up())
        self.assertTrue(get.call_args[0][0].endswith("/api/health"))

    def test_api_is_up_false_on_non_200(self):
        with mock.patch.object(collect.requests, "get", return_value=mock.Mock(status_code=503)):
            self.assertFalse(collect.api_is_up())

    def test_api_is_up_false_on_connection_error(self):
        with mock.patch.object(collect.requests, "get", side_effect=ConnectionError("refused")):
            self.assertFalse(collect.api_is_up())


class ServeTests(_CollectorTestCase):
    def test_serve_once_writes_one_row_for_due_source(self):
        self._patch(collect_settings, "ensure_sources", lambda: [])
        self._patch(first_run, "tick", lambda now: None)
        self._patch(scheduler, "get_last_runs", lambda conn: {})
        self._patch(scheduler, "get_last_attempts", lambda conn: {})
        self._patch(scheduler, "due_sources", lambda now, settings, last_runs: ["fake_src"])
        self._patch(scheduler, "claim_requests", lambda conn, exclude_sources=(): [])
        self._patch(scheduler, "is_running", lambda conn, source, timeout_seconds: False)
        rc = collect.cmd_serve(argparse.Namespace(once=True, dry_run=False))
        self.assertEqual(rc, 0)
        self.assertEqual(self.source.run_calls, 1)
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.store.rows[0]["status"], "ok")
        self.assertEqual(self.store.rows[0]["trigger"], "schedule")

    def _serve_with_attempt(self, started_at):
        # Yearly cron: the latest slot is Jan 1 of this year or last year, so any started_at
        # from the last few minutes is newer than the slot and the source is not due.
        self._patch(collect_settings, "ensure_sources", lambda: [])
        self._patch(first_run, "tick", lambda now: None)
        self._patch(scheduler, "get_settings",
                    lambda conn: {"fake_src": {"mode": "scheduled", "cron": "0 0 1 1 *", "params": {}}})
        self._patch(scheduler, "get_last_attempts", lambda conn: {"fake_src": started_at})
        self._patch(scheduler, "claim_requests", lambda conn, exclude_sources=(): [])
        self._patch(scheduler, "is_running", lambda conn, source, timeout_seconds: False)
        return collect.cmd_serve(argparse.Namespace(once=True, dry_run=False))

    def test_serve_does_not_rerun_source_after_recent_failed_attempt(self):
        # A failed run is still an attempt: it started after the latest slot, so it must not be re-run.
        self.source.fail = True
        recent = datetime.now(pytz.UTC).replace(microsecond=0)
        rc = self._serve_with_attempt(recent)
        self.assertEqual(rc, 0)
        self.assertEqual(self.source.run_calls, 0)
        self.assertEqual(self.store.rows, [])

    def test_serve_runs_source_when_last_attempt_is_before_slot(self):
        # Control for the test above: an attempt older than the latest slot leaves the source due.
        rc = self._serve_with_attempt(datetime(2000, 1, 1, tzinfo=pytz.UTC))
        self.assertEqual(rc, 0)
        self.assertEqual(self.source.run_calls, 1)


class RequestIdTests(_CollectorTestCase):
    def setUp(self):
        super().setUp()
        self.link = mock.Mock()
        self._patch(scheduler, "link_request_to_run", self.link)

    def test_run_once_request_id_is_passed_as_a_uuid(self):
        request_id = uuid.uuid4()
        rc, _, _ = self._cli(["run-once", "--source", "fake_src", "--request-id", str(request_id)])
        self.assertEqual(rc, 0)
        self.link.assert_called_once()
        self.assertIsInstance(self.link.call_args[0][1], uuid.UUID)
        self.assertEqual(self.link.call_args[0][1], request_id)
        self.assertEqual(self.link.call_args[0][2], 0)  # the run the fake store started

    def test_run_once_without_request_id_links_nothing(self):
        rc, _, _ = self._cli(["run-once", "--source", "fake_src"])
        self.assertEqual(rc, 0)
        self.link.assert_not_called()

    def test_bad_request_id_is_rejected_before_any_db_work(self):
        with mock.patch.object(collect.db, "connect", side_effect=AssertionError("no db")) as connect:
            rc, _, err = self._cli(["run-once", "--source", "fake_src", "--request-id", "not-a-uuid"])
        self.assertEqual(rc, 1)
        self.assertIn("--request-id must be a UUID", err)
        connect.assert_not_called()
        self.assertEqual(self.store.rows, [])
        self.link.assert_not_called()

    def test_run_has_no_request_id_option(self):
        with self.assertRaises(SystemExit):
            self._cli(["run", "fake_src", "--request-id", str(uuid.uuid4())])


class SchedulerSqlTests(unittest.TestCase):
    """The offline suite has no Postgres, so these check the SQL text and the mapping only.
    The live behaviour of the lock and the ok-only filter still needs a check against Postgres."""

    def test_get_last_runs_counts_only_ok_rows(self):
        conn = mock.Mock()
        conn.execute.return_value.fetchall.return_value = [{"source": "candles_eod", "started_at": NOW}]
        result = scheduler.get_last_runs(conn)
        sql = conn.execute.call_args[0][0]
        self.assertRegex(sql, r"WHERE\s+status\s*=\s*'ok'")
        self.assertEqual(result, {"candles_eod": NOW})

    def test_get_last_attempts_excludes_only_skipped_rows(self):
        conn = mock.Mock()
        conn.execute.return_value.fetchall.return_value = [{"source": "candles_eod", "started_at": NOW}]
        result = scheduler.get_last_attempts(conn)
        sql = conn.execute.call_args[0][0]
        self.assertRegex(sql, r"WHERE\s+status\s*<>\s*'skipped'")
        self.assertNotRegex(sql, r"status\s*=\s*'ok'")
        self.assertEqual(result, {"candles_eod": NOW})

    def test_try_lock_uses_spec_key_and_ends_transaction(self):
        conn = mock.Mock()
        conn.execute.return_value.fetchone.return_value = {"locked": True}
        self.assertTrue(scheduler.try_lock(conn, "candles_eod"))
        sql, params = conn.execute.call_args[0]
        self.assertIn("pg_try_advisory_lock(hashtext('collector:' || %s))", sql)
        self.assertEqual(params, ("candles_eod",))
        conn.commit.assert_called()

    def test_try_lock_false_when_held(self):
        conn = mock.Mock()
        conn.execute.return_value.fetchone.return_value = {"locked": False}
        self.assertFalse(scheduler.try_lock(conn, "candles_eod"))

    def test_list_runs_passes_skipped_rows_through(self):
        row = {"id": "x", "source": "candles_eod", "trigger": "manual", "started_at": NOW,
               "finished_at": NOW, "status": "skipped", "from_date": None, "to_date": None,
               "rows_fetched": 0, "rows_new": 0, "message": "already_running"}
        cm = mock.MagicMock()
        cm.__enter__.return_value.execute.return_value.fetchall.return_value = [row]
        with mock.patch.object(collect_settings.db, "connect", return_value=cm):
            result = collect_settings.list_runs()
        self.assertEqual(result[0]["status"], "skipped")
        self.assertEqual(result[0]["message"], "already_running")


if __name__ == "__main__":
    unittest.main()
