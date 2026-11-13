"""Scheduler: determine which sources are due, claim requests, record runs."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence
import uuid

import psycopg
import pytz
from croniter import croniter

from scanner.pg import db

# collector_runs.trigger accepts these two values (001_core.sql). Nothing else may be recorded.
TRIGGERS = ("schedule", "manual")


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


def claim_requests(conn: psycopg.Connection, exclude_sources: Sequence[str] = ()) -> list[dict]:
    """Claim and return the unclaimed collector_requests, one per source.

    DISTINCT ON (source) picks the oldest open request of each source. Postgres rejects
    FOR UPDATE together with DISTINCT, so the rows are locked in a second CTE that joins to
    those ids: FOR UPDATE OF SKIP LOCKED lets concurrent claimers take disjoint rows. The unique
    partial index collector_requests_one_open allows at most one open request per source.
    exclude_sources names sources that must not be claimed here (those with their own container).
    Their requests stay open for the container path. An empty exclude_sources excludes nothing.
    Returns a list of dicts with id, source, collector_run fields.
    """
    with conn.transaction():
        rows = conn.execute("""
            WITH candidates AS (
                SELECT DISTINCT ON (source) id
                FROM collector_requests
                WHERE claimed_at IS NULL AND source <> ALL(%s)
                ORDER BY source, requested_at
            ),
            locked AS (
                SELECT r.id
                FROM collector_requests r
                JOIN candidates c ON c.id = r.id
                WHERE r.claimed_at IS NULL
                FOR UPDATE OF r SKIP LOCKED
            )
            UPDATE collector_requests
            SET claimed_at = NOW()
            WHERE id IN (SELECT id FROM locked)
            RETURNING id, source, collector_run
        """, (list(exclude_sources),)).fetchall()
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


def record_skipped(conn: psycopg.Connection, source: str, trigger: str,
                   message: str) -> uuid.UUID:
    """Record a run that did not execute (status 'skipped') in one insert."""
    run_id = uuid.uuid4()
    conn.execute(
        """INSERT INTO collector_runs (id, source, trigger, status, finished_at, message)
           VALUES (%s, %s, %s, 'skipped', NOW(), %s)""",
        (run_id, source, trigger, message)
    )
    conn.commit()
    return run_id


# Spec 4.2 key rule. The lock is session-level: it stays held by the connection that took it
# until unlock() or until that connection closes (a crashed run releases it automatically).
_LOCK_KEY_SQL = "hashtext('collector:' || %s)"


def try_lock(conn: psycopg.Connection, source: str) -> bool:
    """Try the per-source advisory lock without waiting. True if this connection holds it."""
    row = conn.execute(
        f"SELECT pg_try_advisory_lock({_LOCK_KEY_SQL}) AS locked", (source,)
    ).fetchone()
    conn.commit()  # end the transaction; a session lock survives commit
    return bool(row["locked"])


def unlock(conn: psycopg.Connection, source: str) -> None:
    """Release the per-source advisory lock taken by try_lock on this connection."""
    conn.execute(f"SELECT pg_advisory_unlock({_LOCK_KEY_SQL})", (source,))
    conn.commit()


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
    """Link a collector_request to the run it triggered and mark it claimed.

    The container path (run-once --request-id) never goes through claim_requests, so the link
    also sets claimed_at (COALESCE keeps the value a serve claim already set)."""
    conn.execute(
        "UPDATE collector_requests SET collector_run = %s, claimed_at = COALESCE(claimed_at, NOW()) "
        "WHERE id = %s",
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
    """Get the most recent started_at of an ok run for each source.

    Only status 'ok' counts (ok-only rule, spec 4.2). A failed or skipped row must not hide
    a missed slot from the catch-up logic."""
    rows = conn.execute(
        """SELECT DISTINCT ON (source) source, started_at
           FROM collector_runs
           WHERE status = 'ok'
           ORDER BY source, started_at DESC"""
    ).fetchall()
    return {row["source"]: row["started_at"] for row in rows}


def get_last_attempts(conn: psycopg.Connection) -> dict:
    """Get the most recent started_at of any run that actually started, for each source.

    Counts runs with status ok, failed or running; skipped rows are excluded, so a skipped
    slot (api_unavailable, already_running) stays due and is caught up. A failed run waits
    for the next slot, so a failing source is not re-run every pass. Used only by the Python
    due check until S5a moves due logic to TypeScript. get_last_runs is unchanged."""
    rows = conn.execute(
        """SELECT DISTINCT ON (source) source, started_at
           FROM collector_runs
           WHERE status <> 'skipped'
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
