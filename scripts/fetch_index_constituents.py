"""Download NSE index constituent lists into data/constituents/<slug>.csv.

    python scripts/fetch_index_constituents.py

Idempotent: a slug whose CSV already exists and validates is skipped without a
request. Requests are spaced 2 seconds apart with a generic User-Agent.
Index names and candidate URLs come from scanner/index_sources.py. The slug is the
lowercased name with underscores, so existing files keep their names.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.index_sources import INDEX_SOURCES  # noqa: E402

OUT_DIR = ROOT / "data" / "constituents"

USER_AGENT = "Mozilla/5.0"
PAUSE_SECONDS = 2.0

_last_request = 0.0


def _valid(text: str) -> bool:
    if not text.strip() or text.lstrip().lower().startswith("<"):
        return False
    header = text.lstrip("﻿").splitlines()[0]
    return "Symbol" in header and "ISIN" in header


def _get(url: str) -> str | None:
    """One throttled GET. Returns decoded text, or None on HTTP error."""
    global _last_request
    wait = PAUSE_SECONDS - (time.monotonic() - _last_request)
    if _last_request and wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8-sig", errors="replace")
    except urllib.error.HTTPError as exc:
        print(f"    HTTP {exc.code} for {url}")
        return None
    except urllib.error.URLError as exc:
        print(f"    network error for {url}: {exc.reason}")
        return None


def fetch_one(candidates: tuple[str, ...]) -> tuple[str, str] | None:
    """Try each candidate URL in order and return the first that validates as a CSV."""
    for url in candidates:
        print(f"  trying {url}")
        text = _get(url)
        if text is not None and _valid(text):
            return url, text
        if text is not None:
            print("    response is not a constituent CSV")
    return None


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for name, candidates in INDEX_SOURCES.items():
        slug = name.lower().replace(" ", "_")
        target = OUT_DIR / f"{slug}.csv"
        if target.exists() and _valid(target.read_text(encoding="utf-8-sig", errors="replace")):
            print(f"{name}: already present, skipping ({target.name})")
            continue
        print(f"{name}:")
        found = fetch_one(candidates)
        if found is None:
            print(f"  NOT FOUND after {len(candidates)} requests")
            failures.append(name)
            continue
        url, text = found
        target.write_text(text, encoding="utf-8", newline="")
        rows = [ln for ln in text.splitlines()[1:] if ln.strip()]
        print(f"  saved {target} ({len(rows)} data rows) from {url}")
    if failures:
        print("Failed: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
