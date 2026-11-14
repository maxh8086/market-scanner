"""Watchdog main loop, health policy and max-runtime enforcement.

Fake runner, fake opener, fake clock, no sleep, no docker, no network. The one real DockerRunner
test uses a fake execute and a fake popen, so no docker command runs.
"""
import ast
import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scanner.watchdog import health, main as wd
from scanner.watchdog.config import RuntimeConfig, WatchdogConfig
from scanner.watchdog.docker_runner import DockerRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
CANARY = "CANARY-TOKEN-DO-NOT-LOG"
T0 = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)

API = "http://127.0.0.1:8081"
DUE_URL = API + "/internal/due"
FINISH_URL = API + "/internal/due/finish"
SERVER_HEALTH = API + "/api/health"
UI_HEALTH = "http://127.0.0.1:8080/api/health"


class Clock:
    def __init__(self, start=T0):
        self.now = start
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now = self.now + timedelta(seconds=seconds)

    def advance(self, seconds):
        self.now = self.now + timedelta(seconds=seconds)


class FakeHandle:
    """A Popen-like handle. finish_after=None means it never exits on its own."""

    def __init__(self, log, source, finish_after):
        self.log = log
        self.source = source
        self.finish_after = finish_after
        self.polls = 0
        self.exited = False

    def poll(self):
        self.polls += 1
        if self.finish_after is None or self.polls <= self.finish_after:
            return None
        if not self.exited:
            self.exited = True
            self.log.append(f"exit:{self.source}")
        return 0


class FakeRunner:
    def __init__(self):
        self.events = []
        self.starts = []
        self.handles = []
        self.running = set()
        self.containers = []
        self.started_at = {}
        self.stopped = []
        self.compose = []
        self.finish_after = 1
        self.stop_result = True

    def is_running(self, source):
        self.events.append(f"is_running:{source}")
        return source in self.running

    def remove_leftover(self, source):
        self.events.append(f"remove:{source}")

    def start(self, service, source, request_id):
        self.events.append(f"start:{source}")
        self.starts.append((service, source, request_id))
        handle = FakeHandle(self.events, source, self.finish_after)
        self.handles.append(handle)
        return handle

    def list_collector_containers(self):
        return list(self.containers)

    def container_started_at(self, source):
        return self.started_at.get(source)

    def stop(self, source):
        self.events.append(f"stop:{source}")
        self.stopped.append(source)
        return self.stop_result

    def compose_up(self, service):
        self.compose.append(service)
        return True


class FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code):
    return urllib.error.HTTPError(DUE_URL, code, "error", None, None)


class FakeOpener:
    """Routes by full URL. A route value is a response, or an exception instance to raise."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def __call__(self, request, timeout=None):
        if isinstance(request, str):
            url, method, headers, body = request, "GET", {}, None
        else:
            url, method = request.full_url, request.get_method()
            headers, body = dict(request.header_items()), request.data
        self.calls.append({"url": url, "method": method, "headers": headers, "body": body})
        result = self.routes[url]
        if isinstance(result, BaseException):
            raise result
        return result

    def count(self, url, method="GET"):
        return sum(1 for c in self.calls if c["url"] == url and c["method"] == method)


def due_body(*items):
    sources = []
    for order, (name, request_id) in enumerate(items):
        sources.append(
            {"name": name, "service": "collector", "reason": "slot", "request_id": request_id, "order": order}
        )
    return json.dumps({"sources": sources}).encode("utf-8")


def make_config(root):
    return WatchdogConfig(
        api_base_url=API,
        ui_health_url=UI_HEALTH,
        server_health_url=SERVER_HEALTH,
        token_file=root / "token",
        runtime_file=root / "config" / "collector_runtime.json",
        repo_root=root,
        poll_interval_s=60.0,
        health_interval_s=30.0,
        http_timeout_s=10.0,
        log_dir=root / "logs",
    )


class WatchdogTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.clock = Clock()
        self.opener = FakeOpener()
        self.runner = FakeRunner()
        self.runtime = RuntimeConfig(default_max_runtime_s=1800, sources={"home_filings": 330})
        self.stream = io.StringIO()
        self.logger = wd.configure_logging(None, self.stream, wd.Redactor())
        self.config = make_config(self.root)

    def tearDown(self):
        wd.configure_logging(None, io.StringIO(), wd.Redactor())  # closes the file handlers
        self._tmp.cleanup()

    def watchdog(self, token=CANARY):
        return wd.Watchdog(
            self.config,
            token,
            self.runner,
            self.runtime,
            now=self.clock,
            sleep=self.clock.sleep,
            opener=self.opener,
            logger=self.logger,
        )

    def log_text(self):
        return self.stream.getvalue()


class StartTests(WatchdogTestCase):
    def test_starts_only_due_sources_and_never_a_running_one(self):
        self.runner.running = {"a"}
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body(("a", None), ("b", None)))
        self.runner.finish_after = 0
        self.watchdog().poll_once()
        self.assertEqual([s for _, s, _ in self.runner.starts], ["b"])
        self.assertIn("already_running a", self.log_text())

    def test_remove_leftover_runs_before_start(self):
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body(("a", None)))
        self.runner.finish_after = 0
        self.watchdog().poll_once()
        events = self.runner.events
        self.assertLess(events.index("remove:a"), events.index("start:a"))

    def test_first_pass_is_sequential_in_server_order(self):
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body(("a", None), ("b", None)))
        self.runner.finish_after = 1
        self.watchdog().poll_once()
        events = self.runner.events
        self.assertEqual([s for _, s, _ in self.runner.starts], ["a", "b"])
        self.assertLess(events.index("exit:a"), events.index("start:b"))

    def test_later_passes_start_in_parallel_without_waiting(self):
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body(("a", None)))
        self.runner.finish_after = 0
        dog = self.watchdog()
        dog.poll_once()  # first pass: sequential
        self.runner.finish_after = None  # later handles never exit on their own
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body(("b", None), ("c", None)))
        sleeps_before = len(self.clock.sleeps)
        dog.poll_once()
        self.assertEqual([s for _, s, _ in self.runner.starts], ["a", "b", "c"])
        self.assertEqual(len(self.clock.sleeps), sleeps_before)
        for handle in self.runner.handles[1:]:
            self.assertEqual(handle.polls, 0)

    def test_request_id_reaches_the_run_command(self):
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body(("a", "req-42")))
        self.runner.finish_after = 0
        self.watchdog().poll_once()
        self.assertEqual(self.runner.starts, [("collector", "a", "req-42")])


class RunCommandTests(WatchdogTestCase):
    def test_compose_command_line_from_the_real_builder(self):
        popen_calls = []

        class Done:
            def poll(self):
                return 0

        def popen(args, **kwargs):
            popen_calls.append((list(args), kwargs))
            return Done()

        def execute(args, timeout_s):
            return 0, ""

        runner = DockerRunner(execute=execute, compose_dir=self.root, popen=popen)
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body(("a", "req-7")))
        dog = wd.Watchdog(
            self.config, CANARY, runner, self.runtime,
            now=self.clock, sleep=self.clock.sleep, opener=self.opener, logger=self.logger,
        )
        dog.poll_once()
        args, kwargs = popen_calls[0]
        self.assertIn("--no-deps", args)
        self.assertIn("--name", args)
        self.assertEqual(args[args.index("--name") + 1], "collector-a")
        self.assertEqual(args[args.index("--source") + 1], "a")
        self.assertEqual(args[args.index("--request-id") + 1], "req-7")
        self.assertIs(kwargs.get("shell", False), False)


class HealthTests(WatchdogTestCase):
    def test_restart_policy_backoff_sequence_is_1_5_15_15_minutes(self):
        policy = health.RestartPolicy()
        restarts = []
        for minute in range(0, 45):
            now = T0 + timedelta(minutes=minute)
            if policy.record("ui", False, now):
                restarts.append(minute)
        self.assertEqual(restarts, [2, 3, 8, 23, 38])

    def test_success_resets_the_episode(self):
        policy = health.RestartPolicy()
        for minute in range(0, 3):
            policy.record("server", False, T0 + timedelta(minutes=minute))
        policy.record("server", True, T0 + timedelta(minutes=3))
        self.assertEqual(policy.record("server", False, T0 + timedelta(minutes=4)), [])
        self.assertEqual(policy.record("server", False, T0 + timedelta(minutes=5)), [])
        self.assertEqual(
            policy.record("server", False, T0 + timedelta(minutes=6)),
            ["scanner-postgres", "server"],
        )

    def test_unknown_health_service_is_rejected(self):
        with self.assertRaises(ValueError):
            health.RestartPolicy().record("scanner-postgres", False, T0)

    def test_health_once_restarts_in_order_database_ui_server(self):
        self.opener.routes[UI_HEALTH] = FakeResponse(500)
        self.opener.routes[SERVER_HEALTH] = FakeResponse(500)
        dog = self.watchdog()
        dog.health_once()
        dog.health_once()
        self.assertEqual(self.runner.compose, [])
        self.clock.advance(30)
        dog.health_once()
        self.assertEqual(self.runner.compose, ["scanner-postgres", "ui", "server"])

    def test_check_http_treats_errors_as_unhealthy(self):
        self.assertTrue(health.check_http(UI_HEALTH, 5, opener=lambda u, timeout=None: FakeResponse(204)))
        self.assertFalse(health.check_http(UI_HEALTH, 5, opener=lambda u, timeout=None: FakeResponse(302)))

        def refused(url, timeout=None):
            raise OSError("refused")

        self.assertFalse(health.check_http(UI_HEALTH, 5, opener=refused))


class PostgresDownTests(WatchdogTestCase):
    def test_postgres_down_brings_up_only_the_database_and_is_rate_limited(self):
        self.opener.routes[DUE_URL] = http_error(503)
        dog = self.watchdog()
        dog.poll_once()
        dog.poll_once()  # same instant: rate-limited
        self.assertEqual(self.runner.compose, ["scanner-postgres"])
        self.assertEqual(self.runner.starts, [])
        self.assertIn("poll failed: postgres_down", self.log_text())


class FailedPollTests(WatchdogTestCase):
    def test_nothing_starts_on_any_failed_poll(self):
        cases = {
            "unauthorized": http_error(401),
            "api_unavailable_500": http_error(500),
            "timeout": TimeoutError("timed out"),
            "bad_response_json": FakeResponse(200, b"not json"),
            "bad_response_shape": FakeResponse(200, b'{"sources": [{"name": 1}]}'),
        }
        for kind, response in cases.items():
            with self.subTest(kind=kind):
                self.runner.starts.clear()
                self.runner.compose.clear()
                self.opener.routes[DUE_URL] = response
                self.watchdog().poll_once()
                self.assertEqual(self.runner.starts, [])
                self.assertEqual(self.runner.compose, [])
        self.assertIn("poll failed: unauthorized", self.log_text())
        self.assertIn("poll failed: api_unavailable", self.log_text())
        self.assertIn("poll failed: bad_response", self.log_text())


class MaxRuntimeTests(WatchdogTestCase):
    def _routes(self, finish_status=200):
        self.opener.routes[FINISH_URL] = FakeResponse(finish_status, b'{"finalised": 1}')

    def test_overrun_is_stopped_once_then_finished(self):
        self._routes()
        self.runner.containers = ["collector-home_filings", "collector-fast"]
        self.runner.started_at = {
            "home_filings": self.clock.now - timedelta(seconds=400),
            "fast": self.clock.now - timedelta(seconds=100),
        }
        dog = self.watchdog()
        dog.enforce_max_runtime()
        dog.enforce_max_runtime()
        self.assertEqual(self.runner.stopped, ["home_filings"])
        self.assertEqual(self.opener.count(FINISH_URL, "POST"), 1)
        finish = [c for c in self.opener.calls if c["url"] == FINISH_URL][0]
        self.assertEqual(json.loads(finish["body"]), {"source": "home_filings"})
        self.assertIn("killed home_filings after 400s", self.log_text())
        self.assertIn("finish_killed ok home_filings", self.log_text())

    def test_finish_failure_is_logged(self):
        self._routes(finish_status=500)
        self.runner.containers = ["collector-home_filings"]
        self.runner.started_at = {"home_filings": self.clock.now - timedelta(seconds=400)}
        self.watchdog().enforce_max_runtime()
        self.assertIn("finish_killed failed home_filings", self.log_text())

    def test_never_stops_anything_that_is_not_a_collector(self):
        self._routes()
        self.runner.containers = ["scanner-postgres", "server", "ui", "collector-home_filings"]
        self.runner.started_at = {
            "home_filings": self.clock.now - timedelta(seconds=400),
            "postgres": self.clock.now - timedelta(days=3),
            "server": self.clock.now - timedelta(days=3),
        }
        self.watchdog().enforce_max_runtime()
        self.assertEqual(self.runner.stopped, ["home_filings"])

    def test_a_new_container_instance_can_be_killed_again(self):
        self._routes()
        self.runner.containers = ["collector-home_filings"]
        self.runner.started_at = {"home_filings": self.clock.now - timedelta(seconds=400)}
        dog = self.watchdog()
        dog.enforce_max_runtime()
        self.runner.started_at = {"home_filings": self.clock.now - timedelta(seconds=10)}
        self.clock.advance(5)
        dog.enforce_max_runtime()
        self.runner.started_at = {"home_filings": self.clock.now - timedelta(seconds=500)}
        dog.enforce_max_runtime()
        self.assertEqual(self.runner.stopped, ["home_filings", "home_filings"])


class LoopTests(WatchdogTestCase):
    def test_unexpected_error_is_logged_by_class_and_the_loop_continues(self):
        class Boom(RuntimeError):
            pass

        def explode(source):
            raise Boom("secret detail")

        self.runner.is_running = explode
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body(("a", None)))
        self.opener.routes[UI_HEALTH] = FakeResponse(200)
        self.opener.routes[SERVER_HEALTH] = FakeResponse(200)
        dog = self.watchdog()
        dog.run_forever(max_ticks=3)
        self.assertIn("unexpected error: Boom", self.log_text())
        self.assertNotIn("secret detail", self.log_text())
        self.assertEqual(len(self.clock.sleeps), 3)

    def test_poll_and_health_follow_their_intervals(self):
        self.opener.routes[DUE_URL] = FakeResponse(200, due_body())
        self.opener.routes[UI_HEALTH] = FakeResponse(200)
        self.opener.routes[SERVER_HEALTH] = FakeResponse(200)
        self.watchdog().run_forever(max_ticks=61)
        self.assertEqual(self.opener.count(DUE_URL), 2)  # at t=0 and t=60
        self.assertEqual(self.opener.count(SERVER_HEALTH), 3)  # every 30 s: t=0, 30, 60

    def test_stop_flag_ends_the_loop(self):
        dog = self.watchdog()
        dog.stop()
        dog.run_forever()
        self.assertEqual(self.clock.sleeps, [])


class LogAndMainTests(WatchdogTestCase):
    def _write_runtime(self):
        cfg = self.root / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "collector_runtime.json").write_text(
            json.dumps({"default_max_runtime_s": 1800, "sources": {"home_filings": 330}}),
            encoding="utf-8",
        )

    def test_token_never_reaches_the_log_file_or_stderr(self):
        token_file = self.root / "token"
        token_file.write_text(CANARY + "\n", encoding="utf-8")
        self._write_runtime()
        self.opener.routes[DUE_URL] = http_error(401)
        self.opener.routes[UI_HEALTH] = FakeResponse(500)
        self.opener.routes[SERVER_HEALTH] = FakeResponse(500)
        self.opener.routes[FINISH_URL] = FakeResponse(500)
        self.runner.containers = ["collector-home_filings"]
        self.runner.started_at = {"home_filings": self.clock.now - timedelta(seconds=400)}
        stderr = io.StringIO()
        env = {"WATCHDOG_TOKEN_FILE": str(token_file)}
        with contextlib.redirect_stderr(stderr):
            code = wd.main(env=env, repo_root=self.root, runner=self.runner, opener=self.opener,
                           sleep=self.clock.sleep, now=self.clock, max_ticks=2)
        self.assertEqual(code, 0)
        log_file = self.root / "logs" / "watchdog.log"
        self.assertTrue(log_file.exists())
        self.assertNotIn(CANARY, log_file.read_text(encoding="utf-8"))
        self.assertNotIn(CANARY, stderr.getvalue())
        self.assertIn("poll failed: unauthorized", log_file.read_text(encoding="utf-8"))

    def test_main_exits_2_without_a_token_setting(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = wd.main(env={}, repo_root=self.root, runner=self.runner, max_ticks=1)
        self.assertEqual(code, 2)
        self.assertIn("WATCHDOG_TOKEN_FILE is not set", stderr.getvalue())
        self.assertEqual(self.runner.starts, [])

    def test_main_exits_2_when_the_token_file_is_empty(self):
        token_file = self.root / "token"
        token_file.write_text("   \n", encoding="utf-8")
        self._write_runtime()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = wd.main(env={"WATCHDOG_TOKEN_FILE": str(token_file)}, repo_root=self.root,
                           runner=self.runner, max_ticks=1)
        self.assertEqual(code, 2)
        self.assertNotIn(str(token_file), stderr.getvalue())

    def test_redactor_replaces_the_secret_in_any_message(self):
        redactor = wd.Redactor()
        redactor.secret = CANARY
        logger = wd.configure_logging(None, self.stream, redactor)
        logger.warning("value %s here", CANARY)
        self.assertNotIn(CANARY, self.log_text())
        self.assertIn(wd.REDACTED, self.log_text())


class ImportBoundaryTests(unittest.TestCase):
    def test_no_watchdog_module_imports_psycopg(self):
        package = REPO_ROOT / "scanner" / "watchdog"
        modules = sorted(package.glob("*.py"))
        self.assertTrue(modules)
        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    self.assertFalse(
                        name == "psycopg" or name.startswith("psycopg."),
                        f"{path.name} imports {name}",
                    )


if __name__ == "__main__":
    unittest.main()
