# down

## Overview
Reverse migration for the events database.

## Interface
- `001_home_events.down.sql`: drops `home_events`.
- `003_server_role_select_grant.down.sql`: revokes the server login's `SELECT` on `home_events`.

## Invariants
- Written with `DROP TABLE IF EXISTS`, so re-running it is safe.
- Not applied automatically. It is run by hand.

## Side Effects
- Destructive: deletes every stored home event.

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root.
