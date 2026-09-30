"""Settings helpers: get, update, validate collector configuration.

Used by collect.py CLI and the UI backend (agent F).
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import psycopg
import psycopg.rows
from croniter import croniter

from scanner.pg import db
from scanner.collect.sources import SOURCES


def get_settings() -> dict:
    """Load collector_settings from Postgres.

    Returns:
        {source: {"source": ..., "mode": ..., "cron": ..., "params": ..., "updated_at": ...}, ...}
    """
    try:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT source, mode, cron, params, updated_at FROM collector_settings"
            ).fetchall()
            return {row["source"]: dict(row) for row in rows}
    except Exception:
        return {}


def update_setting(source: str, mode: Optional[str] = None,
                   cron: Optional[str] = None, params: Optional[dict] = None) -> None:
    """Update one source's collector_settings.

    Args:
        source: which source to update
        mode: 'scheduled' or 'manual', or None to keep current
        cron: 5-field cron expression, or None to keep current
        params: dict of source-specific params, or None to keep current

    Raises:
        ValueError: if source doesn't exist, cron is invalid, mode/params invalid
        RuntimeError: if Postgres is unreachable
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")

    if mode is not None and mode not in ("scheduled", "manual"):
        raise ValueError(f"mode must be 'scheduled' or 'manual', not {mode}")

    if cron is not None:
        try:
            croniter(cron)
        except Exception as e:
            raise ValueError(f"invalid cron expression: {e}")

    if params is not None:
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        # Validate known keys per source (reject unknown ones)
        valid_keys = _valid_param_keys(source)
        unknown = set(params.keys()) - valid_keys
        if unknown:
            raise ValueError(f"unknown param keys for {source}: {unknown}")

    # Build the UPDATE: only include what was passed
    with db.connect() as conn:
        if mode is not None or cron is not None or params is not None:
            updates = []
            values = []
            if mode is not None:
                updates.append("mode = %s")
                values.append(mode)
            if cron is not None:
                updates.append("cron = %s")
                values.append(cron)
            if params is not None:
                updates.append("params = %s")
                values.append(json.dumps(params))
            updates.append("updated_at = NOW()")

            query = f"UPDATE collector_settings SET {', '.join(updates)} WHERE source = %s"
            values.append(source)
            conn.execute(query, values)
            conn.commit()


def request_run(source: str) -> bool:
    """Queue a manual "Run now" request for a source.

    Uses the unique index on (source, claimed_at IS NULL) to ensure
    at most one unclaimed request per source. Returns whether a new
    request was queued (True) or one already existed (False).

    Args:
        source: which source to run

    Returns:
        True if a new request was inserted, False if one already existed

    Raises:
        ValueError: if source doesn't exist
        RuntimeError: if Postgres is unreachable
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")

    request_id = uuid.uuid4()
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO collector_requests (id, source)
                   VALUES (%s, %s)
                   ON CONFLICT DO NOTHING""",
                (request_id, source)
            )
            conn.commit()
            # Check if our insert succeeded (if we have the id, we inserted; if not, one existed)
            row = conn.execute(
                "SELECT 1 FROM collector_requests WHERE id = %s",
                (request_id,)
            ).fetchone()
            return bool(row)
    except Exception:
        raise RuntimeError(f"failed to queue request for {source}")


def list_runs(source: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List collector_runs, most recent first.

    Args:
        source: filter to one source, or None for all
        limit: max rows to return

    Returns:
        list of collector_runs rows as dicts
    """
    try:
        with db.connect() as conn:
            if source:
                rows = conn.execute(
                    """SELECT id, source, trigger, started_at, finished_at, status,
                              from_date, to_date, rows_fetched, rows_new, message
                       FROM collector_runs
                       WHERE source = %s
                       ORDER BY started_at DESC
                       LIMIT %s""",
                    (source, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, source, trigger, started_at, finished_at, status,
                              from_date, to_date, rows_fetched, rows_new, message
                       FROM collector_runs
                       ORDER BY started_at DESC
                       LIMIT %s""",
                    (limit,)
                ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _valid_param_keys(source: str) -> set[str]:
    """Valid parameter keys for each source.

    Used to reject unknown keys and provide validation.
    """
    valid = {
        "candles_eod": {"after_close_minutes", "note"},
        "announcements": {"min_history_years"},
        "corporate_actions": set(),
        "filings": {"only_new"},
        "fundamentals": {"refetch_only_on_new_result", "max_age_days"},
    }
    return valid.get(source, set())
