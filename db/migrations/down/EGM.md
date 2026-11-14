# down

## Overview
Reverse migrations for the main database. Each script undoes one forward
migration in `../`. Only 045, 046 and 060 have a reverse script.

## Interface
- `045_app_secret.down.sql`: drops `app_secret`.
- `046_token_expiry_alert.down.sql`: drops `token_alert_sent`.
- `060_ath_scan_candidates.down.sql`: drops `ath_scan_candidates`.

## Invariants
- Each reverse script is the exact inverse of its forward migration and is
  written with `DROP TABLE IF EXISTS`, so it can be re-run safely.
- Reverse scripts are never applied automatically by `migrate.py`. They are
  run by hand.

## Side Effects
- Destructive: dropping a table deletes its stored rows. `app_secret` holds
  encrypted secrets, so rolling back 045 removes them.

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root.
