"""Compose wiring tests for the llm-client service (LC2).

Parses docker-compose.yml at the repo root and checks that:
- the llm-client service exists, publishes no host ports, and joins only the
  "llm" network;
- the top-level "llm" network is declared;
- scanner and ui join the "llm" network;
- llm-client declares a healthcheck.
"""

import pathlib
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


def _load_compose():
    with COMPOSE_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise AssertionError("docker-compose.yml did not parse to a mapping")
    return data


def _service_networks(service):
    """Return the networks of a service as a set of names.

    Compose accepts both a list ("- llm") and a mapping ("llm: {...}").
    """
    networks = service.get("networks")
    if networks is None:
        return set()
    if isinstance(networks, dict):
        return set(networks.keys())
    if isinstance(networks, list):
        return set(networks)
    raise AssertionError(f"unexpected networks shape: {type(networks).__name__}")


class ComposeLlmNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = _load_compose()
        cls.services = cls.compose.get("services") or {}

    def test_llm_client_service_exists(self):
        self.assertIn(
            "llm-client",
            self.services,
            "docker-compose.yml must define a service named 'llm-client'",
        )

    def test_llm_client_has_no_ports(self):
        self.assertIn("llm-client", self.services, "llm-client service missing")
        service = self.services["llm-client"]
        self.assertNotIn(
            "ports",
            service,
            "llm-client must not publish host ports (reachable only on the llm network)",
        )

    def test_llm_client_joins_only_llm_network(self):
        self.assertIn("llm-client", self.services, "llm-client service missing")
        service = self.services["llm-client"]
        networks = service.get("networks")
        self.assertIsNotNone(networks, "llm-client must declare networks")
        if isinstance(networks, dict):
            self.assertEqual(
                set(networks.keys()),
                {"llm"},
                "llm-client must join only the 'llm' network (dict form)",
            )
        else:
            self.assertEqual(
                networks,
                ["llm"],
                "llm-client must join only the 'llm' network (list form)",
            )

    def test_llm_network_declared(self):
        networks = self.compose.get("networks") or {}
        self.assertIn(
            "llm",
            networks,
            "top-level docker-compose 'networks' must declare 'llm'",
        )

    def test_scanner_and_ui_join_llm_network(self):
        for name in ("scanner", "ui"):
            with self.subTest(service=name):
                self.assertIn(name, self.services, f"service '{name}' missing")
                joined = _service_networks(self.services[name])
                self.assertIn(
                    "llm",
                    joined,
                    f"service '{name}' must join the 'llm' network",
                )

    def test_llm_client_has_healthcheck(self):
        self.assertIn("llm-client", self.services, "llm-client service missing")
        self.assertIn(
            "healthcheck",
            self.services["llm-client"],
            "llm-client must declare a healthcheck",
        )


if __name__ == "__main__":
    unittest.main()
