"""Health checks for the ui and server, and the restart policy for their compose services.

A service is restarted (docker compose up -d) after 3 consecutive failed checks. Restarts of one
episode are spaced by the backoff 1, 5, 15, 15 minutes, ... and a success resets the episode.
The database is brought up first whenever any restart is due. Only compose up is used, never stop.
"""
from __future__ import annotations

import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

DB_SERVICE = "scanner-postgres"
SERVICE_ORDER = (DB_SERVICE, "ui", "server")
RESTARTABLE = ("ui", "server")
FAILURE_THRESHOLD = 3
BACKOFF_S = (60, 300, 900)

Opener = Callable[..., Any]


def check_http(url: str, timeout_s: float, opener: Opener = urllib.request.urlopen) -> bool:
    """True for a 2xx answer. Never raises."""
    try:
        with opener(url, timeout=timeout_s) as response:
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            return isinstance(status, int) and 200 <= status < 300
    except Exception:  # noqa: BLE001 - refused, timeout, DNS, HTTP error: all unhealthy
        return False


class Backoff:
    """Rate limit for restarts within one episode.

    The first call is due at once. Each later call is due only after the gap for its step:
    1, 5, 15, then 15 minutes for every further step.
    """

    def __init__(self) -> None:
        self._step = 0
        self._next_at: datetime | None = None

    def due(self, now: datetime) -> bool:
        if self._next_at is not None and now < self._next_at:
            return False
        gap = BACKOFF_S[min(self._step, len(BACKOFF_S) - 1)]
        self._next_at = now + timedelta(seconds=gap)
        self._step += 1
        return True

    def reset(self) -> None:
        self._step = 0
        self._next_at = None


class RestartPolicy:
    def __init__(self) -> None:
        self._failures: dict[str, int] = {service: 0 for service in RESTARTABLE}
        self._backoff: dict[str, Backoff] = {service: Backoff() for service in RESTARTABLE}

    def record(self, service: str, ok: bool, now: datetime) -> list[str]:
        """Record one health result. Returns the compose services to bring up this tick, in order."""
        if service not in RESTARTABLE:
            raise ValueError("unknown service")
        if ok:
            self._failures[service] = 0
            self._backoff[service].reset()
            return []
        self._failures[service] += 1
        if self._failures[service] < FAILURE_THRESHOLD:
            return []
        if not self._backoff[service].due(now):
            return []
        return [DB_SERVICE, service]
