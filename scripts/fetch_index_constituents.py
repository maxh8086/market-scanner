"""Download NSE index constituent lists into data/constituents/<slug>.csv.

    python scripts/fetch_index_constituents.py

Idempotent: a slug whose CSV already exists and validates is skipped without a
request. Requests are spaced 2 seconds apart with a generic User-Agent.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "constituents"

PRIMARY_BASE = "https://nsearchives.nseindia.com/content/indices/"
FALLBACK_BASE = "https://www.niftyindices.com/IndexConstituent/"
USER_AGENT = "Mozilla/5.0"
PAUSE_SECONDS = 2.0
MAX_VARIANTS = 3

# slug -> (index name, filename variants; the first is the known candidate)
INDICES = {
    "nifty_50": (
        "Nifty 50",
        ["ind_nifty50list.csv", "ind_nifty_50_list.csv", "ind_nifty50_list.csv"],
    ),
    "nifty_next_50": (
        "Nifty Next 50",
        ["ind_niftynext50list.csv", "ind_nifty_next50_list.csv", "ind_niftynext50_list.csv"],
    ),
    "nifty_midcap_150": (
        "Nifty Midcap 150",
        ["ind_niftymidcap150list.csv", "ind_nifty_midcap150_list.csv", "ind_niftymidcap_150list.csv"],
    ),
    "nifty_smallcap_250": (
        "Nifty Smallcap 250",
        ["ind_niftysmallcap250list.csv", "ind_nifty_smallcap250_list.csv", "ind_niftysmallcap_250list.csv"],
    ),
    "nifty_microcap_250": (
        "Nifty Microcap 250",
        ["ind_niftymicrocap250_list.csv", "ind_niftymicrocap250list.csv", "ind_nifty_microcap250_list.csv"],
    ),
    "nifty_bank": (
        "Nifty Bank",
        ["ind_niftybanklist.csv", "ind_nifty_bank_list.csv", "ind_niftybank_list.csv"],
    ),
}

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


def fetch_one(slug: str, name: str, variants: list[str]) -> tuple[str, str] | None:
    """Try the primary host with up to MAX_VARIANTS filenames, then the fallback host."""
    attempts: list[str] = [PRIMARY_BASE + f for f in variants[:MAX_VARIANTS]]
    attempts.append(FALLBACK_BASE + variants[0])
    for url in attempts:
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
    for slug, (name, variants) in INDICES.items():
        target = OUT_DIR / f"{slug}.csv"
        if target.exists() and _valid(target.read_text(encoding="utf-8-sig", errors="replace")):
            print(f"{name}: already present, skipping ({target.name})")
            continue
        print(f"{name}:")
        found = fetch_one(slug, name, variants)
        if found is None:
            print(f"  NOT FOUND after {len(variants[:MAX_VARIANTS]) + 1} requests")
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
