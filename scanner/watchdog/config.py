"""Watchdog configuration: env settings, the bearer token file and the per-source runtime limits.

Nothing here reads .env or the secrets store. The token file path comes from the environment
(a host path outside the repo). Error messages never include a path value or a secret.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_API_BASE_URL = "http://127.0.0.1:8081"
DEFAULT_UI_HEALTH_URL = "http://127.0.0.1:8080/api/health"
DEFAULT_POLL_S = 60.0
DEFAULT_HEALTH_S = 30.0
DEFAULT_HTTP_TIMEOUT_S = 10.0

_SOURCE_RE = re.compile(r"^[a-z0-9_]+$")


class ConfigError(RuntimeError):
    """Configuration is missing or invalid. The message is fixed text: no path, no secret."""


@dataclass(frozen=True)
class WatchdogConfig:
    api_base_url: str
    ui_health_url: str
    server_health_url: str
    token_file: Path
    runtime_file: Path
    repo_root: Path
    poll_interval_s: float
    health_interval_s: float
    http_timeout_s: float
    log_dir: Path


@dataclass(frozen=True)
class RuntimeConfig:
    default_max_runtime_s: int
    sources: Mapping[str, int] = field(default_factory=dict)

    def max_runtime_s(self, source: str) -> int:
        return int(self.sources.get(source, self.default_max_runtime_s))


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if not value > 0:
        raise ConfigError(f"{name} must be greater than 0")
    return value


def load_config(env: Mapping[str, str], repo_root: Path) -> WatchdogConfig:
    token_raw = (env.get("WATCHDOG_TOKEN_FILE") or "").strip()
    if token_raw == "":
        raise ConfigError("WATCHDOG_TOKEN_FILE is not set")

    api_base_url = (env.get("WATCHDOG_API_BASE_URL") or "").strip() or DEFAULT_API_BASE_URL
    api_base_url = api_base_url.rstrip("/")
    server_health_url = (env.get("WATCHDOG_SERVER_HEALTH_URL") or "").strip() or f"{api_base_url}/api/health"
    ui_health_url = (env.get("WATCHDOG_UI_HEALTH_URL") or "").strip() or DEFAULT_UI_HEALTH_URL
    runtime_raw = (env.get("WATCHDOG_RUNTIME_FILE") or "").strip()
    runtime_file = Path(runtime_raw) if runtime_raw else repo_root / "config" / "collector_runtime.json"

    return WatchdogConfig(
        api_base_url=api_base_url,
        ui_health_url=ui_health_url,
        server_health_url=server_health_url,
        token_file=Path(token_raw),
        runtime_file=runtime_file,
        repo_root=repo_root,
        poll_interval_s=_positive_float(env, "WATCHDOG_POLL_S", DEFAULT_POLL_S),
        health_interval_s=_positive_float(env, "WATCHDOG_HEALTH_S", DEFAULT_HEALTH_S),
        http_timeout_s=_positive_float(env, "WATCHDOG_HTTP_TIMEOUT_S", DEFAULT_HTTP_TIMEOUT_S),
        log_dir=repo_root / "logs",
    )


def read_token(path: Path | str) -> str:
    """Return the stripped token file content. Missing, unreadable or empty -> ConfigError."""
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        text = ""
    if not text:
        raise ConfigError("watchdog token file is missing or empty")
    return text


def _positive_int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{what} must be a positive integer")
    return value


def load_runtime(path: Path | str) -> RuntimeConfig:
    """Read the runtime limits file. Missing or malformed -> ConfigError (fixed text)."""
    try:
        parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise ConfigError("collector runtime config is missing or not valid JSON") from None
    if not isinstance(parsed, dict):
        raise ConfigError("collector runtime config has a bad shape")
    default = _positive_int(parsed.get("default_max_runtime_s"), "default_max_runtime_s")
    raw_sources = parsed.get("sources", {})
    if not isinstance(raw_sources, dict):
        raise ConfigError("collector runtime config has a bad shape")
    sources: dict[str, int] = {}
    for name, seconds in raw_sources.items():
        if not isinstance(name, str) or not _SOURCE_RE.match(name):
            raise ConfigError("collector runtime config has a bad source name")
        sources[name] = _positive_int(seconds, "source max_runtime_s")
    return RuntimeConfig(default_max_runtime_s=default, sources=sources)
