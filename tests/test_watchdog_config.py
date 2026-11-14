"""Watchdog config: env defaults, token file reading, runtime limits, and the no-psycopg rule."""
import ast
import json
import tempfile
import unittest
from pathlib import Path

from scanner.watchdog import config as cfg

REPO = Path(__file__).resolve().parent.parent
CANARY = "CANARY-TOKEN-DO-NOT-LOG"


class LoadConfigTests(unittest.TestCase):
    def test_token_file_is_required(self):
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config({}, REPO)
        self.assertEqual(str(ctx.exception), "WATCHDOG_TOKEN_FILE is not set")

    def test_blank_token_file_is_required(self):
        with self.assertRaises(cfg.ConfigError):
            cfg.load_config({"WATCHDOG_TOKEN_FILE": "   "}, REPO)

    def test_defaults(self):
        c = cfg.load_config({"WATCHDOG_TOKEN_FILE": "/host/outside/token"}, REPO)
        self.assertEqual(c.api_base_url, "http://127.0.0.1:8081")
        self.assertEqual(c.server_health_url, "http://127.0.0.1:8081/api/health")
        self.assertEqual(c.ui_health_url, "http://127.0.0.1:8080/api/health")
        self.assertEqual(c.runtime_file, REPO / "config" / "collector_runtime.json")
        self.assertEqual(c.poll_interval_s, 60.0)
        self.assertEqual(c.health_interval_s, 30.0)
        self.assertEqual(c.http_timeout_s, 10.0)
        self.assertEqual(c.log_dir, REPO / "logs")
        self.assertEqual(c.repo_root, REPO)

    def test_overrides(self):
        env = {
            "WATCHDOG_TOKEN_FILE": "/host/token",
            "WATCHDOG_API_BASE_URL": "http://127.0.0.1:9999/",
            "WATCHDOG_SERVER_HEALTH_URL": "http://h/health",
            "WATCHDOG_UI_HEALTH_URL": "http://u/health",
            "WATCHDOG_RUNTIME_FILE": "/elsewhere/runtime.json",
            "WATCHDOG_POLL_S": "5",
            "WATCHDOG_HEALTH_S": "7.5",
            "WATCHDOG_HTTP_TIMEOUT_S": "2",
        }
        c = cfg.load_config(env, REPO)
        self.assertEqual(c.api_base_url, "http://127.0.0.1:9999")
        self.assertEqual(c.server_health_url, "http://h/health")
        self.assertEqual(c.ui_health_url, "http://u/health")
        self.assertEqual(c.runtime_file, Path("/elsewhere/runtime.json"))
        self.assertEqual(c.poll_interval_s, 5.0)
        self.assertEqual(c.health_interval_s, 7.5)
        self.assertEqual(c.http_timeout_s, 2.0)

    def test_server_health_defaults_from_overridden_api_base(self):
        env = {"WATCHDOG_TOKEN_FILE": "/t", "WATCHDOG_API_BASE_URL": "http://127.0.0.1:7000"}
        c = cfg.load_config(env, REPO)
        self.assertEqual(c.server_health_url, "http://127.0.0.1:7000/api/health")

    def test_bad_interval_raises_fixed_text(self):
        env = {"WATCHDOG_TOKEN_FILE": "/host/token", "WATCHDOG_POLL_S": "soon"}
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(env, REPO)
        self.assertIn("WATCHDOG_POLL_S", str(ctx.exception))
        self.assertNotIn("/host/token", str(ctx.exception))

    def test_non_positive_interval_rejected(self):
        env = {"WATCHDOG_TOKEN_FILE": "/t", "WATCHDOG_HEALTH_S": "0"}
        with self.assertRaises(cfg.ConfigError):
            cfg.load_config(env, REPO)


class ReadTokenTests(unittest.TestCase):
    def test_reads_stripped_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "token"
            p.write_text(f"  {CANARY}\n", encoding="utf-8")
            self.assertEqual(cfg.read_token(p), CANARY)

    def test_missing_file_raises_without_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "no_such_token"
            with self.assertRaises(cfg.ConfigError) as ctx:
                cfg.read_token(p)
        self.assertEqual(str(ctx.exception), "watchdog token file is missing or empty")
        self.assertNotIn(d, str(ctx.exception))

    def test_empty_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "token"
            p.write_text("  \n", encoding="utf-8")
            with self.assertRaises(cfg.ConfigError) as ctx:
                cfg.read_token(p)
        self.assertEqual(str(ctx.exception), "watchdog token file is missing or empty")


class LoadRuntimeTests(unittest.TestCase):
    def _write(self, d, obj):
        p = Path(d) / "runtime.json"
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
        return p

    def test_shipped_file_has_home_filings_330_and_default_1800(self):
        rt = cfg.load_runtime(REPO / "config" / "collector_runtime.json")
        self.assertEqual(rt.default_max_runtime_s, 1800)
        self.assertEqual(rt.max_runtime_s("home_filings"), 330)
        self.assertEqual(rt.max_runtime_s("some_other_source"), 1800)

    def test_missing_source_uses_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, {"default_max_runtime_s": 900, "sources": {"a": 60}})
            rt = cfg.load_runtime(p)
        self.assertEqual(rt.max_runtime_s("a"), 60)
        self.assertEqual(rt.max_runtime_s("b"), 900)

    def test_sources_key_optional(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, {"default_max_runtime_s": 900})
            rt = cfg.load_runtime(p)
        self.assertEqual(rt.max_runtime_s("x"), 900)

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "{not json")
            with self.assertRaises(cfg.ConfigError):
                cfg.load_runtime(p)

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(cfg.ConfigError):
                cfg.load_runtime(Path(d) / "absent.json")

    def test_bad_values_raise(self):
        bad = [
            {"default_max_runtime_s": 0},
            {"default_max_runtime_s": -5},
            {"default_max_runtime_s": "1800"},
            {"default_max_runtime_s": True},
            {"default_max_runtime_s": 1800, "sources": {"a": 0}},
            {"default_max_runtime_s": 1800, "sources": {"a": 1.5}},
            {"default_max_runtime_s": 1800, "sources": {"Bad-Name": 10}},
            {"default_max_runtime_s": 1800, "sources": []},
            [1, 2],
        ]
        for obj in bad:
            with self.subTest(obj=obj), tempfile.TemporaryDirectory() as d:
                p = self._write(d, obj)
                with self.assertRaises(cfg.ConfigError):
                    cfg.load_runtime(p)


class NoPsycopgTests(unittest.TestCase):
    def test_no_watchdog_module_imports_psycopg(self):
        pkg = REPO / "scanner" / "watchdog"
        files = sorted(pkg.glob("*.py"))
        self.assertTrue(files)
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    self.assertFalse(
                        name == "psycopg" or name.startswith("psycopg."),
                        f"{path.name} imports {name}",
                    )


if __name__ == "__main__":
    unittest.main()
