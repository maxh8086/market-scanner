"""Apply db/migrations/*.sql (main database) or db/events_migrations/*.sql (events database)
in filename order, once each. Safe to run on every start.

    python -m scanner.pg.migrate                  # main database: apply what is pending
    python -m scanner.pg.migrate --status         # main database: list applied / pending
    python -m scanner.pg.migrate --db events      # events database (POSTGRES_EVENTS_DB)
    python -m scanner.pg.migrate --db events --status

Each file runs in its own transaction and is recorded in that database's schema_migrations
table, so a half-applied file leaves nothing behind. Never edit an applied file: add a new one.
Files are globbed non-recursively, so the down/ folders never run.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from . import db

_DB_ROOT = Path(__file__).resolve().parents[2] / "db"
MIGRATION_DIRS = {"main": _DB_ROOT / "migrations", "events": _DB_ROOT / "events_migrations"}
MIGRATIONS = MIGRATION_DIRS["main"]  # kept for existing readers of the name
_BOOT = """CREATE TABLE IF NOT EXISTS schema_migrations (
  filename text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"""


def _check_target(target: str) -> None:
    if target not in MIGRATION_DIRS:
        raise ValueError(f"unknown migration target {target!r}; use 'main' or 'events'")


def _dbname(target: str) -> str | None:
    """None means the default database (main, unchanged). 'events' is POSTGRES_EVENTS_DB."""
    _check_target(target)
    if target == "main":
        return None
    return os.environ.get("POSTGRES_EVENTS_DB") or "market_scanner_events"


def files(target: str = "main") -> list[Path]:
    _check_target(target)
    return sorted(MIGRATION_DIRS[target].glob("*.sql"))


def status(target: str = "main") -> list[tuple[str, bool]]:
    _check_target(target)
    with db.connect(_dbname(target)) as conn:
        conn.execute(_BOOT)
        done = {r["filename"] for r in conn.execute("SELECT filename FROM schema_migrations")}
    return [(f.name, f.name in done) for f in files(target)]


def apply(target: str = "main") -> list[str]:
    _check_target(target)
    with db.connect(_dbname(target)) as conn:
        return apply_on(conn, target)


def apply_on(conn, target: str = "main") -> list[str]:
    """Apply the target's files on an open connection (tests use this to target a throwaway
    schema of the main database). The caller owns the connection."""
    _check_target(target)
    applied = []
    conn.execute(_BOOT)
    conn.commit()
    done = {r["filename"]: r["sha256"] for r in conn.execute("SELECT filename, sha256 FROM schema_migrations")}
    for f in files(target):
        sql = f.read_text(encoding="utf-8")
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        if f.name in done:
            if done[f.name] != digest:
                raise RuntimeError(f"{f.name} was edited after it was applied; add a new migration instead")
            continue
        with conn.transaction():
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (filename, sha256) VALUES (%s, %s)", (f.name, digest))
        applied.append(f.name)
    return applied


def main(argv=None) -> int:
    load_dotenv(find_dotenv(usecwd=True))  # same .env loading as scanner/upstox.py
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--db", choices=sorted(MIGRATION_DIRS), default="main",
                    help="which database: main (default) or events")
    args = ap.parse_args(argv)
    if args.status:
        for name, ok in status(args.db):
            print(("applied  " if ok else "PENDING  ") + name)
        return 0
    done = apply(args.db)
    print("applied: " + ", ".join(done) if done else "schema is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
