"""Compose wiring tests for the run-once collector template (S3).

Parses docker-compose.yml at the repo root and checks that:
- the x-collector-run-once template is a run-once service (profile collectors, restart no,
  entrypoint ends in run-once, no container_name, no ports, no docker socket, no ./output mount,
  read-only collector token mount, default network only, no Mongo or Neo4j keys);
- x-collector-pg-env carries Postgres only, and x-collector-mongo-env carries the document store;
- the old `collector` service is unchanged in the ways this slice must not touch;
- every service named in config/collector_services.json is a run-once collector service;
- no service that runs `run-once` is restart: always.
"""

import json
import pathlib
import unittest

from tests.test_compose_llm_network import _load_compose, _service_networks

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
COLLECTOR_SERVICES_PATH = REPO_ROOT / "config" / "collector_services.json"

TEMPLATE_KEY = "x-collector-run-once"
PG_ENV_KEY = "x-collector-pg-env"
MONGO_ENV_KEY = "x-collector-mongo-env"
MONGO_ENV_KEYS = ("SCANNER_MONGO_HOST", "DOCSTORE_BACKEND", "NEO4J_URI")
COLLECTOR_TOKEN_TARGET = "/run/app-keys/collector_token"


def _volume_triples(service):
    """Return (host, target, mode) for each compose volume entry of a service.

    Short-syntax strings are split on the last two ':' so "${VAR:?message}" host parts stay intact.
    """
    triples = []
    for entry in service.get("volumes") or []:
        if isinstance(entry, dict):
            triples.append(
                (
                    str(entry.get("source", "")),
                    str(entry.get("target", "")),
                    "ro" if entry.get("read_only") else "",
                )
            )
            continue
        parts = str(entry).rsplit(":", 2)
        if len(parts) == 2:
            triples.append((parts[0], parts[1], ""))
        elif len(parts) == 3:
            triples.append((parts[0], parts[1], parts[2]))
        else:
            raise AssertionError(f"cannot parse volume entry: {entry!r}")
    return triples


class ComposeCollectorTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = _load_compose()
        cls.services = cls.compose.get("services") or {}

    def _template(self):
        self.assertIn(TEMPLATE_KEY, self.compose, f"docker-compose.yml must define {TEMPLATE_KEY}")
        template = self.compose[TEMPLATE_KEY]
        self.assertIsInstance(template, dict, f"{TEMPLATE_KEY} must be a mapping")
        return template

    def test_template_key_exists_and_is_mapping(self):
        self._template()

    def test_template_is_run_once_collectors_profile(self):
        self.assertEqual(self._template().get("profiles"), ["collectors"])

    def test_template_restart_is_no(self):
        self.assertEqual(self._template().get("restart"), "no")

    def test_template_entrypoint_ends_in_run_once(self):
        entrypoint = self._template().get("entrypoint")
        self.assertIsInstance(entrypoint, list, "template entrypoint must be a list")
        self.assertEqual(entrypoint[-1], "run-once", f"template entrypoint must end in run-once; got {entrypoint!r}")

    def test_template_has_no_container_name(self):
        self.assertNotIn(
            "container_name",
            self._template(),
            "template must not set container_name (the watchdog passes --name collector-<source>)",
        )

    def test_template_publishes_no_ports(self):
        self.assertFalse(self._template().get("ports"), "template must not publish ports")

    def test_template_has_no_docker_socket_mount(self):
        for entry in self._template().get("volumes") or []:
            with self.subTest(entry=entry):
                self.assertNotIn("docker.sock", str(entry), "template must not mount the docker socket")

    def test_template_has_no_output_mount(self):
        for _host, target, _mode in _volume_triples(self._template()):
            with self.subTest(target=target):
                self.assertNotEqual(target, "/app/output", "template must not mount ./output (no CSV output)")

    def test_template_collector_token_mount_is_readonly_and_required(self):
        matches = [
            (host, mode)
            for host, target, mode in _volume_triples(self._template())
            if target == COLLECTOR_TOKEN_TARGET
        ]
        self.assertEqual(len(matches), 1, f"template must mount {COLLECTOR_TOKEN_TARGET} exactly once")
        host, mode = matches[0]
        self.assertEqual(mode, "ro", "template collector token mount must be read-only (:ro)")
        self.assertTrue(
            host.startswith("${APP_SERVICE_TOKEN_FILE:?"),
            f"template collector token host path must be ${{APP_SERVICE_TOKEN_FILE:?...}}; got {host!r}",
        )

    def test_template_has_no_mongo_or_neo4j_keys(self):
        environment = self._template().get("environment") or {}
        for key in MONGO_ENV_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, environment, f"template environment must not define {key} (Mongo and Neo4j are not collector-wide)")

    def test_template_networks_default_only(self):
        self.assertEqual(
            _service_networks(self._template()),
            {"default"},
            "template must join the default network only",
        )

    def test_pg_env_anchor_is_postgres_only(self):
        self.assertIn(PG_ENV_KEY, self.compose, f"docker-compose.yml must define {PG_ENV_KEY}")
        pg_env = self.compose[PG_ENV_KEY]
        self.assertEqual(str(pg_env.get("POSTGRES_HOST")), "scanner-postgres")
        self.assertEqual(str(pg_env.get("POSTGRES_PORT")), "5432")
        for key in MONGO_ENV_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, pg_env, f"{PG_ENV_KEY} must not define {key}")

    def test_mongo_env_anchor_has_document_store(self):
        self.assertIn(MONGO_ENV_KEY, self.compose, f"docker-compose.yml must define {MONGO_ENV_KEY}")
        mongo_env = self.compose[MONGO_ENV_KEY]
        self.assertEqual(str(mongo_env.get("SCANNER_MONGO_HOST")), "scanner-mongo:27017")
        self.assertEqual(str(mongo_env.get("DOCSTORE_BACKEND")), "mongo")

    def test_old_collector_service_unchanged(self):
        self.assertIn("collector", self.services, "the old collector service must stay")
        collector = self.services["collector"]
        self.assertEqual(collector.get("entrypoint"), ["python", "collect.py", "serve"])
        self.assertEqual(collector.get("restart"), "always")
        self.assertIn(
            "./output",
            [host for host, target, _mode in _volume_triples(collector)],
            "the old collector service must keep its ./output mount",
        )
        self.assertIn(
            "/app/output",
            [target for _host, target, _mode in _volume_triples(collector)],
            "the old collector service must keep its /app/output target",
        )

    def test_run_once_services_are_never_restart_always(self):
        for name, service in self.services.items():
            if not isinstance(service, dict):
                continue
            parts = []
            for field in ("entrypoint", "command"):
                value = service.get(field)
                if isinstance(value, list):
                    parts += [str(part) for part in value]
                elif value:
                    parts.append(str(value))
            if "run-once" in parts:
                with self.subTest(service=name):
                    self.assertNotEqual(
                        service.get("restart"),
                        "always",
                        f"run-once service {name} must not use restart: always",
                    )

    def test_services_named_in_collector_services_file_are_run_once_collectors(self):
        # Forward-looking: config/collector_services.json is empty today ("sources": {}), so this
        # passes vacuously. Each source added later must map to a run-once collector compose service.
        data = json.loads(COLLECTOR_SERVICES_PATH.read_text(encoding="utf-8"))
        sources = data.get("sources") or {}
        for key, entry in sources.items():
            service_name = entry.get("service", key) if isinstance(entry, dict) else key
            with self.subTest(service=service_name):
                self.assertIn(
                    service_name,
                    self.services,
                    f"collector_services.json names {service_name}, which is not a compose service",
                )
                service = self.services[service_name]
                self.assertIn("collectors", service.get("profiles") or [], f"{service_name} must have profile collectors")
                self.assertNotIn("container_name", service, f"{service_name} must not set container_name")
                self.assertEqual(service.get("restart"), "no", f"{service_name} must use restart: \"no\"")


HOME_SERVICE = "collector-home-filings"
INGEST_TOKEN_TARGET = "/run/app-keys/home_events_ingest_token"
RUN_KEYS_FOLDER = "/run/app-keys"
MASTER_KEY_DIR_VAR = "APP_MASTER_KEY_DIR"


class HomeFilingsCollectorServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = _load_compose()
        cls.services = cls.compose.get("services") or {}

    def _service(self):
        self.assertIn(HOME_SERVICE, self.services, f"docker-compose.yml must define {HOME_SERVICE}")
        service = self.services[HOME_SERVICE]
        self.assertIsInstance(service, dict, f"{HOME_SERVICE} must be a mapping")
        return service

    def test_template_sets_collector_api_base_url(self):
        template = self.compose["x-collector-run-once"]
        environment = template.get("environment") or {}
        self.assertIn("COLLECTOR_API_BASE_URL", environment, "template must set COLLECTOR_API_BASE_URL")
        value = str(environment["COLLECTOR_API_BASE_URL"])
        self.assertIn("EVENTS_API_BASE_URL", value, "COLLECTOR_API_BASE_URL must reference EVENTS_API_BASE_URL")
        self.assertIn("http://server:8081", value, "COLLECTOR_API_BASE_URL must default to http://server:8081")

    def test_service_is_run_once_collector(self):
        service = self._service()
        self.assertIn("collectors", service.get("profiles") or [], "must have profile collectors")
        self.assertEqual(service.get("restart"), "no", 'must use restart: "no"')
        self.assertEqual(service.get("entrypoint"), ["python", "collect.py", "run-once"])
        self.assertEqual(service.get("command"), ["--source", "home_filings"])
        self.assertNotIn("container_name", service, "must not set container_name")
        self.assertFalse(service.get("ports"), "must not publish ports")
        self.assertEqual(_service_networks(service), {"default"}, "must join the default network only")

    def test_service_has_no_mongo_or_neo4j_env(self):
        environment = self._service().get("environment") or {}
        for key in MONGO_ENV_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, environment, f"{HOME_SERVICE} must not define {key}")

    def test_service_mounts_tokens_readonly_without_key_folder(self):
        triples = _volume_triples(self._service())
        targets = {target: (host, mode) for host, target, mode in triples}

        collector = targets.get(COLLECTOR_TOKEN_TARGET)
        self.assertIsNotNone(collector, f"must mount {COLLECTOR_TOKEN_TARGET}")
        self.assertEqual(collector[1], "ro", "collector token mount must be read-only")

        ingest = targets.get(INGEST_TOKEN_TARGET)
        self.assertIsNotNone(ingest, f"must mount {INGEST_TOKEN_TARGET}")
        self.assertEqual(ingest[1], "ro", "ingest token mount must be read-only")
        self.assertTrue(
            ingest[0].startswith("${APP_HOME_EVENTS_INGEST_TOKEN_FILE:?"),
            f"ingest token host path must be ${{APP_HOME_EVENTS_INGEST_TOKEN_FILE:?...}}; got {ingest[0]!r}",
        )

        self.assertNotIn(RUN_KEYS_FOLDER, targets, f"must not mount {RUN_KEYS_FOLDER} as a folder")
        for host, target, _mode in triples:
            with self.subTest(target=target):
                self.assertNotIn(MASTER_KEY_DIR_VAR, host, "must not mount the folder that holds app_master_key")
                self.assertNotIn("app_master_key", host, "must not mount a path naming app_master_key")

    def test_services_file_maps_home_filings(self):
        data = json.loads(COLLECTOR_SERVICES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            (data.get("sources") or {}).get("home_filings"),
            {"service": HOME_SERVICE, "host": "nse"},
        )
        self.assertIn(HOME_SERVICE, self.services)

    def test_source_in_command_is_registered(self):
        from scanner.collect.sources import SOURCES

        command = self._service().get("command") or []
        self.assertIn("home_filings", command)
        self.assertIn("home_filings", SOURCES, "the command source must be registered in scanner.collect.sources.SOURCES")

    def test_runtime_limit_is_330(self):
        runtime = json.loads((REPO_ROOT / "config" / "collector_runtime.json").read_text(encoding="utf-8"))
        self.assertEqual((runtime.get("sources") or {}).get("home_filings"), 330)


if __name__ == "__main__":
    unittest.main()
