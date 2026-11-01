"""Backfill runs and stock_snapshots from existing output files.

Reads three run dates (2026-09-28, 09-29, 09-30) from output/ath_enriched_<date>.csv
and output/ath_conclusions_<date>.csv, creates runs and snapshots, then computes changes.

Idempotent: running twice adds nothing and changes nothing.

    python -m scanner.pg.backfill [--dry-run]
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from scanner import runs
from . import db


BACKFILL_DATES = [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)]
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def backfill_run(run_date: date) -> tuple[str, int, int]:
    """Backfill a single run date.

    Reads enriched and conclusions files, creates or reuses a run,
    records snapshots, and computes changes.

    Returns (run_id, snapshots_count, changes_count).
    """
    # Check if run already exists
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT run_id FROM runs WHERE run_date = %s AND trigger = 'backfill'",
            (run_date,)
        ).fetchone()
        if existing:
            run_id = str(existing['run_id'])
            print(f"{run_date}: run {run_id[:8]}... already exists, skipping")
            return (run_id, 0, 0)

    # Load enriched CSV
    enriched_path = OUTPUT_DIR / f"ath_enriched_{run_date}.csv"
    if not enriched_path.exists():
        print(f"{run_date}: {enriched_path} not found")
        return ("", 0, 0)

    enriched_df = pd.read_csv(enriched_path)

    # Load conclusions CSV if it exists
    conclusions_df = None
    conclusions_path = OUTPUT_DIR / f"ath_conclusions_{run_date}.csv"
    if conclusions_path.exists():
        conclusions_df = pd.read_csv(conclusions_path)
    else:
        print(f"{run_date}: {conclusions_path} not found, recording without conclusions")

    # Create run
    run_id = runs.start_run(run_date, trigger="backfill")
    print(f"{run_date}: created run {run_id[:8]}...")

    # Record snapshots
    snapshot_count = runs.record_snapshots(run_id, enriched_df, conclusions_df)
    print(f"  recorded {snapshot_count} snapshots")

    # Compute changes
    change_count = runs.compute_changes(run_id)
    print(f"  computed {change_count} changes")

    # Finish run
    runs.finish_run(run_id, "complete")

    return (run_id, snapshot_count, change_count)


def get_change_summary(run_id: str) -> dict:
    """Get a summary of changes for a run."""
    with db.connect() as conn:
        result = {}
        for kind in ['entered_range', 'left_range', 'bucket_change', 'stance_change',
                     'new_order_book', 'capacity_change', 'new_filing']:
            count = conn.execute(
                "SELECT COUNT(*) as n FROM snapshot_changes WHERE run_id = %s AND kind = %s",
                (run_id, kind)
            ).fetchone()['n']
            if count > 0:
                result[kind] = count
    return result


def sample_timeline(symbol: str) -> None:
    """Print a sample timeline for a symbol."""
    with db.connect() as conn:
        rows = list(conn.execute(
            """SELECT r.run_date, r.status, s.bucket, s.stance, s.distance_pct,
                      s.order_pct_of_sales
               FROM stock_snapshots s
               JOIN runs r ON s.run_id = r.run_id
               WHERE s.symbol = %s AND r.status IN ('complete', 'partial')
               ORDER BY r.run_date DESC""",
            (symbol,)
        ))
    if rows:
        print(f"\n  {symbol}:")
        for row in rows:
            print(f"    {row['run_date']} {row['status']}: bucket={row['bucket']}, "
                  f"stance={row['stance']}, distance={row['distance_pct']:.2f}%, "
                  f"order={row['order_pct_of_sales']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be done without writing to the database")
    args = ap.parse_args(argv)

    if args.dry_run:
        print("(dry-run mode: no database writes)")

    if not db.available():
        print("Postgres is not reachable; skipping backfill")
        return 3  # Same convention as graph_sync.py

    # Check if schema is up to date
    try:
        from . import migrate
        migrate.apply()
    except Exception as e:
        print(f"Failed to apply migrations: {e}")
        return 1

    print("\nBackfilling from existing output files...")

    total_snapshots = 0
    total_changes = 0
    all_run_ids = []

    for run_date in BACKFILL_DATES:
        if args.dry_run:
            print(f"{run_date}: would create run and record snapshots")
        else:
            run_id, snap_count, change_count = backfill_run(run_date)
            if run_id:
                all_run_ids.append(run_id)
                total_snapshots += snap_count
                total_changes += change_count

    print(f"\nBackfill complete:")
    print(f"  Total snapshots: {total_snapshots}")
    print(f"  Total changes: {total_changes}")

    # Print change summary
    if not args.dry_run and all_run_ids:
        print(f"\nChange summary:")
        for run_id in all_run_ids:
            changes = get_change_summary(run_id)
            if changes:
                run_row = None
                with db.connect() as conn:
                    run_row = conn.execute(
                        "SELECT run_date FROM runs WHERE run_id = %s",
                        (run_id,)
                    ).fetchone()
                if run_row:
                    print(f"  {run_row['run_date']}: {changes}")

        # Sample timeline for a few stocks
        print(f"\nSample timelines:")
        with db.connect() as conn:
            # Get a couple of symbols that have snapshots
            symbols = []
            for row in conn.execute(
                "SELECT DISTINCT symbol FROM stock_snapshots LIMIT 2"
            ):
                symbols.append(row['symbol'])

        for symbol in symbols:
            sample_timeline(symbol)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
