"""Watchdog docker runner: exact command builders, parsing, and the collector-only stop rule.

No real docker is called: the execute and popen seams are fakes.
"""
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scanner.watchdog import docker_runner as dr

COMPOSE_DIR = Path("C:/repo/market-scanner")
CANARY = "CANARY-TOKEN-DO-NOT-LOG"


class FakeExecute:
    def __init__(self, rc=0, out=""):
        self.rc = rc
        self.out = out
        self.calls = []

    def __call__(self, args, timeout_s):
        self.calls.append((list(args), timeout_s))
        return self.rc, self.out


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        return "handle"


class ContainerNameTests(unittest.TestCase):
    def test_name(self):
        self.assertEqual(dr.container_name("home_filings"), "collector-home_filings")

    def test_invalid_source_rejected(self):
        for bad in ("", "Home", "a-b", "a b", "../x", "a;rm", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dr.container_name(bad)


class BuildRunArgsTests(unittest.TestCase):
    def setUp(self):
        self.runner = dr.DockerRunner(execute=FakeExecute(), compose_dir=COMPOSE_DIR)

    def test_exact_args_without_request_id(self):
        args = self.runner.build_run_args("collector_home", "home_filings", None)
        self.assertEqual(args, [
            "docker", "compose", "--project-directory", str(COMPOSE_DIR),
            "--profile", "collectors", "run", "--rm", "--no-deps",
            "--name", "collector-home_filings", "collector_home",
            "--source", "home_filings",
        ])

    def test_exact_args_with_request_id(self):
        args = self.runner.build_run_args("collector_home", "home_filings", "req-42")
        self.assertEqual(args[-4:], ["--source", "home_filings", "--request-id", "req-42"])
        self.assertEqual(args.count("--source"), 1)
        self.assertEqual(args.count("home_filings"), 1)

    def test_bad_service_rejected(self):
        with self.assertRaises(ValueError):
            self.runner.build_run_args("svc; rm -rf", "home_filings", None)

    def test_bad_source_rejected(self):
        with self.assertRaises(ValueError):
            self.runner.build_run_args("collector_home", "Home", None)


class IsRunningTests(unittest.TestCase):
    def test_true_when_name_listed(self):
        ex = FakeExecute(out="collector-home_filings\n")
        self.assertTrue(dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).is_running("home_filings"))
        args = ex.calls[0][0]
        self.assertEqual(args[:2], ["docker", "ps"])
        self.assertIn("name=^/collector-home_filings$", args)
        self.assertIn("{{.Names}}", args)

    def test_false_when_absent_or_prefix_only(self):
        ex = FakeExecute(out="collector-home_filings_old\n")
        self.assertFalse(dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).is_running("home_filings"))
        ex2 = FakeExecute(out="")
        self.assertFalse(dr.DockerRunner(execute=ex2, compose_dir=COMPOSE_DIR).is_running("home_filings"))


class RemoveLeftoverTests(unittest.TestCase):
    def test_rm_force(self):
        ex = FakeExecute(rc=1)
        dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).remove_leftover("home_filings")
        self.assertEqual(ex.calls[0][0], ["docker", "rm", "-f", "collector-home_filings"])


class StartTests(unittest.TestCase):
    def test_popen_gets_list_args_no_shell_and_devnull_output(self):
        pop = FakePopen()
        runner = dr.DockerRunner(execute=FakeExecute(), compose_dir=COMPOSE_DIR, popen=pop)
        handle = runner.start("collector_home", "home_filings", "req-1")
        self.assertEqual(handle, "handle")
        args, kwargs = pop.calls[0]
        self.assertEqual(args, runner.build_run_args("collector_home", "home_filings", "req-1"))
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)


class StartedAtTests(unittest.TestCase):
    def test_parses_nanoseconds_truncated(self):
        ex = FakeExecute(out="2026-11-14T10:00:00.123456789Z\n")
        got = dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).container_started_at("home_filings")
        self.assertEqual(got, datetime(2026, 11, 14, 10, 0, 0, 123456, tzinfo=timezone.utc))
        self.assertEqual(ex.calls[0][0], ["docker", "inspect", "-f", "{{.State.StartedAt}}", "collector-home_filings"])

    def test_parses_without_fraction_and_offset(self):
        ex = FakeExecute(out="2026-11-14T10:00:00+05:30")
        got = dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).container_started_at("home_filings")
        self.assertEqual(got.utcoffset(), timedelta(hours=5, minutes=30))

    def test_none_on_error_or_garbage(self):
        self.assertIsNone(dr.DockerRunner(execute=FakeExecute(rc=1, out="x"), compose_dir=COMPOSE_DIR)
                          .container_started_at("home_filings"))
        self.assertIsNone(dr.DockerRunner(execute=FakeExecute(out="yesterday"), compose_dir=COMPOSE_DIR)
                          .container_started_at("home_filings"))

    def test_none_for_invalid_date_values(self):
        ex = FakeExecute(out="2026-13-45T99:99:99Z")
        self.assertIsNone(dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).container_started_at("home_filings"))


class StopTests(unittest.TestCase):
    def test_stop_collector_container(self):
        ex = FakeExecute(rc=0)
        self.assertTrue(dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).stop("home_filings"))
        self.assertEqual(ex.calls[0][0], ["docker", "stop", "collector-home_filings"])

    def test_stop_false_on_nonzero_rc(self):
        self.assertFalse(dr.DockerRunner(execute=FakeExecute(rc=1), compose_dir=COMPOSE_DIR).stop("home_filings"))

    def test_stop_only_ever_targets_collector_names(self):
        ex = FakeExecute(rc=0)
        runner = dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR)
        # Hyphenated service names and anything not a plain source are rejected outright.
        for name in ("scanner-postgres", "collector-x", "", "../ui", "ui;x"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.stop(name)
        self.assertEqual(ex.calls, [])
        # A source named like a core service still maps to the collector container only.
        for name in ("server", "ui", "scanner_postgres"):
            runner.stop(name)
        stopped = [args[2] for args, _ in ex.calls]
        self.assertEqual(stopped, ["collector-server", "collector-ui", "collector-scanner_postgres"])
        for target in stopped:
            self.assertTrue(target.startswith("collector-"))


class ListCollectorContainersTests(unittest.TestCase):
    def test_returns_only_collector_names(self):
        out = "collector-home_filings\nserver\nscanner-postgres\ncollector-index_eod\n\n"
        ex = FakeExecute(out=out)
        names = dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).list_collector_containers()
        self.assertEqual(names, ["collector-home_filings", "collector-index_eod"])
        self.assertIn("name=^/collector-", ex.calls[0][0])

    def test_empty_on_error(self):
        ex = FakeExecute(rc=1, out="collector-x\n")
        self.assertEqual(dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).list_collector_containers(), [])


class ComposeUpTests(unittest.TestCase):
    def test_compose_up_args(self):
        ex = FakeExecute(rc=0)
        self.assertTrue(dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR).compose_up("scanner-postgres"))
        self.assertEqual(ex.calls[0][0], [
            "docker", "compose", "--project-directory", str(COMPOSE_DIR), "up", "-d", "scanner-postgres",
        ])

    def test_compose_up_false_on_failure(self):
        self.assertFalse(dr.DockerRunner(execute=FakeExecute(rc=1), compose_dir=COMPOSE_DIR).compose_up("ui"))

    def test_bad_service_rejected_without_calling_docker(self):
        ex = FakeExecute(rc=0)
        runner = dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR)
        for bad in ("", "UI", "a b", "x;y", "../x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                runner.compose_up(bad)
        self.assertEqual(ex.calls, [])


class TokenSecrecyTests(unittest.TestCase):
    def test_runner_never_places_secret_in_args(self):
        # The runner has no token input; a canary only proves nothing reaches its args by accident.
        ex = FakeExecute(out="")
        runner = dr.DockerRunner(execute=ex, compose_dir=COMPOSE_DIR)
        runner.is_running("home_filings")
        runner.list_collector_containers()
        for args, _ in ex.calls:
            self.assertNotIn(CANARY, " ".join(args))


class DefaultExecuteTests(unittest.TestCase):
    def test_missing_binary_returns_failure_without_raising(self):
        rc, out = dr.default_execute(["watchdog-no-such-binary-xyz"], 5)
        self.assertNotEqual(rc, 0)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
