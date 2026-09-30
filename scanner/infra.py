"""Reach the shared infra from the host as well as from inside its Docker network.

secrets/ath_scanner.env names the services by their in-network hostnames (postgres, mongo,
neo4j, vllm). Containers use them as written. A process on the host (tests, a dev shell) sets
INFRA_LOCAL=1 and the same values are rewritten to the 127.0.0.1-only ports the infra publishes:
5432, 27017, 7687, and 8001 for vLLM.
"""
from __future__ import annotations

import os
import re

_HOSTS = re.compile(r"(?<![\w.-])(postgres|mongo|neo4j)(?=[:/\s,]|$)")
_VLLM = re.compile(r"(?<![\w.-])vllm:8000")


def is_local(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("INFRA_LOCAL", "")).lower() in {"1", "true", "yes"}


def localize(value: str, env: dict | None = None) -> str:
    """Rewrite in-network hostnames in a DSN / URI / URL when INFRA_LOCAL is set."""
    if not value or not is_local(env):
        return value
    return _VLLM.sub("127.0.0.1:8001", _HOSTS.sub("127.0.0.1", value))
