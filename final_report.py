"""Write a final Excel report from the latest enriched scan and conclusions."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from scanner.workbook import write_workbook


OUTPUT_DIR = Path("output")


def newest_enriched() -> Path | None:
    """Find the newest ath_enriched_*.csv file."""
    files = sorted(OUTPUT_DIR.glob("ath_enriched_*.csv"))
    return files[-1] if files else None


def newest_conclusions(date_stem: str) -> Path | None:
    """Find the conclusions CSV matching the given date stem."""
    path = OUTPUT_DIR / f"ath_conclusions_{date_stem}.csv"
    return path if path.exists() else None


def main(argv: list[str] | None = None) -> int:
    """Generate final Excel report."""
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--enriched",
        help="enriched CSV path (default: newest in output/)"
    )
    p.add_argument(
        "--conclusions",
        help="conclusions CSV path (default: matches enriched date stem)"
    )
    p.add_argument(
        "--output-dir",
        default="output",
        help="output directory (default: output/)"
    )
    args = p.parse_args(argv)

    # Find or validate enriched CSV
    enriched_path = Path(args.enriched) if args.enriched else newest_enriched()
    if not enriched_path or not enriched_path.exists():
        print("No output/ath_enriched_*.csv found. Run enrich.py --report first.")
        return 1

    # Extract date stem (ath_enriched_YYYY-MM-DD -> YYYY-MM-DD)
    date_stem = enriched_path.stem.replace("ath_enriched_", "")

    # Find or validate conclusions CSV
    if args.conclusions:
        conclusions_path = Path(args.conclusions)
        if not conclusions_path.exists():
            print(f"Conclusions file not found: {conclusions_path}")
            return 1
    else:
        conclusions_path = newest_conclusions(date_stem)
        if not conclusions_path:
            print(f"Warning: No conclusions CSV found for {date_stem}; will write empty conclusion columns.")

    # Read CSVs
    enriched_df = pd.read_csv(enriched_path)
    conclusions_df = pd.read_csv(conclusions_path) if conclusions_path else pd.DataFrame()

    # Write workbook
    output_path = write_workbook(enriched_df, conclusions_df, date_stem, output_dir=args.output_dir)
    print(output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
