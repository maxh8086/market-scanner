"""Symbol / ISIN -> instrument token resolution, backed by a daily-cached
dump of kite.instruments("NSE")."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

CACHE_PATH = Path("data/nse_instruments.parquet")


def load_nse_instruments(kite, refresh: bool = False) -> pd.DataFrame:
    """Return the NSE instrument dump as a DataFrame, cached for the day."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CACHE_PATH.exists() and not refresh:
        mtime = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
        if mtime.date() == datetime.now().date():
            return pd.read_parquet(CACHE_PATH)

    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)
    df.to_parquet(CACHE_PATH)
    return df


def build_symbol_index(instruments_df: pd.DataFrame) -> tuple[dict, dict]:
    """Return (by_tradingsymbol, by_isin) lookup dicts, restricted to the
    equity (EQ) series on the NSE segment."""
    eq = instruments_df[
        (instruments_df["segment"] == "NSE") & (instruments_df["instrument_type"] == "EQ")
    ]
    by_symbol = {row["tradingsymbol"]: row for _, row in eq.iterrows()}

    by_isin: dict = {}
    if "isin" in eq.columns:
        for _, row in eq.iterrows():
            isin = row.get("isin")
            if isin:
                by_isin.setdefault(isin, row)

    return by_symbol, by_isin


def resolve_token(symbol: str, isin: str | None, by_symbol: dict, by_isin: dict):
    """Resolve a trading symbol to its instrument row, falling back to ISIN
    match if the symbol itself isn't found (e.g. after a rename)."""
    row = by_symbol.get(symbol)
    if row is not None:
        return row
    if isin:
        row = by_isin.get(isin)
        if row is not None:
            return row
    return None
