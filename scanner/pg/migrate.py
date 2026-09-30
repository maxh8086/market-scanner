"""Apply db/migrations/*.sql in filename order, once each. Safe to run on every start.

    python -m scanner.pg.migrate            # apply what is pending
    python -m scanner.pg.migrate --status   # list applied / pending

Each file runs in its own transaction and is recorded in schema_migrations, so a
half-applied file leaves nothing behind. Never edit an applied file: add a new one.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from . import db

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
_BOOT = """CREATE TABLE IF NOT EXISTS schema_migrations (
  filename text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"""


def files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def status() -> list[tuple[str, bool]]:
    with db.connect() as conn:
        conn.execute(_BOOT)
        done = {r["filename"] for r in conn.execute("SELECT filename FROM schema_migrations")}
    return [(f.name, f.name in done) for f in files()]


def apply() -> list[str]:
    applied = []
    with db.connect() as conn:
        conn.execute(_BOOT)
        conn.commit()
        done = {r["filename"]: r["sha256"] for r in conn.execute("SELECT filename, sha256 FROM schema_migrations")}
        for f in files():
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    if args.status:
        for name, ok in status():
            print(("applied  " if ok else "PENDING  ") + name)
        return 0
    done = apply()
    print("applied: " + ", ".join(done) if done else "schema is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
