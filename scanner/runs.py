"""Run history and stock snapshots.

Note on left_range: when a stock is absent in the current run but present in the
previous run by run_date, we create a stock_snapshots row with the last known values
(distance_pct, ltp, ath_high, ath_date) to hang the change on. The metrics jsonb
will hold the enriched row if available; missing data is noted in the snapshot_changes
note field.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Optional
from decimal import Decimal

import pandas as pd
import numpy as np

from .pg import db


def start_run(run_date: date, trigger: str = "manual") -> str:
    """Start a new run for the given trading date.

    Returns the uuid of the run, which is marked 'running' and is_current=false.
    The next finish_run with status='complete' will mark it current.
    """
    run_id = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO runs (run_id, run_date, trigger, status, is_current)
               VALUES (%s, %s, %s, 'running', false)""",
            (run_id, run_date, trigger)
        )
    return run_id


def begin_run(run_id: str, run_date: date, trigger: str = "manual") -> str:
    """Create the 'running' row for a run whose id the caller already chose.

    start.ps1 picks the id first so every stage can tag its LLM calls with it (the
    llm_calls foreign key needs the row to exist). Calling it twice is harmless.
    """
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO runs (run_id, run_date, trigger, status, is_current)
               VALUES (%s, %s, %s, 'running', false)
               ON CONFLICT (run_id) DO NOTHING""",
            (run_id, run_date, trigger))
    return run_id


def record_snapshots(run_id: str, enriched_df: pd.DataFrame,
                    conclusions: Optional[pd.DataFrame] = None) -> int:
    """Record one snapshot per symbol in the enriched data.

    Args:
        run_id: the run uuid
        enriched_df: the enriched CSV as a DataFrame (from ath_enriched_<date>.csv)
        conclusions: optional conclusions DataFrame (from ath_conclusions_<date>.csv).
                    If provided, stance and stance_score are taken from it.

    Returns the number of rows inserted/updated.

    The bucket values in the enriched CSV are mapped to the schema values:
    'NEW_ATH_TODAY', '0-5%', '5-15%', '15-26%' -> 'at_ath', 'within_5', 'within_10', 'within_26'
    """
    if conclusions is None:
        conclusions = pd.DataFrame()

    # Map the enriched bucket values to schema values
    bucket_map = {
        'NEW_ATH_TODAY': 'at_ath',
        '0-5%': 'within_5',
        '5-15%': 'within_10',
        '15-26%': 'within_26',
    }

    # Build conclusions lookup: symbol -> row dict
    conclusion_lookup = {}
    if not conclusions.empty:
        for _, row in conclusions.iterrows():
            conclusion_lookup[row['symbol']] = row.to_dict()

    count = 0
    with db.transaction() as conn:
        for _, row in enriched_df.iterrows():
            symbol = row['symbol']

            # Map bucket value
            bucket_raw = row.get('bucket', '')
            bucket = bucket_map.get(bucket_raw, bucket_raw)

            # Get conclusion data if available
            stance = None
            stance_score = None
            if symbol in conclusion_lookup:
                conc_row = conclusion_lookup[symbol]
                stance = conc_row.get('stance')
                # The schema stores lower case; conclude.py emits CONSTRUCTIVE / MIXED / CAUTIOUS.
                stance = stance.lower() if isinstance(stance, str) and stance.strip() else None
                stance_score = conc_row.get('stance_score')
                # Handle NaN values
                if pd.isna(stance_score):
                    stance_score = None

            # Build metrics jsonb: the entire enriched row, with NaN -> null
            metrics = {}
            for col in enriched_df.columns:
                val = row[col]
                if pd.isna(val):
                    metrics[col] = None
                elif isinstance(val, np.integer):
                    metrics[col] = int(val)
                elif isinstance(val, np.floating):
                    metrics[col] = float(val)
                elif isinstance(val, (int, float)):
                    metrics[col] = val
                else:
                    metrics[col] = str(val)

            # Extract typed columns
            ltp = _to_decimal(row.get('ltp'))
            ath_high = _to_decimal(row.get('ath_high'))
            ath_date_val = row.get('ath_date')
            if pd.notna(ath_date_val):
                ath_date_val = pd.to_datetime(ath_date_val).date()
            else:
                ath_date_val = None
            distance_pct = _to_decimal(row.get('distance_pct'))
            one_year_return = _to_decimal(row.get('yoy_growth_pct'))
            order_pct_of_sales = _to_decimal(row.get('order_pct_of_sales'))

            isin = row.get('isin')
            if pd.isna(isin):
                isin = None

            conn.execute(
                """INSERT INTO stock_snapshots
                   (run_id, symbol, isin, company, industry, ltp, ath_high, ath_date,
                    distance_pct, bucket, one_year_return_pct, order_pct_of_sales,
                    stance, stance_score, metrics)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (run_id, symbol) DO UPDATE SET
                   isin = EXCLUDED.isin, company = EXCLUDED.company,
                   industry = EXCLUDED.industry, ltp = EXCLUDED.ltp,
                   ath_high = EXCLUDED.ath_high, ath_date = EXCLUDED.ath_date,
                   distance_pct = EXCLUDED.distance_pct, bucket = EXCLUDED.bucket,
                   one_year_return_pct = EXCLUDED.one_year_return_pct,
                   order_pct_of_sales = EXCLUDED.order_pct_of_sales,
                   stance = EXCLUDED.stance, stance_score = EXCLUDED.stance_score,
                   metrics = EXCLUDED.metrics""",
                (run_id, symbol, isin, row.get('company'), row.get('industry'),
                 ltp, ath_high, ath_date_val, distance_pct, bucket,
                 one_year_return, order_pct_of_sales, stance, stance_score,
                 json.dumps(metrics))
            )
            count += 1

    return count


def compute_changes(run_id: str, order_book_threshold: float = 0.5,
                   capacity_threshold: float = 0.3, new_filings_count: int = 0) -> int:
    """Compute timeline changes for a completed run.

    Compares each snapshot in this run with the same symbol's snapshot in the
    previous run by run_date, and writes snapshot_changes rows.

    Args:
        run_id: the run uuid
        order_book_threshold: order_pct_of_sales change threshold for new_order_book
        capacity_threshold: for capacity_change detection
        new_filings_count: count of new filings in Mongo since previous run (optional)

    Returns the number of change rows written.
    """
    ORDER_BOOK_THRESHOLD = order_book_threshold
    CAPACITY_THRESHOLD = capacity_threshold

    count = 0
    with db.transaction() as conn:
        # Get the run's run_date
        run_row = conn.execute(
            "SELECT run_date FROM runs WHERE run_id = %s",
            (run_id,)
        ).fetchone()
        if not run_row:
            return 0
        run_date = run_row['run_date']

        # Get the previous run by run_date (latest earlier date)
        prev_row = conn.execute(
            """SELECT run_id FROM runs
               WHERE run_date < %s AND is_current
               ORDER BY run_date DESC LIMIT 1""",
            (run_date,)
        ).fetchone()
        if not prev_row:
            # No previous run; no changes to compute (first run)
            return 0

        prev_run_id = prev_row['run_id']

        # Get all symbols in current run
        current_symbols = set()
        for row in conn.execute(
            "SELECT DISTINCT symbol FROM stock_snapshots WHERE run_id = %s",
            (run_id,)
        ):
            current_symbols.add(row['symbol'])

        # Get all symbols in previous run
        prev_symbols = {}
        for row in conn.execute(
            "SELECT symbol FROM stock_snapshots WHERE run_id = %s",
            (prev_run_id,)
        ):
            symbol = row['symbol']
            prev_symbols[symbol] = True

        # Check for new symbols (entered_range)
        for symbol in current_symbols:
            if symbol not in prev_symbols:
                # New entry
                curr = conn.execute(
                    """SELECT metrics, distance_pct, bucket
                       FROM stock_snapshots WHERE run_id = %s AND symbol = %s""",
                    (run_id, symbol)
                ).fetchone()
                _insert_change(conn, run_id, symbol, 'entered_range',
                              before=None,
                              after=json.dumps({'distance_pct': float(curr['distance_pct']),
                                              'bucket': curr['bucket']}),
                              note="First appearance in range")
                count += 1

        # Check for removed symbols (left_range)
        for symbol in prev_symbols:
            if symbol not in current_symbols:
                # Symbol left the range; create a snapshot row with last known values
                prev = conn.execute(
                    """SELECT distance_pct, ltp, ath_high, ath_date, metrics
                       FROM stock_snapshots WHERE run_id = %s AND symbol = %s""",
                    (prev_run_id, symbol)
                ).fetchone()
                if prev:
                    # Insert a snapshot row for this left_range event
                    metrics = prev['metrics'] or {}
                    conn.execute(
                        """INSERT INTO stock_snapshots
                           (run_id, symbol, distance_pct, bucket, metrics)
                           VALUES (%s, %s, %s, 'left_range', %s)
                           ON CONFLICT (run_id, symbol) DO NOTHING""",
                        (run_id, symbol, prev['distance_pct'],
                         json.dumps(metrics))
                    )
                    _insert_change(conn, run_id, symbol, 'left_range',
                                  before=json.dumps({'distance_pct': float(prev['distance_pct'])}),
                                  after=None,
                                  note="Left the range; showing last known values")
                    count += 1

        # Check for changes in remaining symbols
        for symbol in current_symbols:
            if symbol in prev_symbols:
                curr = conn.execute(
                    """SELECT distance_pct, bucket, stance, order_pct_of_sales, metrics
                       FROM stock_snapshots WHERE run_id = %s AND symbol = %s""",
                    (run_id, symbol)
                ).fetchone()
                prev = conn.execute(
                    """SELECT distance_pct, bucket, stance, order_pct_of_sales, metrics
                       FROM stock_snapshots WHERE run_id = %s AND symbol = %s""",
                    (prev_run_id, symbol)
                ).fetchone()

                # Bucket change
                if prev['bucket'] != curr['bucket']:
                    _insert_change(conn, run_id, symbol, 'bucket_change',
                                  before=json.dumps({'bucket': prev['bucket']}),
                                  after=json.dumps({'bucket': curr['bucket']}),
                                  note=f"Moved from {prev['bucket']} to {curr['bucket']}")
                    count += 1

                # Stance change
                if prev['stance'] != curr['stance']:
                    _insert_change(conn, run_id, symbol, 'stance_change',
                                  before=json.dumps({'stance': prev['stance']}),
                                  after=json.dumps({'stance': curr['stance']}),
                                  note=f"Stance changed from {prev['stance']} to {curr['stance']}")
                    count += 1

                # Order book change
                prev_order = float(prev['order_pct_of_sales'] or 0)
                curr_order = float(curr['order_pct_of_sales'] or 0)
                if abs(prev_order - curr_order) > ORDER_BOOK_THRESHOLD:
                    _insert_change(conn, run_id, symbol, 'new_order_book',
                                  before=json.dumps({'order_pct_of_sales': prev_order}),
                                  after=json.dumps({'order_pct_of_sales': curr_order}),
                                  note=f"Order book ratio changed from {prev_order:.2f}% to {curr_order:.2f}%")
                    count += 1

        # new_filing, capacity_change handled separately if needed
        # For now, they require external data (Mongo, SEBI), handled by caller

    return count


def finish_run(run_id: str, status: str, **fields) -> None:
    """Mark a run as complete, and atomically update current flag if needed.

    When status='complete', marks the previous current run of the same date as
    is_current=false, and marks this one as is_current=true, in one transaction.
    This prevents the partial unique index violation.

    Args:
        run_id: the run uuid
        status: 'complete', 'failed', or 'partial'
        **fields: optional run columns to update (git_sha, model, gpu_name, etc.)
    """
    with db.transaction() as conn:
        # Get the run's run_date
        run_row = conn.execute(
            "SELECT run_date FROM runs WHERE run_id = %s",
            (run_id,)
        ).fetchone()
        if not run_row:
            return

        run_date = run_row['run_date']

        # Build the update statement dynamically
        set_parts = ["status = %s", "finished_at = now()"]
        params = [status]

        for key, val in fields.items():
            set_parts.append(f"{key} = %s")
            params.append(val)

        params.append(run_id)

        # If status is 'complete', also handle is_current
        if status == 'complete':
            set_parts.append("is_current = true")
            # First, mark any existing current run of this date as non-current
            conn.execute(
                """UPDATE runs SET is_current = false
                   WHERE run_date = %s AND is_current = true AND run_id != %s""",
                (run_date, run_id)
            )

        update_sql = f"""UPDATE runs SET {', '.join(set_parts)}
                         WHERE run_id = %s"""
        conn.execute(update_sql, params)


def _to_decimal(val) -> Optional[Decimal]:
    """Convert a value to Decimal or None if NaN/None."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return Decimal(str(val))
    except (ValueError, TypeError):
        return None


def _insert_change(conn, run_id: str, symbol: str, kind: str,
                  before: Optional[str], after: Optional[str],
                  note: Optional[str]) -> None:
    """Insert a snapshot_change row, skipping duplicates."""
    conn.execute(
        """INSERT INTO snapshot_changes (run_id, symbol, kind, before, after, note)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (run_id, symbol, kind) DO NOTHING""",
        (run_id, symbol, kind, before, after, note)
    )


