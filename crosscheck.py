#!/usr/bin/env python
"""Cross-check a scan's prices against independent sources (NSE Bhavcopy).

This tool compares a scan's LTP and ATH against NSE's public bhavcopy data,
providing an independent verification without calling Upstox. Useful for
detecting anomalies.

Usage:
    python crosscheck.py                          # latest scan in output/
    python crosscheck.py --scan output/ath_scan_2026-09-29.csv
    python crosscheck.py --date 2026-09-29
    python crosscheck.py --tol 1.0 --output-dir custom_output
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from scanner.crosscheck import NseBhavcopy, compare, check_ath, summarize_comparison


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description="Cross-check a scan's prices against NSE Bhavcopy."
    )
    p.add_argument(
        "--scan",
        type=str,
        default=None,
        help="Path to scan CSV (default: newest output/ath_scan_*.csv)",
    )
    p.add_argument(
        "--date",
        type=str,
        default=None,
        help="Scan date as YYYY-MM-DD (inferred from filename if not given)",
    )
    p.add_argument(
        "--tol",
        type=float,
        default=0.5,
        help="Tolerance in %% for close-price comparison (default 0.5)",
    )
    p.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Directory for output CSV (default: output)",
    )
    return p.parse_args()


def find_latest_scan(output_dir: str = "output") -> tuple[Path, date] | None:
    """Find the newest scan CSV in output_dir.

    Returns (path, date_from_filename) or None if not found.
    """
    output_path = Path(output_dir)
    if not output_path.exists():
        return None

    scans = sorted(output_path.glob("ath_scan_*.csv"), reverse=True)
    if not scans:
        return None

    # Extract date from filename ath_scan_YYYY-MM-DD.csv
    filename = scans[0].name
    date_str = filename.replace("ath_scan_", "").replace(".csv", "")
    try:
        scan_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        return scans[0], scan_date
    except ValueError:
        return None


def main() -> int:
    """Run cross-check and return exit code (0 = OK, 1 = divergences found)."""
    args = parse_args()

    # Determine scan file and date
    if args.scan:
        scan_path = Path(args.scan)
        if not scan_path.exists():
            print(f"Error: scan file not found: {scan_path}")
            return 1

        # Extract date from path if not given
        if args.date:
            scan_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        else:
            # Try to infer from filename
            try:
                date_str = scan_path.stem.replace("ath_scan_", "")
                scan_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                print("Error: unable to infer scan date; use --date")
                return 1
    else:
        # Find latest scan
        result = find_latest_scan(args.output_dir)
        if not result:
            print(f"Error: no scan CSV found in {args.output_dir}")
            return 1
        scan_path, scan_date = result

    if args.date:
        scan_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    print(f"Cross-checking {scan_path} (date: {scan_date})...")

    # Load scan
    try:
        scan_df = pd.read_csv(scan_path)
    except Exception as e:
        print(f"Error reading scan CSV: {e}")
        return 1

    if "symbol" not in scan_df.columns or "ltp" not in scan_df.columns:
        print("Error: scan CSV must have 'symbol' and 'ltp' columns")
        return 1

    # Compare LTP
    print("\nComparing LTP (close prices)...")
    source = NseBhavcopy()
    ltp_results = compare(scan_df, source, scan_date, tol_pct=args.tol)
    ltp_summary = summarize_comparison(ltp_results)

    print(f"  OK:       {ltp_summary['ok']:4d}")
    print(f"  DIVERGED: {ltp_summary['diverged']:4d}")
    print(f"  NO_DATA:  {ltp_summary['no_data']:4d}")
    print(f"  TOTAL:    {ltp_summary['total']:4d}")

    if ltp_summary["diverged"] > 0:
        print(f"\n  Top divergences:")
        for i, worst in enumerate(ltp_summary["worst_divergences"][:3], 1):
            diff = worst["diff_pct"]
            print(
                f"    {i}. {worst['symbol']}: scan={worst['scan_ltp']:.2f} "
                f"source={worst['source_close']:.2f} diff={diff:+.2f}%"
            )

    # Check ATH if column exists
    if "ath_high" in scan_df.columns and "ath_date" in scan_df.columns:
        print("\nComparing ATH (historical highs)...")
        ath_results = check_ath(scan_df, source, tol_pct=args.tol)
        ath_summary = summarize_comparison(ath_results)

        print(f"  OK:       {ath_summary['ok']:4d}")
        print(f"  DIVERGED: {ath_summary['diverged']:4d}")
        print(f"  NO_DATA:  {ath_summary['no_data']:4d}")
        print(f"  TOTAL:    {ath_summary['total']:4d}")

    # Write output CSV
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"crosscheck_{scan_date.isoformat()}.csv"
    ltp_results.to_csv(output_file, index=False)
    print(f"\nResults written to {output_file}")

    # Exit with appropriate code
    has_diverged = ltp_summary["diverged"] > 0
    if has_diverged:
        print("\n⚠ Divergences found. Exit code 1.")
        return 1
    else:
        print("\n✓ All checks passed. Exit code 0.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
