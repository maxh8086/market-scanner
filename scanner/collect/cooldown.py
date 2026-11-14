"""Shared block cooldown over the source_cooldown table (migration 049).

Flat 1 hour per D7 (docs/designs/t4f-mvp-plan.md). Implements the Cooldown Protocol of
scanner/home_events.py (active / block / reset). The host is the cooldown key; only 'nse' is
used today, and nothing in this module names a host.

Each call opens one short transaction on a fresh connection and closes it. Errors propagate
(fail closed): run_cycle treats an exception as a failed cycle.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from scanner.pg import db

COOLDOWN = timedelta(hours=1)  # the only duration; no per-host or per-class variation.


def _check_host(host: str) -> None:
    if not isinstance(host, str) or host == "" or host != host.strip().lower():
        raise ValueError(f"host must be a non-empty lower-case str without surrounding space: {host!r}")


def _check_now(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")


class PgCooldown:
    def __init__(self, connect=db.connect):
        self._connect = connect

    def active(self, host: str, now: datetime) -> bool:
        _check_host(host)
        _check_now(now)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cooldown_until FROM source_cooldown WHERE host = %s", (host,)).fetchone()
        if row is None or row["cooldown_until"] is None:
            return False
        return row["cooldown_until"] > now

    def block(self, host: str, now: datetime, reason: str) -> None:
        _check_host(host)
        _check_now(now)
        until = now + COOLDOWN
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO source_cooldown (host, cooldown_until, reason, updated_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (host) DO UPDATE SET "
                "cooldown_until = GREATEST(source_cooldown.cooldown_until, EXCLUDED.cooldown_until), "
                "reason = CASE WHEN source_cooldown.cooldown_until IS NULL "
                "OR EXCLUDED.cooldown_until >= source_cooldown.cooldown_until "
                "THEN EXCLUDED.reason ELSE source_cooldown.reason END, "
                "updated_at = EXCLUDED.updated_at",
                (host, until, reason, now),
            )

    def reset(self, host: str, now: datetime | None = None) -> None:
        # Conditional: clears only a NULL or already-expired cooldown. An unexpired block was
        # written by another container during this run (two containers share the 'nse' row), and
        # reset must not erase it. now=None uses the database clock.
        _check_host(host)
        if now is not None:
            _check_now(now)
        with self._connect() as conn:
            conn.execute(
                "UPDATE source_cooldown SET cooldown_until = NULL, reason = NULL, updated_at = now() "
                "WHERE host = %s AND (cooldown_until IS NULL OR cooldown_until <= COALESCE(%s, now()))",
                (host, now),
            )
