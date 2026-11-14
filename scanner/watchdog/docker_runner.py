"""Docker command builders and a thin executor for the watchdog.

Every command is a list of arguments run with shell=False. Only collector containers can be
stopped; nothing here stops scanner-postgres, server or ui. Output from docker is never logged
or returned, except the parsed container names and timestamps.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

_SOURCE_RE = re.compile(r"^[a-z0-9_]+$")
_SERVICE_RE = re.compile(r"^[a-z0-9_-]+$")
_STARTED_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$"
)
CONTAINER_PREFIX = "collector-"
QUERY_TIMEOUT_S = 30.0
COMPOSE_TIMEOUT_S = 300.0
_FAILED_RC = -1

ExecuteFn = Callable[[list[str], "float | None"], tuple[int, str]]


def default_execute(args: list[str], timeout_s: float | None) -> tuple[int, str]:
    """Run one command with list args and no shell. Returns (returncode, stdout)."""
    try:
        proc = subprocess.run(
            args,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return _FAILED_RC, ""
    return proc.returncode, proc.stdout or ""


def container_name(source: str) -> str:
    if not isinstance(source, str) or not _SOURCE_RE.match(source):
        raise ValueError("invalid source name")
    return f"{CONTAINER_PREFIX}{source}"


def _check_service(service: str) -> str:
    if not isinstance(service, str) or not _SERVICE_RE.match(service):
        raise ValueError("invalid compose service name")
    return service


def _parse_started_at(text: str) -> datetime | None:
    """Parse Docker's RFC3339 StartedAt, truncating fractional seconds to microseconds."""
    match = _STARTED_RE.match(text.strip())
    if match is None:
        return None
    base, fraction, zone = match.groups()
    micro = (fraction or "0")[:6].ljust(6, "0")
    zone = "+00:00" if zone == "Z" else zone
    try:
        return datetime.fromisoformat(f"{base}.{micro}{zone}")
    except ValueError:
        return None


class DockerRunner:
    def __init__(
        self,
        execute: ExecuteFn = default_execute,
        *,
        compose_dir: Path,
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self._execute = execute
        self._compose_dir = Path(compose_dir)
        self._popen = popen

    def _compose_prefix(self) -> list[str]:
        return ["docker", "compose", "--project-directory", str(self._compose_dir)]

    def is_running(self, source: str) -> bool:
        name = container_name(source)
        _, out = self._execute(
            ["docker", "ps", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"],
            QUERY_TIMEOUT_S,
        )
        return name in {line.strip() for line in out.splitlines()}

    def remove_leftover(self, source: str) -> None:
        name = container_name(source)
        self._execute(["docker", "rm", "-f", name], QUERY_TIMEOUT_S)

    def build_run_args(self, service: str, source: str, request_id: str | None) -> list[str]:
        name = container_name(source)
        service = _check_service(service)
        args = [
            *self._compose_prefix(),
            "--profile",
            "collectors",
            "run",
            "--rm",
            "--no-deps",
            "--name",
            name,
            service,
            "--source",
            source,
        ]
        if request_id is not None:
            args += ["--request-id", request_id]
        return args

    def start(self, service: str, source: str, request_id: str | None) -> Any:
        """Start one collector run; returns the process handle (poll() / wait())."""
        args = self.build_run_args(service, source, request_id)
        return self._popen(
            args,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def container_started_at(self, source: str) -> datetime | None:
        name = container_name(source)
        rc, out = self._execute(
            ["docker", "inspect", "-f", "{{.State.StartedAt}}", name], QUERY_TIMEOUT_S
        )
        if rc != 0:
            return None
        return _parse_started_at(out)

    def stop(self, source: str) -> bool:
        name = container_name(source)
        if not name.startswith(CONTAINER_PREFIX):
            raise ValueError("only collector containers can be stopped")
        rc, _ = self._execute(["docker", "stop", name], COMPOSE_TIMEOUT_S)
        return rc == 0

    def list_collector_containers(self) -> list[str]:
        rc, out = self._execute(
            ["docker", "ps", "--filter", f"name=^/{CONTAINER_PREFIX}", "--format", "{{.Names}}"],
            QUERY_TIMEOUT_S,
        )
        if rc != 0:
            return []
        names = [line.strip() for line in out.splitlines()]
        return [n for n in names if n.startswith(CONTAINER_PREFIX)]

    def compose_up(self, service: str) -> bool:
        service = _check_service(service)
        rc, _ = self._execute(
            [*self._compose_prefix(), "up", "-d", service], COMPOSE_TIMEOUT_S
        )
        return rc == 0
