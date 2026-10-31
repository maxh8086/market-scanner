"""Loader and validator for the shared column glossary.

The glossary is ``config/glossary.json``: one entry per column key, with the
label, tooltip, explanation and derivation used by the workbook, the model
prompt and the UI. The format is fixed by docs/adr/0001-shared-glossary-format.md.

This module is the only code that reads ``config/glossary.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "config" / "glossary.json"

VISIBILITY_VALUES = ("excel", "ui", "prompt", "backend")
DERIVATION_KINDS = ("formula", "producer")
WORDING_STATUSES = ("draft", "approved")
BACKEND_ONLY = ["backend"]
TEXT_FIELDS = ("tooltip", "explanation")
REQUIRED_FIELDS = ("key", "visibility", "derivation_kind", "provisional", "wording_status")


def _validate_entry(key: str, entry: Any) -> None:
    """Raise ValueError naming ``key`` if ``entry`` breaks a rule in the ADR field table."""
    if not isinstance(entry, dict):
        raise ValueError(f"glossary entry {key!r} must be a JSON object")
    for field in REQUIRED_FIELDS:
        if field not in entry:
            raise ValueError(f"glossary entry {key!r} is missing required field {field!r}")
    if entry["key"] != key:
        raise ValueError(f"glossary entry {key!r} has key field {entry['key']!r}")

    visibility = entry["visibility"]
    if (
        not isinstance(visibility, list)
        or not visibility
        or any(v not in VISIBILITY_VALUES for v in visibility)
    ):
        raise ValueError(f"glossary entry {key!r} has invalid visibility {visibility!r}")

    kind = entry["derivation_kind"]
    if kind not in DERIVATION_KINDS:
        raise ValueError(f"glossary entry {key!r} has invalid derivation_kind {kind!r}")
    if kind == "formula" and not _non_empty_str(entry.get("formula")):
        raise ValueError(f"glossary entry {key!r} has derivation_kind 'formula' but no formula")
    if kind == "producer" and not _non_empty_str(entry.get("producer")):
        raise ValueError(f"glossary entry {key!r} has derivation_kind 'producer' but no producer")

    if visibility == BACKEND_ONLY:
        for field in TEXT_FIELDS:
            if field in entry:
                raise ValueError(
                    f"glossary entry {key!r} is backend-only and must not have {field!r}"
                )

    if entry["wording_status"] not in WORDING_STATUSES:
        raise ValueError(
            f"glossary entry {key!r} has invalid wording_status {entry['wording_status']!r}"
        )
    if not isinstance(entry["provisional"], bool):
        raise ValueError(f"glossary entry {key!r} has non-boolean provisional")


def _non_empty_str(value: Any) -> bool:
    """True when ``value`` is a string with at least one non-space character."""
    return isinstance(value, str) and value.strip() != ""


def load_glossary(path: Optional[Path] = None) -> dict[str, Mapping[str, Any]]:
    """Read and validate the glossary file, returning entries keyed by column key.

    ``path`` defaults to ``config/glossary.json``. Raises ValueError naming the
    key on any entry that breaks the ADR rules, and on a file that is not a
    JSON object.
    """
    source = Path(path) if path is not None else GLOSSARY_PATH
    with source.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"glossary file {source} must contain a JSON object")
    for key, entry in data.items():
        _validate_entry(key, entry)
    return data


def entry_for(key: str) -> Optional[Mapping[str, Any]]:
    """Return the glossary entry for ``key``, or None when there is none."""
    return load_glossary().get(key)
