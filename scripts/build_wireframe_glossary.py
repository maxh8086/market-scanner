"""Inline the shared glossary into the wireframe as a generated JavaScript block.

Source: config/glossary.json, read only through scanner.glossary.load_glossary.
Target: the lines between the two marker comments in ui/wireframes/strategy.html.

Run from the repo root:
    .venv/Scripts/python.exe scripts/build_wireframe_glossary.py

The first run replaces the hand-written "const G={ ... };" object with the
marker-wrapped block. Later runs replace only what sits between the markers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scanner.glossary import GLOSSARY_PATH, load_glossary  # noqa: E402

WIREFRAME_PATH = REPO_ROOT / "ui" / "wireframes" / "strategy.html"
BEGIN_MARKER = "/* glossary:begin */"
END_MARKER = "/* glossary:end */"
LEGACY_START = "const G={"
LEGACY_END = "\n};"


def build_block(glossary_dict: Mapping[str, Mapping[str, Any]]) -> str:
    """Return the ``const G={...};`` block, one line per entry, in key order.

    The text of each entry is written as ``[label, tooltip, how]``. ``how`` is
    the formula for formula entries and the explanation for producer entries.
    Lines use LF endings; the caller converts them to the file's line endings.
    """
    keys = list(glossary_dict)
    lines = ["const G={"]
    for index, key in enumerate(keys):
        entry = glossary_dict[key]
        how = entry["formula"] if entry["derivation_kind"] == "formula" else entry["explanation"]
        values = [
            json.dumps(entry["label"], ensure_ascii=False),
            json.dumps(entry["tooltip"], ensure_ascii=False),
            json.dumps(how, ensure_ascii=False),
        ]
        comma = "," if index < len(keys) - 1 else ""
        lines.append(f" {key}:[{','.join(values)}]{comma}")
    lines.append("};")
    return "\n".join(lines)


def sync_wireframe(html_path: Path | str) -> bool:
    """Rewrite the glossary block in ``html_path`` if it differs. Return True when changed."""
    path = Path(html_path)
    with path.open(encoding="utf-8", newline="") as fh:
        text = fh.read()

    newline = "\r\n" if "\r\n" in text else "\n"
    block = build_block(load_glossary(GLOSSARY_PATH)).replace("\n", newline)

    if BEGIN_MARKER in text:
        begin = text.index(BEGIN_MARKER) + len(BEGIN_MARKER)
        end = text.index(END_MARKER, begin)
        new_text = text[:begin] + newline + block + newline + text[end:]
    else:
        start = text.index(LEGACY_START)
        end = text.index(LEGACY_END, start) + len(LEGACY_END)
        new_text = (
            text[:start]
            + BEGIN_MARKER
            + newline
            + block
            + newline
            + END_MARKER
            + text[end:]
        )

    if new_text == text:
        return False
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_text)
    return True


def main() -> None:
    changed = sync_wireframe(WIREFRAME_PATH)
    print("updated" if changed else "unchanged")


if __name__ == "__main__":
    main()
