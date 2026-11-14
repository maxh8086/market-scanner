"""Compose wiring tests for the server service (S3 container).

Parses docker-compose.yml at the repo root and checks that:
- the server service exists and takes no .env file (DB logins and tokens never come from .env);
- its only secret mount is the single home-events ingest token file, read-only and required;
- it has no mount of the master key folder;
- its environment, loopback-only port, healthcheck, restart policy, networks and build are right;
- the ui service keeps its existing mounts;
- start.ps1 brings up ui, collector and server together;
- the server Dockerfile never copies env or secret files and runs as the node user;
- env.template documents the ingest token variable.
"""

import pathlib
import re
import unittest

from tests.test_compose_llm_network import _load_compose, _service_networks

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
START_PS1_PATH = REPO_ROOT / "start.ps1"
SERVER_DOCKERFILE_PATH = REPO_ROOT / "docker" / "server" / "Dockerfile"
ENV_TEMPLATE_PATH = REPO_ROOT / "env.template"

INGEST_TOKEN_VAR = "APP_HOME_EVENTS_INGEST_TOKEN_FILE"


def _split_volume(entry):
    """Return (host, target, mode) for a compose volume entry.

    Short-syntax strings are split on the LAST two ':' so a host part such as
    "${VAR:?message}" (which contains ':') is kept intact. Long-syntax mappings are
    mapped onto the same tuple shape.
    """
    if isinstance(entry, dict):
        return (
            str(entry.get("source", "")),
            str(entry.get("target", "")),
            "ro" if entry.get("read_only") else "",
        )
    if not isinstance(entry, str):
        raise AssertionError(f"unexpected volume entry type: {type(entry).__name__}")
    parts = entry.rsplit(":", 2)
    if len(parts) == 2:
        # No mode suffix: "host:target"
        return parts[0], parts[1], ""
    if len(parts) != 3:
        raise AssertionError(f"cannot parse volume entry: {entry!r}")
    return parts[0], parts[1], parts[2]


def _volume_entries(service):
    volumes = service.get("volumes") or []
    return [_split_volume(entry) for entry in volumes]


def _volume_strings(service):
    return [str(entry) for entry in (service.get("volumes") or [])]


class ComposeServerServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = _load_compose()
        cls.services = cls.compose.get("services") or {}

    def test_server_service_exists(self):
        self.assertIn(
            "server",
            self.services,
            "docker-compose.yml must define a service named 'server'",
        )

    def test_server_has_no_env_file_and_no_master_key_file_env(self):
        self.assertIn("server", self.services, "server service missing")
        service = self.services["server"]
        self.assertNotIn(
            "env_file",
            service,
            "server must not use env_file: DB logins and tokens must not come from .env",
        )
        environment = service.get("environment") or {}
        self.assertNotIn(
            "APP_MASTER_KEY_FILE",
            environment,
            "server must not receive APP_MASTER_KEY_FILE (only the UI holds the master key)",
        )

    def test_server_has_exactly_two_readonly_secret_file_mounts(self):
        self.assertIn("server", self.services, "server service missing")
        service = self.services["server"]
        app_keys_entries = [
            (host, target, mode)
            for host, target, mode in _volume_entries(service)
            if target.startswith("/run/app-keys")
        ]
        self.assertEqual(
            len(app_keys_entries),
            2,
            "server must have exactly two volumes whose target starts with /run/app-keys",
        )
        by_target = {target: (host, mode) for host, target, mode in app_keys_entries}
        expected = {
            "/run/app-keys/home_events_ingest_token": INGEST_TOKEN_VAR,
            "/run/app-keys/server_db_password": "APP_SERVER_DB_PASSWORD_FILE",
        }
        self.assertEqual(
            set(by_target),
            set(expected),
            "server's /run/app-keys mounts must target exactly the ingest token file and the server db password file",
        )
        strings = _volume_strings(service)
        for target, var in expected.items():
            with self.subTest(target=target):
                host, mode = by_target[target]
                self.assertTrue(
                    any(v.endswith(":" + target + ":ro") for v in strings),
                    f"server's mount of {target} must be read-only (:ro)",
                )
                self.assertEqual(mode, "ro", f"server's mount of {target} must be read-only (:ro)")
                self.assertTrue(
                    host.startswith("${" + var + ":?"),
                    f"server's host path for {target} must be ${{{var}:?...}} so compose refuses to start when unset; got {host!r}",
                )

    def test_server_has_no_master_key_folder_mount(self):
        self.assertIn("server", self.services, "server service missing")
        service = self.services["server"]
        for host, target, _mode in _volume_entries(service):
            with self.subTest(target=target, host=host):
                self.assertNotIn(
                    target,
                    ("/run/app-keys", "/run/app-keys/"),
                    "server must not mount the whole /run/app-keys folder (master key folder)",
                )
                self.assertNotIn(
                    "APP_MASTER_KEY_DIR",
                    host,
                    "server must not mount the master key folder (APP_MASTER_KEY_DIR)",
                )
                self.assertNotIn(
                    "app_master_key",
                    host,
                    "server must not mount the master key file (app_master_key)",
                )

    def test_server_environment_values(self):
        self.assertIn("server", self.services, "server service missing")
        environment = self.services["server"].get("environment")
        self.assertIsInstance(
            environment,
            dict,
            "server environment must be a mapping (anchors merge under safe_load)",
        )
        expected = {
            "SERVICE_TOKEN_DIR": "/run/app-keys",
            "SERVER_HOST": "0.0.0.0",
            "SERVER_PORT": "8081",
            "POSTGRES_HOST": "scanner-postgres",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertIn(key, environment, f"server environment must define {key}")
                self.assertEqual(
                    str(environment[key]),
                    value,
                    f"server environment {key} must be {value!r}",
                )

    def test_server_database_login_environment(self):
        self.assertIn("server", self.services, "server service missing")
        environment = self.services["server"].get("environment") or {}
        self.assertEqual(
            str(environment.get("POSTGRES_USER")),
            "market_scanner_server",
            "server must log in to Postgres as role market_scanner_server",
        )
        self.assertEqual(
            str(environment.get("POSTGRES_PASSWORD_FILE")),
            "/run/app-keys/server_db_password",
            "server POSTGRES_PASSWORD_FILE must be /run/app-keys/server_db_password",
        )
        self.assertEqual(
            str(environment.get("POSTGRES_DB")),
            "${POSTGRES_DB:-market_scanner}",
            "server POSTGRES_DB must be ${POSTGRES_DB:-market_scanner}",
        )
        for key in ("POSTGRES_PASSWORD", "POSTGRES_DSN", "UPSTOX_ACCESS_TOKEN", "KITE_ACCESS_TOKEN"):
            with self.subTest(key=key):
                self.assertNotIn(
                    key,
                    environment,
                    f"server environment must not define {key}",
                )

    def test_server_ports_loopback_only_8081(self):
        self.assertIn("server", self.services, "server service missing")
        ports = self.services["server"].get("ports") or []
        self.assertEqual(
            len(ports),
            1,
            "server must publish exactly one host port",
        )
        port = str(ports[0])
        self.assertTrue(
            port.startswith("127.0.0.1:"),
            f"server port must be loopback only (127.0.0.1:...); got {port!r}",
        )
        self.assertTrue(
            port.endswith(":8081"),
            f"server port must map to container port 8081; got {port!r}",
        )
        self.assertNotEqual(port, "8081:8081", "server port must never be published on all interfaces")

    def test_server_healthcheck(self):
        self.assertIn("server", self.services, "server service missing")
        healthcheck = self.services["server"].get("healthcheck")
        self.assertIsInstance(healthcheck, dict, "server must declare a healthcheck mapping")
        test = healthcheck.get("test")
        self.assertIsInstance(test, list, "server healthcheck test must be a list")
        self.assertTrue(
            test and test[0] == "CMD",
            f"server healthcheck test must start with 'CMD'; got {test!r}",
        )
        self.assertIn(
            "/api/health",
            " ".join(str(part) for part in test),
            "server healthcheck must probe /api/health",
        )
        self.assertEqual(
            str(healthcheck.get("interval")),
            "30s",
            "server healthcheck interval must be 30s",
        )

    def test_server_restart_policy(self):
        self.assertIn("server", self.services, "server service missing")
        self.assertEqual(
            self.services["server"].get("restart"),
            "unless-stopped",
            "server restart policy must be 'unless-stopped'",
        )

    def test_server_networks_default_only(self):
        self.assertIn("server", self.services, "server service missing")
        joined = _service_networks(self.services["server"])
        self.assertIn(
            "default",
            joined,
            "server must list the 'default' network explicitly",
        )
        self.assertNotIn(
            "llm",
            joined,
            "server must not join the 'llm' network",
        )

    def test_server_build_context_and_dockerfile(self):
        self.assertIn("server", self.services, "server service missing")
        build = self.services["server"].get("build")
        self.assertIsInstance(build, dict, "server build must be a mapping with dockerfile and context")
        self.assertEqual(
            build.get("dockerfile"),
            "docker/server/Dockerfile",
            "server build dockerfile must be docker/server/Dockerfile",
        )
        self.assertEqual(
            build.get("context"),
            ".",
            "server build context must be '.'",
        )

    def test_ui_keeps_existing_secret_mounts(self):
        self.assertIn("ui", self.services, "ui service missing")
        strings = _volume_strings(self.services["ui"])
        self.assertTrue(
            any(v.endswith(":/run/service-tokens/collector_token:ro") for v in strings),
            "ui must keep its read-only collector_token mount at /run/service-tokens/collector_token",
        )
        self.assertTrue(
            any(v.endswith(":/run/app-keys:ro") for v in strings),
            "ui must keep its read-only key folder mount at /run/app-keys",
        )

    def test_start_ps1_brings_up_ui_collector_and_server(self):
        self.assertTrue(START_PS1_PATH.exists(), "start.ps1 missing at repo root")
        text = START_PS1_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"'compose',\s*'up',\s*'-d',\s*'ui',\s*'collector',\s*'server'",
            "start.ps1 must run compose up -d for ui, collector and server",
        )

    def test_server_dockerfile_copies_no_env_or_secrets_and_runs_as_node(self):
        self.assertTrue(SERVER_DOCKERFILE_PATH.exists(), "docker/server/Dockerfile missing")
        lines = SERVER_DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.upper().startswith("COPY"):
                lowered = stripped.lower()
                self.assertNotIn(
                    ".env",
                    lowered,
                    f"server Dockerfile must not COPY .env files: {stripped!r}",
                )
                self.assertNotIn(
                    "secrets",
                    lowered,
                    f"server Dockerfile must not COPY secrets: {stripped!r}",
                )
        self.assertTrue(
            any(line.strip() == "USER node" for line in lines),
            "server Dockerfile must contain a 'USER node' line",
        )

    def test_env_template_documents_ingest_token_variable(self):
        self.assertTrue(ENV_TEMPLATE_PATH.exists(), "env.template missing at repo root")
        text = ENV_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn(
            INGEST_TOKEN_VAR,
            text,
            f"env.template must document {INGEST_TOKEN_VAR}",
        )
        self.assertIn(
            "APP_SERVER_DB_PASSWORD_FILE",
            text,
            "env.template must document APP_SERVER_DB_PASSWORD_FILE",
        )


if __name__ == "__main__":
    unittest.main()
