# events_migrations

## Overview
Migrations for the events database, which holds the home events feed. The
database is separate from the main one, and `scanner/pg/migrate.py` applies
this folder when given the events target.

## Interface
- `001_home_events.sql`: creates `home_events` with indexes
  `home_events_isin_pub_idx` and `home_events_pub_idx`.
- Child contract: [down](./down/EGM.md).

## Invariants
- Apply order is by filename. `001` is the only migration so far.
- Table names here must not collide with the main database, because the two
  databases are separate.

## Side Effects
- DDL on the events Postgres database when `migrate.py` runs with the events
  target.

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` (covers `tests/test_pg_migrate_events.py`).
