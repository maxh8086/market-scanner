#!/usr/bin/env python
"""Portfolio CLI: overlay Kite holdings on ATH scan and enriched data.

Usage:
    python portfolio.py [--holdings PATH] [--scan PATH] [--enriched PATH] [--output-dir DIR]

Defaults:
    --holdings: data/holdings.json or data/holdings.csv (or Kite API if KITE_API_KEY + KITE_ACCESS_TOKEN set)
    --scan: newest output/ath_scan_*.csv
    --enriched: newest output/ath_enriched_*.csv (optional)
    --output-dir: output

Outputs:
    output/portfolio_<date>.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

from scanner.portfolio import load_holdings, overlay

IST = timezone(timedelta(hours=5, minutes=30))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Overlay Kite holdings on ATH scan results.")
    p.add_argument("--holdings", type=str, default=None, help="Path to holdings file (JSON/CSV)")
    p.add_argument("--scan", type=str, default=None, help="Path to scan CSV (default: newest ath_scan_*.csv)")
    p.add_argument("--enriched", type=str, default=None, help="Path to enriched CSV (optional, default: newest ath_enriched_*.csv)")
    p.add_argument("--output-dir", type=str, default="output", help="Output directory (default: output)")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    return p.parse_args()


def find_latest(pattern: str, directory: str = "output") -> Path | None:
    """Find the latest file matching a glob pattern."""
    candidates = sorted(Path(directory).glob(pattern))
    return candidates[-1] if candidates else None


def main() -> int:
    args = parse_args()

    # Load holdings
    holdings_df = load_holdings(file_path=args.holdings, verbose=args.verbose)
    if holdings_df.empty:
        print(
            "Error: No holdings data found.\n\n"
            "Please provide holdings by either:\n"
            "  1. Saving a Kite holdings export to: data/holdings.json or data/holdings.csv\n"
            "  2. Setting KITE_API_KEY and KITE_ACCESS_TOKEN in .env\n"
            "     (you can get holdings from Kite MCP via: get_holdings -> save to data/holdings.json)\n\n"
            "Usage:\n"
            "  python portfolio.py --holdings PATH\n"
            "  python portfolio.py (auto-detects data/holdings.json or data/holdings.csv)"
        )
        return 2

    # Load scan
    scan_path = args.scan
    if not scan_path:
        scan_path = find_latest("ath_scan_*.csv", args.output_dir)
    if not scan_path or not Path(scan_path).exists():
        print(f"Error: Scan CSV not found (run ath_scan.py first or pass --scan PATH)")
        return 2
    scan_df = pd.read_csv(scan_path, keep_default_na=False)
    if args.verbose:
        print(f"Loaded scan: {scan_path} ({len(scan_df)} rows)")

    # Load enriched (optional)
    enriched_df = None
    enriched_path = args.enriched
    if not enriched_path:
        enriched_path = find_latest("ath_enriched_*.csv", args.output_dir)
    if enriched_path and Path(enriched_path).exists():
        enriched_df = pd.read_csv(enriched_path, keep_default_na=False)
        if args.verbose:
            print(f"Loaded enriched: {enriched_path} ({len(enriched_df)} rows)")
    else:
        if args.verbose:
            print("No enriched data provided (optional)")

    # Overlay
    portfolio_df, summary = overlay(holdings_df, scan_df, enriched_df, verbose=args.verbose)

    # Write output
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(IST).strftime("%Y-%m-%d")
    output_cols = [
        "symbol", "quantity", "avg_price", "ltp", "invested", "current_value",
        "pnl", "pnl_pct", "weight_pct", "in_scan",
        "bucket", "distance_pct", "ath_date", "above_ema50", "above_sma200",
    ]
    # Add enriched columns if present
    for col in ["order_significance", "revenue_outlook", "guidance"]:
        if col in portfolio_df.columns:
            output_cols.append(col)

    # Only output columns that exist
    output_cols = [col for col in output_cols if col in portfolio_df.columns]

    portfolio_df_out = portfolio_df[output_cols].copy() if output_cols else portfolio_df.copy()

    csv_path = out_dir / f"portfolio_{today}.csv"
    portfolio_df_out.to_csv(csv_path, index=False)
    print(f"\nWrote portfolio: {csv_path} ({len(portfolio_df)} holdings)")

    # Print summary
    print(f"\n{'='*60}")
    print(f"PORTFOLIO SUMMARY - {today}")
    print(f"{'='*60}")
    print(f"\nTotals:")
    print(f"  Invested:       {summary['total_invested']:,.0f} INR")
    print(f"  Current value:  {summary['total_value']:,.0f} INR")
    print(f"  P&L:            {summary['total_pnl']:,.0f} INR ({summary['total_pnl_pct']:.2f}%)")
    print(f"\nHoldings:")
    print(f"  Total:          {summary['total_holdings']}")
    print(f"  In scan:        {summary['total_holdings_in_scan']}")
    print(f"  Not in scan:    {summary['total_holdings_not_in_scan']}")

    if summary["holdings_by_bucket"]:
        print(f"\nBy bucket:")
        for bucket in ["NEW_ATH_TODAY", "0-5%", "5-15%", "15-26%"]:
            if bucket in summary["holdings_by_bucket"]:
                count = summary["holdings_by_bucket"][bucket]
                value = summary["value_by_bucket"].get(bucket, 0)
                pct = (value / summary['total_value'] * 100) if summary['total_value'] > 0 else 0
                print(f"  {bucket:<15} {count:>3} holdings, {value:>12,.0f} INR ({pct:>5.1f}%)")

    if summary["largest_single_weight_pct"] > 0:
        print(f"\nLargest position: {summary['largest_single_symbol']} ({summary['largest_single_weight_pct']:.1f}%)")

    if summary["attention_flags"]:
        print(f"\nATTENTION:")
        for flag in summary["attention_flags"]:
            print(f"  • {flag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
