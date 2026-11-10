# Requests to the collector-split spec owner

Date: 2026-11-10. From: the home-events filings work. To: the user, who owns `docs/designs/collector-split-spec.md`.

The user owns the split spec and receives this file directly. The split spec is not edited by this work.

Source: `docs/designs/home-events-filings-spec.md` section 2 (the table at lines 36 to 44), and `docs/progress/home-events-filings-spec-review3.md`, "Still outstanding". The filings spec is described as approved (revision 4, 2026-11-10); the overview calls it a draft, so this status is to confirm. Four of its first tasks are built and merged: T2a (PR 75), T3a (PR 76), T4a (PR 77), T5a (PR 78).

## What the filings spec needs from the split spec

| Slice | Request | Why |
|---|---|---|
| S1a | Add: `run()` may return `status` in `ok`, `failed`, `skipped`; `execute_source` persists it with counts and `message`; run-once exits non-zero on `failed`. With a test. | Without it a blocked run records `ok`. |
| S1a, S3 | Add: how run-once learns a source is an events source. The filings spec uses a class attribute `events_source = True` (task T4d). | Run-once needs the API-health check for events sources only. |
| S3 | Add: Fastify `server` containerised and reachable from collector containers. Today Fastify binds `127.0.0.1:8081` on the host, so no container reaches it. Internal routes are token-gated on the same port as `/api/*`. | Collector posts events through Fastify (filings spec D9). |
| S4 | Add: the watchdog finalises a `running` row when it kills a container (`failed`, message `killed`), with max-runtime in `config/collector_runtime.json`. Value for `home_filings`: 330 s. | Filings spec 5.3: worst case 224 s run plus container start; the run deadline is 240 s. |
| S5a | Add: an `exchange` field per entry in `config/collector_services.json` (`home_filings` is `nse`), so `GET /internal/due` omits a source whose host row in `source_cooldown` is active. Hosts created at run time by `ensure_source_row` are not in that file, so the fetcher must also check its host's row before each request (decisions A9, item 8). | Cooldown per host key (2026-11-10). |
| S2, S5a | Cooldown table and rows for every collection host (added 2026-11-10; overview 7.3). (a) Rename `exchange_cooldown` to `source_cooldown`, keyed by host (the user agrees; you decide). Hosts and proposed keys: `nse`, `bse`, `upstox`, `screener`, `rbi`, `federal_reserve`, `fred`, `bls`, `mospi`, `investing_com`, `cnbc_tv18`. (b) Backoff classes (user, 2026-11-10): API class (`upstox`, `fred`) starts at 3 minutes, doubles to 6 minutes, caps at 15 minutes; other class (every other host, including `nse`, `bse` and `rbi`) starts at 15 minutes, doubles, caps at 1 hour. (c) Keep the per-key independence rule of 4.3a. (d) Add an idempotent function, name proposed `ensure_source_row(host, backoff_class)`, that creates a row the first time a host appears in an accepted Telegram link, with the other class as default (confirmed 2026-11-10; the function name is proposed). A host with no row gets one from this function before its first fetch. Design rules: decisions A9 (2026-11-10). | Overview 7.3, the news and macro docs, and decisions A2 status (2026-11-10). |
| S2 | Assign migration numbers. S2 claims 047, S2a "a number when written", S5a needs one and names none, S8's `filings` cron migration is a fourth claimant. The filings registration migration (shown as `NNN`) takes the next number after those. | Task T1 waits for the assignment. |

## Citations to repoint

The split spec cites "filings spec 4.7" for the fundamentals queue in four places: its 4.2, the 4.6 table "weekly sweep" row, S5a and S7. Section 4.7 of the filings spec is now a stub. Repoint all four to the future `fundamentals-trigger-spec.md` (not yet written).

## New since the filings review

- The events database has its own migration series (`db/events_migrations/`) with its own `schema_migrations`. All numbers in that series are allocated in one table, `docs/designs/home-event-sources.md` section 6.3. Those numbers are separate from the main-database numbers the split spec assigns. Do not use the events series for main-database work.
- Merged T2a changed `scanner/pg/db.py` (`dsn` and `connect` take an optional `dbname`) and `scanner/pg/migrate.py` (`--db {main,events}`, `target` argument, `apply_on`). If any split slice edits those two files, merge `main` into the slice branch first.
- The cron for filings is `*/5 8-20 * * 1-5` (IST), set together with the collector mode in task T9, not in the registration migration.
