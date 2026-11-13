"""Loader for config/collector_services.json: the sources that run in their own container.

Shape (proposed in docs/designs/collector-split-slices.md, S1b):
    {"sources": {"<source name>": {"service": "<compose service>", "host": "<cooldown host>"}}}

A missing file is an error that names the file: it is never read as an empty set, because that
would let the old serve loop run a source that already has a container. A malformed file is an
error for the same reason. Both are raised as ValueError; the caller decides what to do with it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "collector_services.json"
_ALLOWED_ENTRY_KEYS = frozenset({"service", "host"})


def load_container_sources(path: Optional[Path] = None) -> set[str]:
    """Names of the sources listed in the services file.

    Raises ValueError, naming the file, when the file is missing, has malformed JSON, a wrong
    shape, or an unknown key in an entry."""
    p = Path(path) if path is not None else DEFAULT_PATH
    if not p.exists():
        raise ValueError(f"{p}: services file not found")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{p}: malformed JSON: {e}") from e

    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict):
        raise ValueError(f'{p}: top level must be an object with a "sources" object')

    for name, entry in data["sources"].items():
        if not isinstance(entry, dict):
            raise ValueError(f'{p}: entry "{name}" must be an object')
        unknown = set(entry) - _ALLOWED_ENTRY_KEYS
        if unknown:
            raise ValueError(f'{p}: entry "{name}" has unknown key(s): {", ".join(sorted(unknown))}')
        for key, value in entry.items():
            if not isinstance(value, str):
                raise ValueError(f'{p}: entry "{name}" field "{key}" must be a string')

    return set(data["sources"])
