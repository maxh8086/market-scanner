"""The watchdog loop: start due collectors, stop overrunning ones, and keep ui and server up.

Logs are fixed lines (no token, no subprocess output, no compose config, no environment).
The token is only passed to api_client, which places it in the Authorization header.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from scanner.watchdog import api_client
from scanner.watchdog.config import ConfigError, RuntimeConfig, WatchdogConfig, load_config, load_runtime, read_token
from scanner.watchdog.docker_runner import CONTAINER_PREFIX, DockerRunner
from scanner.watchdog.health import DB_SERVICE, SERVICE_ORDER, Backoff, RestartPolicy, check_http

LOGGER_NAME = "scanner.watchdog"
TICK_S = 1.0
WAIT_TICK_S = 5.0
REDACTED = "[redacted]"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 5

Opener = Callable[..., Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Redactor(logging.Filter):
    """Replaces the bearer token in any log message. The secret is set once it has been read."""

    def __init__(self) -> None:
        super().__init__()
        self.secret = ""

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secret:
            message = record.getMessage()
            if self.secret in message:
                record.msg = message.replace(self.secret, REDACTED)
                record.args = ()
        return True


def configure_logging(log_dir: Path | None, stream: TextIO, redactor: Redactor) -> logging.Logger:
    """(Re)configure the watchdog logger: a rotating file under log_dir plus a stream."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers: list[logging.Handler] = []
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_dir / "watchdog.log",
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUPS,
                encoding="utf-8",
            )
        )
    handlers.append(logging.StreamHandler(stream))
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(redactor)
        logger.addHandler(handler)
    return logger


class Watchdog:
    def __init__(
        self,
        config: WatchdogConfig,
        token: str,
        runner: Any,
        runtime: RuntimeConfig,
        *,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        opener: Opener | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._token = token
        self._runner = runner
        self._runtime = runtime
        self._now = now or _utc_now
        self._sleep = sleep or time.sleep
        self._opener = opener or urllib.request.urlopen
        self._log = logger or logging.getLogger(LOGGER_NAME)
        self._policy = RestartPolicy()
        self._db_backoff = Backoff()
        self._first_pass_done = False
        self._killed: set[tuple[str, datetime]] = set()
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    # --- collectors -------------------------------------------------------------------------

    def poll_once(self) -> None:
        result = api_client.fetch_due(
            self._config.api_base_url,
            self._token,
            self._config.http_timeout_s,
            opener=self._opener,
        )
        if not result.ok:
            self._log.warning("poll failed: %s", result.error)
            if result.error == "postgres_down" and self._db_backoff.due(self._now()):
                ok = self._runner.compose_up(DB_SERVICE)
                self._log.warning("compose up %s %s", DB_SERVICE, "ok" if ok else "failed")
            return
        self._db_backoff.reset()
        self._start_due(result.sources)

    def _start_due(self, sources: list[api_client.DueSource]) -> None:
        # The first successful pass after start is sequential; later passes start in parallel.
        sequential = not self._first_pass_done
        self._first_pass_done = True
        for src in sources:
            if self._runner.is_running(src.name):
                self._log.info("already_running %s", src.name)
                continue
            self._runner.remove_leftover(src.name)
            try:
                handle = self._runner.start(src.service, src.name, src.request_id)
            except Exception as exc:  # noqa: BLE001 - popen failure: log the class only
                self._log.error("start failed %s: %s", src.name, type(exc).__name__)
                continue
            self._log.info("started %s", src.name)
            if sequential:
                self._wait_for(handle)

    def _wait_for(self, handle: Any) -> None:
        while handle.poll() is None:
            self.enforce_max_runtime()
            self._sleep(WAIT_TICK_S)

    def enforce_max_runtime(self) -> None:
        now = self._now()
        for name in self._runner.list_collector_containers():
            if not name.startswith(CONTAINER_PREFIX):
                continue
            source = name[len(CONTAINER_PREFIX):]
            try:
                started = self._runner.container_started_at(source)
            except ValueError:
                continue
            if started is None:
                continue
            key = (source, started)
            if key in self._killed:
                continue
            age_s = (now - started).total_seconds()
            limit_s = self._runtime.max_runtime_s(source)
            if age_s <= limit_s:
                continue
            self._killed.add(key)
            try:
                stopped = self._runner.stop(source)
            except ValueError:
                continue
            if not stopped:
                self._log.error("stop failed %s", source)
                continue
            self._log.warning("killed %s after %ds", source, int(age_s))
            finished = api_client.finish_killed(
                self._config.api_base_url,
                self._token,
                source,
                self._config.http_timeout_s,
                opener=self._opener,
            )
            self._log.info("finish_killed %s %s", "ok" if finished else "failed", source)

    # --- ui and server ----------------------------------------------------------------------

    def health_once(self) -> None:
        now = self._now()
        results = {
            "ui": check_http(self._config.ui_health_url, self._config.http_timeout_s, self._opener),
            "server": check_http(self._config.server_health_url, self._config.http_timeout_s, self._opener),
        }
        due: set[str] = set()
        for service in ("ui", "server"):
            self._log.info("health %s %s", service, "ok" if results[service] else "failed")
            due.update(self._policy.record(service, results[service], now))
        for service in SERVICE_ORDER:
            if service in due:
                ok = self._runner.compose_up(service)
                self._log.warning("compose up %s %s", service, "ok" if ok else "failed")

    # --- main loop --------------------------------------------------------------------------

    def run_forever(self, max_ticks: int | None = None) -> None:
        last_poll: datetime | None = None
        last_health: datetime | None = None
        ticks = 0
        while not self._stopped:
            if max_ticks is not None and ticks >= max_ticks:
                break
            ticks += 1
            now = self._now()
            try:
                if last_poll is None or (now - last_poll).total_seconds() >= self._config.poll_interval_s:
                    last_poll = now
                    self.poll_once()
                    self.enforce_max_runtime()
                if last_health is None or (now - last_health).total_seconds() >= self._config.health_interval_s:
                    last_health = now
                    self.health_once()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive; log the class only
                self._log.error("unexpected error: %s", type(exc).__name__)
            self._sleep(TICK_S)


def main(
    argv: list[str] | None = None,
    env: dict[str, str] | None = None,
    *,
    repo_root: Path | None = None,
    runner: Any = None,
    opener: Opener = urllib.request.urlopen,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], datetime] | None = None,
    max_ticks: int | None = None,
) -> int:
    env_map = dict(os.environ) if env is None else dict(env)
    root = repo_root or Path(__file__).resolve().parents[2]
    redactor = Redactor()
    logger = configure_logging(None, sys.stderr, redactor)
    try:
        config = load_config(env_map, root)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2
    try:
        token = read_token(config.token_file)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2
    try:
        runtime = load_runtime(config.runtime_file)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2
    redactor.secret = token
    logger = configure_logging(config.log_dir, sys.stderr, redactor)
    if runner is None:
        runner = DockerRunner(compose_dir=config.repo_root)
    watchdog = Watchdog(
        config,
        token,
        runner,
        runtime,
        now=now,
        sleep=sleep,
        opener=opener,
        logger=logger,
    )
    logger.info("watchdog started")
    watchdog.run_forever(max_ticks=max_ticks)
    logger.info("watchdog stopped")
    return 0
