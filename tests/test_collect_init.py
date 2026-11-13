"""collect.py init, the container-sources loader, serve skipping container sources, the
claim_requests SQL, and link_request_to_run wiring.

Offline: no Postgres. Database calls are replaced by fakes or mock connections. The live behaviour
of the claim SQL and of the request link still needs a check against Postgres.
"""
import argparse
import contextlib
import io
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest import mock

import psycopg
import pytz

import collect
from scanner.collect import first_run
from scanner.collect import scheduler
from scanner.collect import services
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


class _Source(sources_module.Source):
    def __init__(self, name):
        super().__init__(name)
        self.run_calls = 0

    def run(self, params, now=None, dry_run=False):
        self.run_calls += 1
        return {"fetched": 1, "new": 1, "from": None, "to": None, "message": ""}

    def plan(self, params, now=None):
        return {"fetched": 0, "new": 0, "from": None, "to": None, "message": ""}


class _Base(unittest.TestCase):
    """Fake collector_runs writes (rows keep the uuid the scheduler returned) and two sources."""

    def setUp(self):
        self.rows = []
        self.fake_src = _Source("fake_src")
        self.other_src = _Source("other_src")
        self._patch(collect.db, "connect", lambda *a, **k: _FakeConn())
        self._patch(scheduler, "try_lock", lambda conn, source: True)
        self._patch(scheduler, "unlock", lambda conn, source: None)
        self._patch(scheduler, "get_settings", lambda conn: {})
        self._patch(scheduler, "get_last_attempts", lambda conn: {})
        self._patch(scheduler, "is_running", lambda conn, source, timeout_seconds: False)
        self._patch(scheduler, "start_run", self._start_run)
        self._patch(scheduler, "finish_run", self._finish_run)
        self._patch(scheduler, "record_skipped", self._record_skipped)
        self._patch(collect_settings, "ensure_sources", lambda: [])
        self._patch(first_run, "tick", lambda now: "done")
        self._patch(collect, "_reported_container", set())
        patched = mock.patch.dict(sources_module.SOURCES,
                                  {"fake_src": self.fake_src, "other_src": self.other_src})
        patched.start()
        self.addCleanup(patched.stop)

    def _patch(self, target, attribute, new):
        p = mock.patch.object(target, attribute, new)
        p.start()
        self.addCleanup(p.stop)

    def _start_run(self, conn, source, trigger):
        run_id = uuid.uuid4()
        self.rows.append({"id": run_id, "source": source, "trigger": trigger, "status": "running"})
        return run_id

    def _finish_run(self, conn, run_id, status, fetched, new, from_date, to_date, message=""):
        for row in self.rows:
            if row["id"] == run_id:
                row["status"] = status

    def _record_skipped(self, conn, source, trigger, message):
        run_id = uuid.uuid4()
        self.rows.append({"id": run_id, "source": source, "trigger": trigger, "status": "skipped"})
        return run_id

    def _cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = collect.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def _serve_once(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            rc = collect.cmd_serve(argparse.Namespace(once=True, dry_run=False))
        return rc, err.getvalue()


class InitTests(_Base):
    def test_init_runs_the_three_duties_and_exits_0(self):
        ensure = mock.Mock(return_value=["fake_src"])
        tick = mock.Mock(return_value="done")
        split = mock.Mock(wraps=collect.split_registered)
        self._patch(collect_settings, "ensure_sources", ensure)
        self._patch(first_run, "tick", tick)
        self._patch(collect, "split_registered", split)
        settings_rows = {"fake_src": {"mode": "manual"}, "gone_src": {"mode": "manual"}}
        self._patch(scheduler, "get_settings", lambda conn: settings_rows)

        rc, _, err = self._cli(["init"])

        self.assertEqual(rc, 0)
        ensure.assert_called_once_with()
        tick.assert_called_once()
        self.assertIsInstance(tick.call_args[0][0], datetime)
        split.assert_called_once()
        self.assertIn("gone_src", err)  # a settings row with no collector is reported

    def test_init_twice_is_safe(self):
        self.assertEqual(self._cli(["init"])[0], 0)
        self.assertEqual(self._cli(["init"])[0], 0)

    def test_init_returns_3_when_postgres_raises(self):
        ensure = mock.Mock(return_value=[])
        self._patch(collect_settings, "ensure_sources", ensure)
        self._patch(collect.db, "connect", mock.Mock(side_effect=ConnectionError("refused")))

        rc, _, err = self._cli(["init"])

        self.assertEqual(rc, 3)
        self.assertIn("Postgres unreachable", err)
        ensure.assert_not_called()

    def test_init_returns_3_on_operational_error_during_registration(self):
        self._patch(collect_settings, "ensure_sources",
                    mock.Mock(side_effect=psycopg.OperationalError("server closed")))
        rc, _, _ = self._cli(["init"])
        self.assertEqual(rc, 3)

    def test_init_returns_1_on_other_failure(self):
        self._patch(collect_settings, "ensure_sources", mock.Mock(side_effect=ValueError("bad row")))
        rc, _, err = self._cli(["init"])
        self.assertEqual(rc, 1)
        self.assertIn("bad row", err)


class ServeContainerSkipTests(_Base):
    def setUp(self):
        super().setUp()
        self._patch(services, "load_container_sources", lambda path=None: {"fake_src"})
        self._patch(scheduler, "due_sources", lambda now, settings, last_runs: ["fake_src", "other_src"])
        self.claim = mock.Mock(return_value=[])
        self._patch(scheduler, "claim_requests", self.claim)

    def test_serve_skips_listed_source_and_runs_unlisted_one(self):
        rc, err = self._serve_once()
        self.assertEqual(rc, 0)
        self.assertEqual(self.fake_src.run_calls, 0)
        self.assertEqual(self.other_src.run_calls, 1)
        self.assertIn("runs in its own container", err)

    def test_serve_hands_container_sources_to_the_claim(self):
        self._serve_once()
        self.claim.assert_called_with(mock.ANY, {"fake_src"})

    def test_skip_is_logged_once_per_source(self):
        self._serve_once()
        rc, err = self._serve_once()
        self.assertEqual(rc, 0)
        self.assertEqual(err.count("fake_src"), 0)

    def test_malformed_services_file_runs_nothing(self):
        def broken(path=None):
            raise ValueError("config/collector_services.json: malformed JSON")

        self._patch(services, "load_container_sources", broken)
        rc, err = self._serve_once()
        self.assertEqual(rc, 1)
        self.assertEqual(self.fake_src.run_calls, 0)
        self.assertEqual(self.other_src.run_calls, 0)
        self.assertIn("malformed JSON", err)


class LinkRequestTests(_Base):
    def setUp(self):
        super().setUp()
        self._patch(services, "load_container_sources", lambda path=None: set())
        self.link = mock.Mock()
        self._patch(scheduler, "link_request_to_run", self.link)

    def test_manual_request_is_linked_to_the_run_it_started(self):
        request_id = uuid.uuid4()
        self._patch(scheduler, "due_sources", lambda now, settings, last_runs: [])
        self._patch(scheduler, "claim_requests",
                    lambda conn, exclude_sources=(): [{"id": request_id, "source": "fake_src", "collector_run": None}])

        rc, _ = self._serve_once()

        self.assertEqual(rc, 0)
        self.assertEqual(self.fake_src.run_calls, 1)
        self.link.assert_called_once()
        args = self.link.call_args[0]
        self.assertEqual(args[1], request_id)
        self.assertEqual(args[2], self.rows[0]["id"])
        self.assertEqual(self.rows[0]["trigger"], "manual")

    def test_scheduled_run_is_not_linked(self):
        self._patch(scheduler, "due_sources", lambda now, settings, last_runs: ["fake_src"])
        self._patch(scheduler, "claim_requests", lambda conn, exclude_sources=(): [])

        rc, _ = self._serve_once()

        self.assertEqual(rc, 0)
        self.assertEqual(self.fake_src.run_calls, 1)
        self.link.assert_not_called()

    def test_link_failure_is_logged_and_loop_continues(self):
        request_id = uuid.uuid4()
        self.link.side_effect = RuntimeError("write failed")
        self._patch(scheduler, "due_sources", lambda now, settings, last_runs: [])
        self._patch(scheduler, "claim_requests",
                    lambda conn, exclude_sources=(): [{"id": request_id, "source": "fake_src", "collector_run": None}])

        rc, err = self._serve_once()

        self.assertEqual(rc, 0)
        self.assertEqual(self.fake_src.run_calls, 1)
        self.assertIn("could not link request", err)

    def test_request_is_linked_before_the_source_runs(self):
        order = []
        request_id = uuid.uuid4()
        self.link.side_effect = lambda conn, rid, run_id: order.append(("link", rid, run_id))
        real_run = self.fake_src.run

        def traced_run(params, now=None, dry_run=False):
            order.append(("run",))
            return real_run(params, now)

        self.fake_src.run = traced_run
        outcome = collect.execute_source("fake_src", "manual", request_id=request_id)
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(order, [("link", request_id, self.rows[0]["id"]), ("run",)])

    def test_skipped_run_with_a_request_is_also_linked(self):
        request_id = uuid.uuid4()
        self._patch(scheduler, "try_lock", lambda conn, source: False)
        outcome = collect.execute_source("fake_src", "manual", request_id=request_id)
        self.assertEqual(outcome["status"], "skipped")
        self.assertEqual(outcome["reason"], "already_running")
        self.link.assert_called_once_with(mock.ANY, request_id, self.rows[0]["id"])
        self.assertEqual(self.fake_src.run_calls, 0)

    def test_execute_source_returns_the_run_id(self):
        outcome = collect.execute_source("fake_src", "manual")
        self.assertEqual(outcome["run_id"], self.rows[0]["id"])

    def test_skipped_outcome_also_returns_the_run_id(self):
        self._patch(scheduler, "try_lock", lambda conn, source: False)
        outcome = collect.execute_source("fake_src", "manual")
        self.assertEqual(outcome["status"], "skipped")
        self.assertEqual(outcome["run_id"], self.rows[0]["id"])


class ServicesLoaderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def _write(self, text):
        path = self.dir / "collector_services.json"
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_file_is_an_error(self):
        path = self.dir / "absent.json"
        with self.assertRaises(ValueError) as ctx:
            services.load_container_sources(path)
        self.assertIn(str(path), str(ctx.exception))

    def test_valid_file_gives_its_source_names(self):
        path = self._write('{"sources": {"candles_eod": {"service": "candles", "host": "upstox"}}}')
        self.assertEqual(services.load_container_sources(path), {"candles_eod"})

    def test_empty_sources_map_gives_empty_set(self):
        self.assertEqual(services.load_container_sources(self._write('{"sources": {}}')), set())

    def test_malformed_json_raises_naming_the_file(self):
        path = self._write("{not json")
        with self.assertRaises(ValueError) as ctx:
            services.load_container_sources(path)
        self.assertIn(str(path), str(ctx.exception))
        self.assertIn("malformed JSON", str(ctx.exception))

    def test_unknown_entry_key_is_rejected(self):
        path = self._write('{"sources": {"candles_eod": {"service": "candles", "exchange": "upstox"}}}')
        with self.assertRaises(ValueError) as ctx:
            services.load_container_sources(path)
        self.assertIn("exchange", str(ctx.exception))
        self.assertIn(str(path), str(ctx.exception))

    def test_wrong_top_level_shape_is_rejected(self):
        path = self._write('{"sources": ["candles_eod"]}')
        with self.assertRaises(ValueError) as ctx:
            services.load_container_sources(path)
        self.assertIn(str(path), str(ctx.exception))

    def test_committed_file_parses(self):
        self.assertIsInstance(services.load_container_sources(), set)


class ClaimRequestsSqlTests(unittest.TestCase):
    """No live Postgres here: check the SQL text and the mapped return with a mock connection."""

    def test_claims_one_request_per_source_in_one_statement(self):
        conn = mock.MagicMock()
        rows = [
            {"id": uuid.uuid4(), "source": "candles_eod", "collector_run": None},
            {"id": uuid.uuid4(), "source": "index_eod", "collector_run": None},
        ]
        conn.execute.return_value.fetchall.return_value = rows

        result = scheduler.claim_requests(conn)

        self.assertEqual(result, rows)
        self.assertEqual(conn.execute.call_count, 1)
        sql = conn.execute.call_args[0][0]
        self.assertIn("DISTINCT ON (source)", sql)
        self.assertIn("claimed_at IS NULL", sql)
        self.assertIn("ORDER BY source, requested_at", sql)
        self.assertIn("FOR UPDATE OF r SKIP LOCKED", sql)
        self.assertIn("WHERE id IN (SELECT id FROM locked)", sql)
        self.assertIn("RETURNING id, source, collector_run", sql)
        self.assertNotIn("LIMIT 1", sql)
        self.assertIn("source <> ALL(%s)", sql)
        self.assertEqual(conn.execute.call_args[0][1], ([],))

    def test_exclude_sources_is_passed_as_a_parameter(self):
        conn = mock.MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        scheduler.claim_requests(conn, ["candles_eod"])
        self.assertEqual(conn.execute.call_args[0][1], (["candles_eod"],))

    def test_claim_runs_inside_a_transaction(self):
        conn = mock.MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        scheduler.claim_requests(conn)
        conn.transaction.assert_called_once()


if __name__ == "__main__":
    unittest.main()
