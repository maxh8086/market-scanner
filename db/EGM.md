# db Blueprint

## Overview
Postgres schema for the project. There are two independent databases, and
`scanner/pg/migrate.py` applies one folder to each:

- `migrations/` applies to the main database (runs, snapshots, market data,
  fundamentals, collector, secrets and token alerts).
- `events_migrations/` applies to the events database (home events feed).

Files apply in filename order. Each file is plain SQL, and later files use
`IF NOT EXISTS` or `ALTER` on objects created earlier. Reverse scripts live in
each folder's `down/` subfolder.

## Subdirectories & Boundaries
- [migrations](./migrations/EGM.md): main database schema, 001 through 046.
- [events_migrations](./events_migrations/EGM.md): events database schema.
