#!/usr/bin/env python3
"""Record a completed run to the database.

Used at the end of the pipeline to capture enriched data and conclusions,
record snapshots, compute changes, and finish the run.

    python record_run.py --run-id <uuid> --date <YYYY-MM-DD> \
        [--enriched PATH] [--conclusions PATH]

Conclusions come from output/ath_conclusions_<date>.csv if not provided.
If conclusions are missing, the run status is recorded as 'partial'.

Exit codes:
    0: success
    3: Postgres unreachable (warning, not a pipeline failure)
    1: other errors
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from scanner import runs
from scanner.pg import db


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True, help="run uuid")
    ap.add_argument("--date", required=True, help="run date (YYYY-MM-DD)")
    ap.add_argument("--enriched", help="path to ath_enriched_<date>.csv")
    ap.add_argument("--conclusions", help="path to ath_conclusions_<date>.csv")
    ap.add_argument("--begin", action="store_true",
                    help="only create the 'running' row for --run-id (start of a run), then exit")
    ap.add_argument("--fail", action="store_true",
                    help="mark the 'running' row for --run-id as failed (pipeline aborted), then exit")
    ap.add_argument("--trigger", default="manual", choices=["manual", "schedule"])
    args = ap.parse_args(argv)

    # Parse date
    try:
        run_date = pd.to_datetime(args.date).date()
    except Exception as e:
        print(f"Invalid date: {args.date}: {e}", file=sys.stderr)
        return 1

    # Check Postgres availability
    if not db.available():
        print("Postgres is not reachable", file=sys.stderr)
        return 3

    # Apply migrations
    try:
        from scanner.pg import migrate
        migrate.apply()
    except Exception as e:
        print(f"Failed to apply migrations: {e}", file=sys.stderr)
        return 1

    if args.begin:
        runs.begin_run(args.run_id, run_date, args.trigger)
        print(f"Run {args.run_id[:8]}... started for {run_date}")
        return 0

    if args.fail:
        runs.finish_run(args.run_id, "failed")
        print(f"Run {args.run_id[:8]}... marked failed")
        return 0

    # Load enriched CSV
    if args.enriched:
        enriched_path = Path(args.enriched)
    else:
        enriched_path = Path(__file__).parent / "output" / f"ath_enriched_{run_date}.csv"

    if not enriched_path.exists():
        print(f"Enriched CSV not found: {enriched_path}", file=sys.stderr)
        return 1

    try:
        enriched_df = pd.read_csv(enriched_path)
        print(f"Loaded {len(enriched_df)} enriched rows from {enriched_path.name}")
    except Exception as e:
        print(f"Failed to load enriched CSV: {e}", file=sys.stderr)
        return 1

    # Load conclusions CSV if available
    conclusions_df = None
    if args.conclusions:
        conclusions_path = Path(args.conclusions)
    else:
        conclusions_path = Path(__file__).parent / "output" / f"ath_conclusions_{run_date}.csv"

    if conclusions_path.exists():
        try:
            conclusions_df = pd.read_csv(conclusions_path)
            print(f"Loaded {len(conclusions_df)} conclusion rows from {conclusions_path.name}")
        except Exception as e:
            print(f"Warning: failed to load conclusions CSV: {e}")
            conclusions_df = None
    else:
        print(f"Warning: conclusions CSV not found, run will be marked 'partial'")

    # Record snapshots
    try:
        snapshot_count = runs.record_snapshots(args.run_id, enriched_df, conclusions_df)
        print(f"Recorded {snapshot_count} snapshots")
    except Exception as e:
        print(f"Failed to record snapshots: {e}", file=sys.stderr)
        runs.finish_run(args.run_id, "failed")
        return 1

    # Compute changes
    try:
        change_count = runs.compute_changes(args.run_id)
        print(f"Computed {change_count} changes")
    except Exception as e:
        print(f"Failed to compute changes: {e}", file=sys.stderr)
        runs.finish_run(args.run_id, "failed")
        return 1

    # Finish run
    status = "partial" if conclusions_df is None else "complete"
    try:
        runs.finish_run(args.run_id, status)
        print(f"Finished run with status '{status}'")
    except Exception as e:
        print(f"Failed to finish run: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
