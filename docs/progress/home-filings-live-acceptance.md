# Home filings live acceptance (F-T9)

Run this yourself; nothing here has been run. This page lists the steps to take the home_filings collector from wiring to a scheduled run. Use real tokens only from files outside the repo, and never paste them into chat or logs.

## Prerequisites

1. Apply migrations 050, 052 and 059 to the main database with `python -m scanner.pg.migrate`. Check with `python -m scanner.pg.migrate --status` that all three are listed as applied.
2. Apply `db/events_migrations/002_server_role_grants.sql` to the events database. Check with `python -m scanner.pg.migrate --db events --status`. If the runner does not pick this file up, apply it by hand as the admin role and say so.
3. Create the three token files outside the repo, each a random value of 32 or more characters, readable by your user only:
   - the collector token (used by the collector containers)
   - the home-events ingest token
   - the collector watchdog token
4. Set these in `.env`, pointing at the host paths of the files:
   - `APP_SERVICE_TOKEN_FILE`
   - `APP_HOME_EVENTS_INGEST_TOKEN_FILE`
   - `APP_COLLECTOR_WATCHDOG_TOKEN_FILE`
5. Set `WATCHDOG_TOKEN_FILE` in your user environment to the watchdog token file path. It is not read from `.env`.
6. Bring the stack up with `docker compose up -d`. Check that `GET http://127.0.0.1:8081/api/health` returns 200.

## Smoke: ingest is idempotent

Build one `curl` call yourself, with your ingest token read from its file, that POSTs one valid one-row batch to `http://127.0.0.1:8081/internal/events/batch`. Send the same body twice.

- First POST: inserted 1, duplicates 0.
- Second POST: inserted 0, duplicates 1.

Do not print the token in the command you keep.

## One manual run

1. Dry run: `docker compose --profile collectors run --rm --no-deps collector-home-filings --source home_filings --dry-run`
2. Real run: the same command without `--dry-run`.

Expect a `collector_runs` row for `home_filings` with status `ok`.

## Flip the schedule

The source stays `manual` until you change it. The request goes to the ui service on loopback:

```
PUT http://127.0.0.1:8080/api/config/home_filings
Content-Type: application/json

{"mode": "scheduled", "cron": "*/5 8-20 * * 1-5"}
```

Build the request yourself. The body shape comes from `ui/app/api.py` (`ConfigUpdateRequest`: `mode`, `cron`, optional `params`).

Then register the watchdog:

1. `scripts\register_watchdog_task.ps1 -WhatIf` and read the output.
2. `scripts\register_watchdog_task.ps1` for real.

## Acceptance

The checks O1 to O9 are listed in `docs/designs/t4f-mvp-plan.md` (around lines 61 to 69). O7 runs after the flip.

## Rollback

- Set the mode back to `manual` with the same `PUT`, using `{"mode": "manual", "cron": "*/5 8-20 * * 1-5"}`.
- Remove the watchdog task with `scripts\register_watchdog_task.ps1 -Unregister`.
