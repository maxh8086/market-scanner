"""Portfolio overlay: Kite holdings joined with ATH scan and enrichment data.

Two ingestion paths behind one interface:
 (a) FILE path (default): holdings export at data/holdings.json or data/holdings.csv
     JSON: list of dicts from Kite's `holdings()` endpoint
     CSV: tradingsymbol, exchange, isin, quantity, t1_quantity, average_price, last_price, pnl, day_change_percentage
 (b) LIVE path (optional): if KITE_API_KEY and KITE_ACCESS_TOKEN are set, fetch via kiteconnect.KiteConnect(...).holdings()
     Falls back to file path on any auth error (TokenException etc.) with a one-line message, never a traceback.

overlay() joins holdings on ISIN (fallback: symbol) with scan and enriched data.
Holdings NOT in scan (>26% below ATH or outside index) are retained with NOT_IN_SCAN marker.

Portfolio-level summary includes total invested/value/pnl, holdings by bucket, concentration flags.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

# Fallback import handling for kiteconnect (not available in test mocks)
try:
    from kiteconnect import KiteConnect, TokenException
except ImportError:
    KiteConnect = None  # type: ignore
    TokenException = Exception  # type: ignore


def load_holdings(file_path: Optional[str] = None, verbose: bool = False) -> pd.DataFrame:
    """Load holdings from file (JSON or CSV) or Kite API if credentials are available.

    Args:
        file_path: Explicit path to holdings file (JSON or CSV). If None, tries:
                   1. Kite API (if KITE_API_KEY and KITE_ACCESS_TOKEN set) with file fallback
                   2. Default file locations: data/holdings.json or data/holdings.csv
        verbose: Print debug info

    Returns:
        DataFrame with columns: tradingsymbol, exchange, isin, quantity, t1_quantity,
                               average_price, last_price, pnl, day_change_percentage
    """
    load_dotenv()

    # Try LIVE path if credentials are available
    api_key = os.environ.get("KITE_API_KEY")
    access_token = os.environ.get("KITE_ACCESS_TOKEN")

    if api_key and access_token and KiteConnect is not None:
        try:
            if verbose:
                print("Loading holdings from Kite API...")
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            holdings = kite.holdings()
            df = pd.DataFrame(holdings)
            if verbose:
                print(f"  Loaded {len(df)} holdings from Kite API")
            return df
        except Exception as e:  # Catch TokenException and any other auth errors
            if verbose:
                print(f"Kite API unavailable ({type(e).__name__}), falling back to file...")

    # FILE path: explicit path, then defaults
    search_paths = []
    if file_path:
        search_paths = [Path(file_path)]
    else:
        search_paths = [Path("data/holdings.json"), Path("data/holdings.csv")]

    for path in search_paths:
        if path.exists():
            if verbose:
                print(f"Loading holdings from {path}...")
            if path.suffix.lower() == ".json":
                df = pd.read_json(path)
            else:  # .csv
                df = pd.read_csv(path)
            if verbose:
                print(f"  Loaded {len(df)} holdings from {path}")
            return df

    # No source found
    return pd.DataFrame()


def overlay(
    holdings_df: pd.DataFrame,
    scan_df: pd.DataFrame,
    enriched_df: Optional[pd.DataFrame] = None,
    verbose: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Join holdings with scan and enriched data, compute portfolio summary.

    Args:
        holdings_df: DataFrame from load_holdings() with tradingsymbol, isin, quantity, etc.
        scan_df: ATH scan output with symbol, bucket, distance_pct, above_ema50, above_sma200, etc.
        enriched_df: Optional enrichment output with order_significance, revenue columns, etc.
        verbose: Print debug info

    Returns:
        (portfolio_df, summary_dict) where:
        - portfolio_df has every holding plus scan/enrichment data where available
        - summary_dict has total_invested, total_value, total_pnl, holdings_by_bucket, attention_flags, etc.
    """
    if holdings_df.empty:
        return pd.DataFrame(), _empty_summary()

    # Normalize holdings: ensure key columns exist
    holdings_df = _normalize_holdings(holdings_df)

    # Build a lookup keyed by both ISIN and symbol for fallback joining
    scan_by_isin = {}
    scan_by_symbol = {}
    if "isin" in scan_df.columns:
        for _, row in scan_df.iterrows():
            isin_val = row.get("isin")
            if pd.notna(isin_val) and str(isin_val).strip():
                scan_by_isin[str(isin_val).upper()] = row.to_dict()
    for _, row in scan_df.iterrows():
        symbol_val = row.get("symbol")
        if pd.notna(symbol_val) and str(symbol_val).strip():
            scan_by_symbol[str(symbol_val).upper()] = row.to_dict()

    enriched_by_isin = {}
    enriched_by_symbol = {}
    if enriched_df is not None and not enriched_df.empty:
        if "isin" in enriched_df.columns:
            for _, row in enriched_df.iterrows():
                isin_val = row.get("isin")
                if pd.notna(isin_val) and str(isin_val).strip():
                    enriched_by_isin[str(isin_val).upper()] = row.to_dict()
        for _, row in enriched_df.iterrows():
            symbol_val = row.get("symbol")
            if pd.notna(symbol_val) and str(symbol_val).strip():
                enriched_by_symbol[str(symbol_val).upper()] = row.to_dict()

    # Build portfolio rows
    portfolio_rows = []
    for _, holding in holdings_df.iterrows():
        row = _overlay_holding(holding, scan_by_isin, scan_by_symbol,
                              enriched_by_isin, enriched_by_symbol)
        portfolio_rows.append(row)

    portfolio_df = pd.DataFrame(portfolio_rows)

    # Compute weights
    total_value = portfolio_df["current_value"].sum()
    portfolio_df["weight_pct"] = (portfolio_df["current_value"] / total_value * 100) if total_value > 0 else 0

    # Compute summary
    summary = _compute_summary(portfolio_df, scan_df if enriched_df is None else enriched_df)

    if verbose:
        print(f"Portfolio: {len(portfolio_df)} holdings, {summary['total_holdings_in_scan']} in scan")

    return portfolio_df, summary


def _normalize_holdings(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure holdings has required columns with proper names."""
    df = df.copy()

    # Rename if needed (Kite returns 'tradingsymbol', we use 'symbol')
    if "tradingsymbol" in df.columns and "symbol" not in df.columns:
        df["symbol"] = df["tradingsymbol"]

    # Normalize column names to lowercase
    df.columns = df.columns.str.lower()

    # Ensure key columns exist
    required = ["symbol", "quantity", "average_price", "last_price"]
    for col in required:
        if col not in df.columns:
            df[col] = None

    # ISIN is optional but useful for joining; leave as-is if missing
    if "isin" not in df.columns:
        df["isin"] = ""

    return df


def _overlay_holding(holding: pd.Series, scan_by_isin: dict, scan_by_symbol: dict,
                    enriched_by_isin: dict, enriched_by_symbol: dict) -> dict:
    """Build one portfolio row by joining a holding with scan/enrichment data."""
    symbol = str(holding.get("symbol", "")).upper().strip()
    isin = str(holding.get("isin", "")).upper().strip()
    quantity = float(holding.get("quantity", 0) or 0)
    avg_price = float(holding.get("average_price", 0) or 0)
    ltp = float(holding.get("last_price", 0) or 0)

    # Join with scan data
    scan_row = None
    if isin:
        scan_row = scan_by_isin.get(isin)
    if scan_row is None and symbol:
        scan_row = scan_by_symbol.get(symbol)

    # Join with enriched data (same fallback logic)
    enriched_row = None
    if isin:
        enriched_row = enriched_by_isin.get(isin)
    if enriched_row is None and symbol:
        enriched_row = enriched_by_symbol.get(symbol)

    # Compute portfolio metrics
    invested = quantity * avg_price
    current_value = quantity * ltp
    pnl = current_value - invested
    pnl_pct = (pnl / invested * 100) if invested > 0 else 0

    # Build output row
    row = {
        "symbol": symbol,
        "quantity": quantity,
        "avg_price": avg_price,
        "ltp": ltp,
        "invested": invested,
        "current_value": current_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "in_scan": "YES" if scan_row is not None else "NOT_IN_SCAN",
    }

    # Add scan columns if available
    if scan_row is not None:
        scan_cols = ["bucket", "distance_pct", "ath_date", "above_ema50", "above_sma200"]
        for col in scan_cols:
            row[col] = scan_row.get(col)
    else:
        for col in ["bucket", "distance_pct", "ath_date", "above_ema50", "above_sma200"]:
            row[col] = None

    # Add enriched columns if available and present
    if enriched_row is not None:
        enrich_cols = ["order_significance", "revenue_outlook", "guidance"]
        for col in enrich_cols:
            if col in enriched_row:
                row[col] = enriched_row.get(col)

    return row


def _compute_summary(portfolio_df: pd.DataFrame, ref_df: Optional[pd.DataFrame] = None) -> dict:
    """Compute portfolio-level summary statistics and ATTENTION flags."""
    if portfolio_df.empty:
        return _empty_summary()

    # Portfolio totals
    total_invested = portfolio_df["invested"].sum()
    total_value = portfolio_df["current_value"].sum()
    total_pnl = total_value - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    # Weights (use existing weight_pct if available, otherwise compute)
    portfolio_df = portfolio_df.copy()
    if "weight_pct" not in portfolio_df.columns:
        portfolio_df["weight_pct"] = (portfolio_df["current_value"] / total_value * 100) if total_value > 0 else 0

    # Count in scan
    in_scan = (portfolio_df["in_scan"] == "YES").sum()
    not_in_scan = len(portfolio_df) - in_scan

    # By bucket
    holdings_by_bucket = {}
    value_by_bucket = {}
    for bucket in portfolio_df["bucket"].unique():
        if pd.notna(bucket):
            mask = portfolio_df["bucket"] == bucket
            holdings_by_bucket[bucket] = int(mask.sum())
            value_by_bucket[bucket] = float(portfolio_df.loc[mask, "current_value"].sum())

    # ATTENTION flags
    flags = []

    # Flag 1: holdings in NEW_ATH_TODAY or 0-5% (momentum)
    momentum = portfolio_df[
        (portfolio_df["bucket"].isin(["NEW_ATH_TODAY", "0-5%"])) &
        (portfolio_df["in_scan"] == "YES")
    ]
    if not momentum.empty:
        flags.append(f"Momentum play: {len(momentum)} holding(s) in NEW_ATH_TODAY or 0-5% ({momentum['weight_pct'].sum():.1f}% of portfolio)")

    # Flag 2: holdings below 200 SMA (trend broken)
    below_sma = portfolio_df[
        (portfolio_df["above_sma200"] == False) &
        (portfolio_df["in_scan"] == "YES")
    ]
    if not below_sma.empty:
        flags.append(f"Trend broken: {len(below_sma)} holding(s) below 200 SMA ({below_sma['weight_pct'].sum():.1f}% of portfolio)")

    # Flag 3: single position > 15% (concentration)
    concentrated = portfolio_df[portfolio_df["weight_pct"] > 15]
    if not concentrated.empty:
        max_weight = concentrated["weight_pct"].max()
        max_symbol = concentrated.loc[concentrated["weight_pct"].idxmax(), "symbol"]
        flags.append(f"Concentration: {max_symbol} is {max_weight:.1f}% of portfolio (limit: 15%)")

    # Flag 4: holdings NOT_IN_SCAN
    if not_in_scan > 0:
        not_in_scan_value = portfolio_df[portfolio_df["in_scan"] == "NOT_IN_SCAN"]["current_value"].sum()
        flags.append(f"Not in scan: {not_in_scan} holding(s), {not_in_scan_value / total_value * 100:.1f}% of portfolio (>26% below ATH or outside index)")

    return {
        "total_invested": total_invested,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "total_holdings": len(portfolio_df),
        "total_holdings_in_scan": in_scan,
        "total_holdings_not_in_scan": not_in_scan,
        "holdings_by_bucket": holdings_by_bucket,
        "value_by_bucket": value_by_bucket,
        "largest_single_weight_pct": portfolio_df["weight_pct"].max() if not portfolio_df.empty else 0,
        "largest_single_symbol": portfolio_df.loc[portfolio_df["weight_pct"].idxmax(), "symbol"] if not portfolio_df.empty else "",
        "attention_flags": flags,
    }


def _empty_summary() -> dict:
    """Return an empty summary structure."""
    return {
        "total_invested": 0,
        "total_value": 0,
        "total_pnl": 0,
        "total_pnl_pct": 0,
        "total_holdings": 0,
        "total_holdings_in_scan": 0,
        "total_holdings_not_in_scan": 0,
        "holdings_by_bucket": {},
        "value_by_bucket": {},
        "largest_single_weight_pct": 0,
        "largest_single_symbol": "",
        "attention_flags": [],
    }
