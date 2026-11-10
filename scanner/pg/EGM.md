# pg

## Overview
Postgres plumbing: the connection helper, the migration runner, the SQLite to
Postgres importer, and the run and snapshot backfill.

## Interface
- `db.py`: `dsn`, `connect`, `transaction`, `available`, `_check_dsn_agrees`.
  Reads `POSTGRES_DSN`, or the `POSTGRES_*` parts when it is unset.
- `migrate.py`: `files`, `status`, `apply`, `apply_on`, `main`. Applies
  `db/migrations/*.sql` (main database) or `db/events_migrations/*.sql` (events
  database).
- `import_sqlite.py`: `import_candles`, `import_announcements`,
  `import_corporate_actions`, `import_symbol_stats`, `import_symbol_listing`,
  `main`.
- `backfill.py`: `backfill_run`, `get_change_summary`, `sample_timeline`, `main`.
  Fills `runs` and `stock_snapshots` from existing output files.

## Invariants
- `migrate.py` applies files in filename order, and each file runs once.
  `_check_target` and `_dbname` guard against applying a migration to the
  wrong database.
- `db.py` refuses a DSN that disagrees with the `POSTGRES_*` parts
  (`_check_dsn_agrees`).
- The SQLite importer is idempotent: a re-run does not duplicate rows.

## Side Effects
- DDL and inserts on Postgres when migrations, imports or backfills run.
- Reads the SQLite data files under `data/` during import.
- Reads output files under `output/` during backfill.

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root (covers
  `tests/test_pg_dsn.py`, `tests/test_import_sqlite.py`,
  `tests/test_pg_migrate_events.py`, `tests/test_backfill.py`).
