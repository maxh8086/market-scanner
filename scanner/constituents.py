"""Download, cache, and clean the Nifty Total Market constituent list."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

PRIMARY_URL = "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv"
FALLBACK_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"

CACHE_PATH = Path("data/ind_niftytotalmarket_list.csv")
MAX_CACHE_AGE_DAYS = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*",
}


def _download(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.content


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    df = df[~df["Symbol"].astype(str).str.startswith("DUMMY")].copy()
    df = df.reset_index(drop=True)
    return df


def load_constituents(override_path: str | None = None, refresh: bool = False) -> pd.DataFrame:
    """Return a cleaned DataFrame of Nifty Total Market constituents.

    The cached CSV is used as-is while it is younger than MAX_CACHE_AGE_DAYS
    (30 days). It is refreshed from NSE when it is older than 30 days or when
    refresh=True. If both downloads fail, a stale cache is still returned.

    Columns: Company Name, Industry, Symbol, Series, ISIN Code
    """
    if override_path:
        df = pd.read_csv(override_path)
        return _clean(df)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    cache_age_days = (time.time() - CACHE_PATH.stat().st_mtime) / 86400 if CACHE_PATH.exists() else None
    if cache_age_days is not None and cache_age_days < MAX_CACHE_AGE_DAYS and not refresh:
        df = pd.read_csv(CACHE_PATH)
        return _clean(df)

    last_error: Exception | None = None
    for url in (PRIMARY_URL, FALLBACK_URL):
        try:
            raw = _download(url)
            CACHE_PATH.write_bytes(raw)
            df = pd.read_csv(CACHE_PATH)
            return _clean(df)
        except Exception as exc:  # noqa: BLE001 - try next source
            last_error = exc
            continue

    if CACHE_PATH.exists():
        # Both downloads failed but we have a stale cache; use it rather than crash.
        df = pd.read_csv(CACHE_PATH)
        return _clean(df)

    raise RuntimeError(
        f"Failed to download constituent list from both sources: {last_error}"
    )
