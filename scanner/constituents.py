"""Index constituents for scans. The run path reads the database; it never downloads.

The monthly job (scanner/company_reference_job.py) stores each index in SCAN_INDEXES in the
index_constituents table. load_constituents() reads one index by name from there. An
operator's local CSV can still be passed as override_path.
"""
from __future__ import annotations

import pandas as pd

from scanner import company_reference as cr

DEFAULT_INDEX = "NIFTY TOTAL MARKET"

# Used as the browser-like header for the monthly job's downloads (company_reference_job).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*",
}

COLUMNS = ["Company Name", "Industry", "Symbol", "Series", "ISIN Code"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    df = df[~df["Symbol"].astype(str).str.startswith("DUMMY")].copy()
    df = df.reset_index(drop=True)
    return df


def load_constituents(override_path: str | None = None, index_name: str = DEFAULT_INDEX) -> pd.DataFrame:
    """Return a DataFrame of one index's constituents.

    With override_path, read that local CSV (same cleaning as before). Otherwise read
    index_name from the database. Raises RuntimeError if the database has no rows for it.

    Columns: Company Name, Industry, Symbol, Series, ISIN Code
    """
    if override_path:
        df = pd.read_csv(override_path)
        return _clean(df)

    from scanner.pg import db  # imported here so override_path runs need no database

    with db.connect() as conn:
        records = cr.load_index_constituents(conn, index_name)
    return pd.DataFrame(records, columns=COLUMNS)
