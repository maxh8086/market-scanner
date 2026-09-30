"""Scheduler: determine which sources are due, claim requests, record runs."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence
import uuid

import psycopg
import pytz
from croniter import croniter

from scanner.pg import db


def due_sources(now: datetime, settings: dict, last_runs: dict,
                tz: Optional[str] = None) -> list[str]:
    """Which sources should run now.

    A source is due if it's scheduled and a cron slot has occurred since the
    last run (or ever, if never run).

    Args:
        now: current time (e.g., datetime.now(UTC))
        settings: {source: {"mode": ..., "cron": ..., ...}}
        last_runs: {source: datetime} of last started_at (or None)
        tz: timezone for cron evaluation (default "Asia/Kolkata")

    Returns:
        list of source names that are due
    """
    if tz is None:
        tz = "Asia/Kolkata"

    # Ensure now is timezone-aware
    if now.tzinfo is None:
        now = pytz.UTC.localize(now)

    due = []

    for source, config in settings.items():
        if config.get("mode") != "scheduled":
            continue

        cron_expr = config.get("cron", "")
        if not cron_expr:
            continue

        last_run = last_runs.get(source)
        try:
            # Convert now to the cron evaluation timezone
            tz_obj = pytz.timezone(tz)
            now_in_tz = now.astimezone(tz_obj) if now.tzinfo else tz_obj.localize(now)

            # Get the most recent cron slot that should have run by now
            cron = croniter(cron_expr, now_in_tz, ret_type=datetime)
            most_recent_slot = cron.get_prev(datetime)

            if last_run is None:
                # Never run: we're due if a slot has run on/after today
                # (for weekday-constrained crons, this ensures Sunday never triggers Mon-Fri jobs)
                if most_recent_slot.date() >= now_in_tz.date():
                    due.append(source)
            elif most_recent_slot > last_run:
                # A new slot has occurred since last_run
                due.append(source)
        except Exception:
            continue

    return due


def claim_requests(conn: psycopg.Connection) -> list[dict]:
    """Claim and return all unclaimed collector_requests, one per source.

    Uses FOR UPDATE SKIP LOCKED to atomically claim one request per source
    and avoid double-running the same source. Returns a list of dicts with
    id, source, collector_run fields.
    """
    with conn.transaction():
        # Find one unclaimed request per source, claim it, and return it
        rows = conn.execute("""
            UPDATE collector_requests
            SET claimed_at = NOW()
            WHERE id = (
                SELECT id FROM collector_requests
                WHERE claimed_at IS NULL
                ORDER BY source, requested_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, source, collector_run
        """).fetchall()
    return rows


def start_run(conn: psycopg.Connection, source: str, trigger: str) -> uuid.UUID:
    """Record a new collector_runs row and return its id."""
    run_id = uuid.uuid4()
    conn.execute(
        """INSERT INTO collector_runs (id, source, trigger, status)
           VALUES (%s, %s, %s, %s)""",
        (run_id, source, trigger, "running")
    )
    conn.commit()
    return run_id


def finish_run(conn: psycopg.Connection, run_id: uuid.UUID, status: str,
               rows_fetched: int, rows_new: int, from_date, to_date,
               message: str = "") -> None:
    """Update a collector_runs row when done."""
    conn.execute(
        """UPDATE collector_runs
           SET status = %s, finished_at = NOW(),
               rows_fetched = %s, rows_new = %s,
               from_date = %s, to_date = %s, message = %s
           WHERE id = %s""",
        (status, rows_fetched, rows_new, from_date, to_date, message, run_id)
    )
    conn.commit()


def link_request_to_run(conn: psycopg.Connection, request_id: uuid.UUID,
                        run_id: uuid.UUID) -> None:
    """Link a collector_request to the run it triggered."""
    conn.execute(
        "UPDATE collector_requests SET collector_run = %s WHERE id = %s",
        (run_id, request_id)
    )
    conn.commit()


def get_settings(conn: psycopg.Connection) -> dict:
    """Load all collector_settings rows."""
    rows = conn.execute(
        "SELECT source, mode, cron, params FROM collector_settings"
    ).fetchall()
    return {row["source"]: dict(row) for row in rows}


def get_last_runs(conn: psycopg.Connection) -> dict:
    """Get the most recent started_at for each source."""
    rows = conn.execute(
        """SELECT DISTINCT ON (source) source, started_at
           FROM collector_runs
           ORDER BY source, started_at DESC"""
    ).fetchall()
    return {row["source"]: row["started_at"] for row in rows}


def is_running(conn: psycopg.Connection, source: str, timeout_seconds: int) -> bool:
    """Check if this source is already running (started within timeout).

    Args:
        conn: database connection
        source: source name
        timeout_seconds: consider a run "running" if started within this many seconds

    Returns:
        True if there's a 'running' row that was started within timeout
    """
    from datetime import timedelta
    cutoff = datetime.now(pytz.UTC) - timedelta(seconds=timeout_seconds)
    row = conn.execute(
        """SELECT 1 FROM collector_runs
           WHERE source = %s AND status = 'running' AND started_at > %s
           LIMIT 1""",
        (source, cutoff)
    ).fetchone()
    return bool(row)
