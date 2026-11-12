# Collector split: slice specifications S1a, S1b, S2, S3, S4, S5a

Status: DRAFT for user review. Not approved. No task is dispatched from this document. Nothing here edits `docs/designs/collector-split-spec.md` (user-owned).
Date: 2026-11-12. Parent: `docs/designs/collector-split-spec.md` (the "split spec", sections 4, 6 and 8). Inputs: `docs/progress/collector-split-spec-requests.md` (the requests file) and `docs/designs/home-events-filings-spec.md` sections 2, 4.1, 4.6 and 9 (the "filings spec").

## 0. How to read this draft

- Each slice gives: purpose; files to create or change; acceptance command; must not change; tool-call limit; dependencies; migration number.
- Where the split spec and the requests file disagree, this draft follows the requests file (it records the later decisions of 2026-11-10 and 2026-11-11) and lists the disagreement in section 9. The split spec itself is not touched.
- Names marked "(proposed)" are mine, not decided. Paths checked against the repo on 2026-11-12 are stated as facts; paths for new files are proposals.
- Acceptance command for every slice that touches Python: `C:/Users/vaibh/Downloads/Projects/Market-Scanner/.venv/Scripts/python.exe -m unittest discover -s tests -t . -q` (full run, must pass). Each slice also names its own test module for the fast loop. A skipped Postgres test is not a pass.
- Tool-call limit: the filings spec uses 25 per task and 40 for the large ones. Same here.
- Run branches: one branch and one merge per slice, each cut from current `main`. If a slice edits `scanner/pg/db.py` or `scanner/pg/migrate.py`, merge `main` into the branch first (T2a changed both).
- All slices: code and tests are dispatched through `tokenfrugal.dispatch_task` per the project rules, with Haiku as tracker and fallback. No secret value is read, printed or committed.

## 1. Migration numbers (all proposals, per the user's "you decide best" on T1)

| Number | Owner | Content |
|---|---|---|
| 047 | taken | `company_reference` |
| 048 | taken | `index_constituents` (latest file in `db/migrations/` on 2026-11-12) |
| 049 | S2 (already claimed in the split spec) | `source_cooldown` table, seed rows, grants for the collector role if any |
| 050 | S5a | `SELECT` grants to `market_scanner_app` on `collector_settings` and `source_cooldown` (both are new reads from Fastify); plus any `collector_requests` change S5a finds it needs |
| 051 | S8 | `filings` cron migration (`UPDATE ... WHERE value = <old default>`) |
| 052 | filings T1 | `home_filings` registration (`manual` mode) |
| S2a | later | "a number when written": next free number after 052 at that time |

Rules: numbers are assigned in merge order only if no slice merges out of this order; if two branches are open, the later one renumbers on merge. The events database has its own series (`db/events_migrations/`, numbers in `home-event-sources.md` 6.3) and is not used by any slice here. Each migration gets a down file in `db/migrations/down/` (manual, not run by the runner), following 047 and 048 (`047_company_reference.down.sql`, `048_index_constituents.down.sql`).

S1a, S1b and S3 add no migration (`skipped` is already allowed by `collector_runs.status`, `001_core.sql:104`). S4 adds none.

Why 050 holds only grants: the split spec puts the `SELECT` grants in S5a (4.2). Keeping the table in 049 and the grants in 050 means S2 can merge before the server exists, and the grant lands with the code that needs it.

## 2. Dependency map and build order

```
S0 (report only) -> S1a -> S1b
                 -> S2   (needs S0 only; can run in parallel with S1a)
S1a -> S5a (needs S2 for the cooldown table to read)
S1a + S5a -> S3
S3 + S5a -> S4
```

Corrected against the split spec's Depends column: S5a lists only S1a there, but it reads `source_cooldown` and grants `SELECT` on it, so it also needs S2 merged first (its tests need the table). S5a therefore depends on S1a and S2. S4 additionally needs S1a's `skipped` and `killed` handling to exist.

Recommended order: S0, then S1a and S2 in parallel (different files; merge S1a first because it edits `collect.py`), then S1b, S5a, S3, S4.

S0 is report only and gates S1a, S2 and S3 in the split spec. Everything below assumes the S0 note `docs/progress/collector-split-s0.md` exists. Where a slice needs an S0 fact, it says so.

---

## 3. Slice S1a: run-once, `execute_source`, status contract

**Purpose.** One shared function that runs a source and writes the run row, used by `serve`, `run` and a new `run-once`. It lets a source return `ok`, `failed` or `skipped`, takes a per-source advisory lock, and exits non-zero on failure. Without it a blocked run records `ok` (requests file, S1a row).

**Dependencies.** S0 (note exists). No other slice.

**Migration number.** None.

**Files to change (all verified to exist)**
- `collect.py` (repo root): extract `execute_source(name, trigger, request_id)` from the inline run-row logic of `cmd_serve` (`collect.py` `cmd_serve` at line 97; `cmd_run` at line 55 writes no run row today). Make `cmd_serve`, `cmd_run` and a new `cmd_run_once` call it. Add the `run-once --source <name> [--request-id <uuid>] [--dry-run]` sub-command. Honour `args.dry_run`. Exit codes: 0 on `ok` and `skipped`; non-zero on `failed`; 3 and no run row when Postgres is unreachable (M12).
- `scanner/collect/sources.py`: in the `Source` base class only, add the class attribute `events_source = False` (the attribute name is the filings spec's, T4d sets it to `True` on `HomeFilings`; this slice only adds the default) and document the return contract: `run()` may return `status` in `ok`, `failed`, `skipped`; a missing `status` means `ok`. No source is edited and none registered.
- `scanner/collect/scheduler.py`: `start_run` (line 96) and `finish_run` (line 108) gain a path that writes `skipped` with a `message` (no migration). `get_last_runs` (line 141) counts only `ok` runs as the last run (the ok-only rule). `due_sources` (line 15) is not otherwise changed: it is frozen after this fix and retired in S9.
- New test files or additions: `tests/test_collect_run_once.py` (new, proposed), additions to `tests/test_collect_scheduler.py` for the ok-only rule, and the UI run-listing check against `skipped` (`settings.py:173,183`, split spec S1a).

**Behaviour to build**
1. `execute_source` order: start run row; take `pg_try_advisory_lock(hashtext('collector:' || source))` on the run connection and hold it for the whole run; call the source; write `status`, counts and `message`; mark the request done if `request_id` is given; release. A second process that cannot take the lock writes `skipped`, message `already_running`, and exits 0.
2. Events-source guard: before the lock, if `source.events_source` is true, check Fastify health (`GET <EVENTS_API_BASE_URL>/api/health`). Not healthy: write `skipped`, message `api_unavailable`, no fetch, no cooldown change. The seven existing sources are not checked. The base-URL setting name is the filings spec's `EVENTS_API_BASE_URL` (non-secret config); its value is the S3 decision, so this slice reads it from the environment with no default and treats "unset" as unhealthy for an events source only.
3. `trigger` allows only `schedule` and `manual` (as today).
4. A source that raises: status `failed`, message is the redacted exception text (reuse the existing redaction used in `tests/test_collect_redaction.py`), exit non-zero.

**Acceptance command**
- Fast loop: `.venv/Scripts/python.exe -m unittest tests.test_collect_run_once tests.test_collect_scheduler tests.test_collect_sources -q`
- Gate: the full unittest run above.
- Test list (from the split spec S1a plus the requests file): unknown source rejected; run-once runs once, writes a run row and exits; `dry_run` honoured and writes no data; a run that cannot take the lock writes `skipped` / `already_running`; events-source skip on API down using a fake events source defined in the test (none is registered); a fake source returning `status: "failed"` makes run-once exit non-zero and the row `failed` with counts and message; a fake source returning `skipped` is persisted as `skipped`; ok-only last-run rule (a later `skipped` or `failed` row does not hide a missed slot); the UI run listing still works with a `skipped` row; Postgres unreachable exits 3 with no row.
- The lock and run-row tests use `tests/pgschema.py` against real Postgres.

**Must not change**
- `scanner/factors.py`, `scanner/marketdata/factors_postgres.py` and every source's `run()` body.
- The `SOURCES` registry and `tests/test_collect_sources.py` exact-set assertion at lines 171-175 (updated by the task that registers new sources, not here).
- `serve` behaviour for sources that exist today beyond writing rows through `execute_source` (same loop, same 60 s sleep).
- The `collector_runs` and `collector_requests` schema; no migration.
- The CSV outputs and `ath_scan` (S2a owns them).

**Tool-call limit.** 40.

**Notes for the filings work.** After this merges, T4d's prerequisite "split S1a" is met. The attribute name `events_source` is from the filings spec 5.1 and 9 (T4d).

---

## 4. Slice S1b: `init`, `collector_services.json`, request claiming

**Purpose.** Move the start-up duties of `serve` into a one-shot `init`, publish the list of sources that have their own container, and make manual requests claim one per source so the watchdog can start the right container.

**Dependencies.** S1a.

**Migration number.** None.

**Files to change**
- `collect.py`: new `init` sub-command that runs `settings.ensure_sources()` (`scanner/collect/settings.py:35`), `first_run.tick` (`scanner/collect/first_run.py:82`) and `split_registered` (`collect.py:44`), then exits. `serve` drops those three duties but keeps its loop for unmoved sources, and skips every source named in `config/collector_services.json`.
- `config/collector_services.json` (new, proposed shape): a JSON object mapping source name to `{"service": "<compose service>", "host": "<cooldown host>"}`. This slice creates it with an empty `sources` map; each move task (S6 to S8) and filings T9 add their source. The field name `host` vs `exchange` is a decision (section 9, Q3); this slice writes the loader to accept `host` and to reject unknown keys, so renaming later is one line.
- `scanner/collect/scheduler.py`: `claim_requests` (line 72) claims one open request per source (`DISTINCT ON (source)` or a per-source filter; unique partial index `collector_requests_one_open`). `link_request_to_run` (line 123) is called from `execute_source` when a request id is passed (it is defined but not called today).
- `start.ps1`: run `collect.py init` after migrations and before any collector or watchdog start. Edit only that call site; the host Node server start is S3's.
- New loader module for the services file: `scanner/collect/services.py` (new, proposed). A missing or invalid file is an error that names the key, not a silent empty list.
- Tests: `tests/test_collect_init.py` (new, proposed), additions to `tests/test_collect_scheduler.py`.

**Acceptance command**
- Fast loop: `.venv/Scripts/python.exe -m unittest tests.test_collect_init tests.test_collect_scheduler -q`
- Gate: full unittest run.
- Tests: `init` creates the settings rows and is idempotent on a second run; `serve` skips a source listed in the services file and still runs an unlisted one; `claim_requests` returns exactly one request per source when two are open for different sources and never two for the same source; `link_request_to_run` is called and the request row references the run; the services loader rejects an unknown key.

**Must not change**
- `execute_source`'s status contract (S1a) and the exit codes.
- The `collector_requests` schema and its unique partial index.
- `scanner/collect/sources.py` registrations.
- Anything outside `start.ps1`'s init call.

**Tool-call limit.** 25.

---

## 5. Slice S2: `source_cooldown` table and the backoff module

**Purpose.** One shared table in the main database holding one cooldown row per host, read before each fetch and written on a block, so every container obeys a block that another container saw. Implements the requests file row for S2 and S5a: host-keyed, two backoff classes, `ensure_source_row`.

**Dependencies.** S0 (existing pacing and symbol-update job name feed the acceptance tests). Independent of S1a.

**Migration number.** 049 (already claimed). Table name: `source_cooldown`. Because `exchange_cooldown` was never created (the grep of the repo shows no table or code of that name), this slice creates `source_cooldown` directly; no rename step exists. The split spec's name `exchange_cooldown` is superseded (section 9, Q4).

**Files to create or change**
- `db/migrations/049_source_cooldown.sql` (new): the table and seed rows (DDL below).
- `db/migrations/down/049_source_cooldown.down.sql` (new, manual).
- `scanner/collect/cooldown.py` (new, proposed): the shared module. Public functions (names proposed; the filings spec 5.1 calls `cooldown.block(host, ...)`, `cooldown.reset(host)` and reads the cooldown before each request, so those three keep those names):
  - `ensure_source_row(host, backoff_class='other')`: idempotent insert (`ON CONFLICT DO NOTHING`); called the first time a host appears in an accepted Telegram link and before the first fetch of any host with no row.
  - `active(host, now=None) -> bool` and `cooldown_until(host)`.
  - `block(host, reason, now=None)`: sets `cooldown_until = now + backoff`, doubling on repeat within the class cap, increments the consecutive-block count.
  - `reset(host)`: success clears `cooldown_until` and the count.
- `scanner/marketdata/factors_postgres.py`: wire `_fetch_nse_feed` (around line 44) and the Upstox, screener and symbol-update fetch points to read the cooldown before fetching and write it on 403, 429 or a block page. Keep each source's own pacing constant unchanged (the 3 s gap at line 28 stays).
- `scanner/collect/sources.py`: where a source ends because a cooldown is active, return `status: "skipped"`, `message: "exchange_cooldown"` (relies on S1a's contract; if S1a has not merged, this slice stops).
- Tests: `tests/test_source_cooldown.py` (new, proposed), real Postgres through `tests/pgschema.py`.
- The symbol-update job name and its fetch point come from S0. If S0 does not name it, the slice stops and returns to the user.

**DDL (proposed; final shape is for the user to approve, section 9 Q5)**
```sql
-- Shared block cooldown, one row per host. Spec: docs/designs/collector-split-spec.md 4.3, 4.3a.
CREATE TABLE source_cooldown (
  host           text PRIMARY KEY,
  backoff_class  text NOT NULL CHECK (backoff_class IN ('api','other')),
  cooldown_until timestamptz,
  block_count    integer NOT NULL DEFAULT 0,
  last_block_at  timestamptz,
  last_reason    text,
  updated_at     timestamptz NOT NULL DEFAULT now()
);
INSERT INTO source_cooldown (host, backoff_class) VALUES
  ('upstox','api'), ('fred','api'),
  ('nse','other'), ('bse','other'), ('screener','other'), ('rbi','other'),
  ('federal_reserve','other'), ('bls','other'), ('mospi','other'),
  ('investing_com','other'), ('cnbc_tv18','other')
ON CONFLICT (host) DO NOTHING;
```
Down file: `DROP TABLE IF EXISTS source_cooldown;` then `DELETE FROM schema_migrations WHERE filename = '049_source_cooldown.sql';`, header "NOT run by the runner. Take a pg_dump first."

**Backoff classes (decided 2026-11-10, requests file)**
- `api` class (`upstox`, `fred`): first block 3 minutes, doubles to 6 minutes, caps at 15 minutes.
- `other` class (every other host, including `nse`, `bse`, `rbi`): first block 15 minutes, doubles, caps at 1 hour (15, 30, 60).
- Per-key independence (4.3a): a block on one host never sets another host's row. An NSE block pauses all NSE callers because they all key `nse`; BSE, Upstox and the rest are independent.
- A host with no row gets `ensure_source_row(host, 'other')` before its first fetch.

**Acceptance command**
- Fast loop: `.venv/Scripts/python.exe -m unittest tests.test_source_cooldown -q` (must run against Postgres, not skipped).
- Gate: full unittest run; `.venv/Scripts/python.exe -m scanner.pg.migrate --status` lists 049.
- Tests: a block on each of the four original hosts sets only its own row; `upstox` backoff sequence is 3, 6, 12, 15 then stays 15; `nse` sequence is 15, 30, 60 then stays 60; a fresh process reads an active row and the source ends `skipped` / `exchange_cooldown`; success clears the row; a symbol-update 403 blocks `nse` and so pauses the `announcements`, `corporate_actions` and `filings` fetches; `ensure_source_row` is idempotent and does not overwrite an existing class; a host with no row is created `other` on first use; real-Postgres test of the write path.

**Must not change**
- Each source's own request pacing and retry constants (`REQUEST_INTERVAL_SECONDS`, `RETRY_BACKOFF_SECONDS`, the 3 s gap).
- `scanner/factors.py` including `matches_orderbook` and `_save_announcements`.
- The same-day coverage logic (`record_coverage`, `missing_windows`): the freshness defect belongs to the freshness spec, not here.
- `collector_runs`, `collector_requests`, `collector_settings` schemas.
- Migration numbers 047, 048 and any number claimed in section 1.
- `scanner/pg/db.py` and `scanner/pg/migrate.py` unless merged `main` first (see section 0).

**Tool-call limit.** 40.

---

## 6. Slice S5a: `GET /internal/due` in Fastify

**Purpose.** The server computes which sources are due. The watchdog polls this endpoint and holds no cron or database logic. It also acts as the heartbeat for S5b.

**Dependencies.** S1a (ok-only rule and status contract) and S2 (the `source_cooldown` table; the split spec lists S1a only, corrected in section 2). S1b for `config/collector_services.json`.

**Migration number.** 050: `SELECT` grants to `market_scanner_app` on `collector_settings` and `source_cooldown`. `db/migrations/050_internal_due_grants.sql` (new) and its down file. `collector_runs` and `collector_requests` grants already exist (migrations 042 and 043).

**Files to create or change**
- `server/src/collectorDue.ts` (new, proposed): the due rule, pure and injected with a `QueryFn`, in the style of `server/src/collectorRefresh.ts` (which already reads `collector_runs` with `status = 'ok'` at line 59 and inserts `collector_requests` at line 42).
- `server/src/collectorDue.test.ts` (new): runs every case in the shared vectors file.
- `server/src/collectorDueRoute.ts` (new, proposed): the route, watchdog bearer-token check, 401/503/500 mapping. Token pattern follows `server/src/homeEventsAuth.ts` (merged in T5b).
- `server/src/app.ts`: register the route; extend `AppDeps` with the token-check dependency. No change to unrelated routes.
- `server/package.json` and `server/package-lock.json`: one cron dependency, version pinned (for example `cron-parser`; the choice and the exact version are made in this slice and stated in the PR, evaluated in `Asia/Kolkata`). Adding a dependency is a user-visible install: ask first, per project rules.
- `tests/data/collector_due_vectors.json` (new, proposed path): shared cases. Each case: cron, now, last ok run, last attempt, cooldown, expected due, and `engines` (`["py","ts"]` or `["ts"]`). The ok-only and never-run cases carry both engines; the retry-gap and cooldown cases are `["ts"]` only (the Python `due_sources` is frozen). A Python test in `tests/test_collect_scheduler.py` runs the `py` cases.
- `db/migrations/050_internal_due_grants.sql` and its down file.
- `docs/designs/` is not edited.

**Behaviour to build** (split spec 4.2, 4.5a)
1. Due rule, in TypeScript, timezone `Asia/Kolkata`, weekday-only like the Python rule (holiday calendar stays open, split risk 8).
2. Slot catch-up counts only `ok` runs as the last run. Only the latest missed slot is returned.
3. Never-run rule: a source with no `ok` run is due only if a cron slot fell today. A source with only failed or skipped rows counts as never-run.
4. Retry rule: any status counts as the last attempt; after `failed` or `skipped` (including `already_running` and `exchange_cooldown`) the source is not due again for 15 minutes or until the next slot, whichever is first.
5. Cooldown: a source is omitted when the `source_cooldown` row for its host has `cooldown_until > now`. The host comes from the `host` field of the source's entry in `config/collector_services.json` (`home_filings` is `nse`). Sources whose host row does not exist are not omitted (the fetcher checks its own host row before each request, requests file S5a row).
6. Only sources listed in `config/collector_services.json` are returned.
7. Order: `index_eod`, `candles_eod`, then the rest in a stable order; `order` is the 1-based position.
8. `reason` is one of `slot`, `catchup`, `request`, `queue`, `stale`. `request_id` is the id of the open `collector_requests` row when `reason` is `request`, else `null`. Checked against the repo: `link_request_to_run` and `claim_requests` use uuid ids (`scheduler.py:123`), so `request_id` is a uuid string, not an integer as the split spec example implies.
9. `fundamentals` queue and staleness: a stub that returns nothing until the fundamentals trigger exists. The split spec cites "filings spec 4.7" here; per the requests file the citation moves to the future `fundamentals-trigger-spec.md`. The stub's comment names that file.
10. Responses: 200 with the contract in 4.5a; 401 for a bad or missing watchdog token; 503 when the database is unavailable; 500 otherwise. The `/internal/due` call records the poll time in memory for S5b (no database write).
11. Watchdog token: a host file outside the repo, read at startup by the server through a config setting (name proposed `COLLECTOR_WATCHDOG_TOKEN_FILE`), the same file-based pattern as `HOME_EVENTS_INGEST_TOKEN_FILE`. Token values never appear in code, tests, logs or docs.

**Acceptance command**
- `npm test --prefix server -- collectorDue` and `npx tsc --noEmit --project server`; then `npm test --prefix server`.
- Gate: the full Python unittest run (for the Python half of the vectors and the 050 migration test), and `.venv/Scripts/python.exe -m scanner.pg.migrate --status` lists 050.
- Tests: every vector passes in TypeScript; the `py` vectors also pass in Python; due never returns a source not in the services file; bad or missing token returns 401; database outage returns 503; the fundamentals stub returns no source; a source whose host has an active cooldown is omitted and one with an expired cooldown is returned; the auth test for `/internal/due` (M14); a vector for the retry gap after `already_running`.

**Must not change**
- Python `due_sources` logic beyond S1a's ok-only change (frozen until S9).
- `server/src/homeEvents*.ts` and the events routes; `server/src/index.ts` (T5c owns its wiring; if wiring is needed here it goes in `app.ts` only; note `index.ts` was modified in the working tree and `kiteToken.ts` was untracked when the filings spec was written, so this slice starts only from a clean tree).
- `collectorRefresh.ts` behaviour.
- Migration numbers outside 050.

**Tool-call limit.** 40.

---

## 7. Slice S3: compose services and the `server` container

**Purpose.** One run-once compose service per source from a shared template; Fastify containerised and reachable from collector containers (requests file S3 row); `start.ps1` stops starting a host Node server. Infrastructure only.

**Dependencies.** S1a, S5a (and S1b for the services file).

**Migration number.** None.

**Files to change**
- `docker-compose.yml`: add a YAML anchor template for run-once collector services; `profiles: [collectors]`, `restart: "no"`, same mounts and secrets as the old `collector` service (line 117) minus `./output` (no CSV, split spec section 3). Mongo access (`DOCSTORE_BACKEND` and network) only for `announcements`, `filings` and `fundamentals` services (M10, option A). Services are added for the sources that exist; this slice adds the template and the `server` service, and the per-source service instances that S6 to S8 and T9 move, one per move task. The old `collector` service stays. Fix the header comment at `docker-compose.yml:4`.
- New `server` service: `restart: unless-stopped`, healthcheck `GET /api/health` (`server/src/app.ts:126`), listens on `0.0.0.0` inside the container, published to `127.0.0.1` only on the host, reached at `http://server:<SERVER_PORT>` (`SERVER_PORT` defaults to 8081 in `server/src/index.ts`). Mounts the watchdog token file and the ingest token file read-only. A Dockerfile for the server if none exists (`server/Dockerfile`, new, proposed).
- `server/src/index.ts`: the bind address becomes configurable (proposed env `SERVER_HOST`, default `127.0.0.1` outside a container, `0.0.0.0` set by compose). One line, no other change. If the tree has uncommitted work in this file, the slice stops (filings spec 9, T5c note).
- `start.ps1`: stop starting a host Node server; compose starts `server`.
- `env.template`: add the non-secret `EVENTS_API_BASE_URL` (`http://server:<SERVER_PORT>`) and `SERVER_HOST`.
- Container name collision check: the fixed name `collector-<source>` and `docker rm -f` before start (watchdog side, S4) is only confirmed here with a compose-level test.

**Acceptance command**
- `docker compose --profile collectors config` returns valid YAML (exit 0, output not echoed in logs).
- `docker compose up -d server` then `docker compose ps server` reports healthy.
- A throwaway run-once container (a trivial command, not a real source) joins the project network and reaches `http://ui:8080` and `http://server:<SERVER_PORT>/api/health` (M15). Command: `docker compose --profile collectors run --rm --no-deps <service> python -c "<health probe>"` (the probe prints status codes only, never headers or environment).
- Gate: full unittest run; `npm test --prefix server`.
- The acceptance commands are infrastructure checks, not unittest. State in the report which were run and which were not.

**Must not change**
- The old `collector` service, until S9.
- The database service, `ui` service and their ports and volumes.
- No secret value in compose, logs or docs; the token files are mounted, not copied.
- Server routes and behaviour.

**Tool-call limit.** 25.

---

## 8. Slice S4: Python watchdog

**Purpose.** A host-side Python watchdog that polls `/internal/due`, starts containers, guards overlap, enforces max runtime, and restarts the database, `ui` and `server`. A thin PowerShell launcher starts it at logon.

**Dependencies.** S3 and S5a (S1a for the `failed` / `killed` run finalisation).

**Migration number.** None.

**Files to create or change**
- `scanner/watchdog/__init__.py`, `scanner/watchdog/main.py`, `scanner/watchdog/docker_runner.py`, `scanner/watchdog/api_client.py`, `scanner/watchdog/health.py` (new, proposed layout; the split spec leaves the path "chosen here" and this is the choice).
- `config/collector_runtime.json` (new): max runtime per source in seconds. Values come from S0's measurements; `home_filings` is 330 s (requests file). This slice creates the file with the sources that have a container so far; each move task adds its own entry.
- `scripts/watchdog.ps1` (new, proposed): a thin launcher that starts the Python process with a single-instance guard. Task Scheduler entry at logon with restart on failure: created by a documented command, not registered by this slice without the user's go-ahead (it changes system configuration).
- `start.ps1`: start or check the watchdog (check only until the user registers the task).
- `tests/test_watchdog.py` (new, proposed): stubbed `docker` runner and fake API.
- Killed-run finalisation: when the watchdog kills a container it must mark that source's `running` row `failed` with message `killed`. The watchdog has no database access (decision 2), so this goes through the API: a small endpoint is needed (`POST /internal/due/finish` or similar). This is a new design point. The requests file says "the watchdog finalises a `running` row", which cannot be done without a database path. Proposed resolution in section 9, Q6; until the user decides, this slice implements the stop and logs the kill and leaves the row finalisation out.

**Behaviour to build** (split spec 4.2 to 4.4, C3, C5, M13, M15)
1. Poll `GET /internal/due` every 60 s with the bearer token from a host file outside the repo. Any non-200 or timeout starts nothing and logs it without secrets.
2. First pass after start: one container at a time in server order; later passes in parallel.
3. Before starting a source: `docker ps` check for the fixed name `collector-<source>`; if running, skip; otherwise `docker rm -f collector-<source>` then `docker compose --profile collectors run --rm --no-deps --name collector-<source> <service>` with `--request-id` when `request_id` is present.
4. Max runtime: `docker stop` for a container older than the `collector_runtime.json` value for its source.
5. Health checks every 30 s for `server` (`GET /api/health`) and `ui` (health path chosen here, confirmed against the compose healthcheck from S3). After 3 failures: `docker compose up -d` for the database, then `ui`, then `server`, with backoff 1, 5, 15 minutes, then every 15 minutes. Never stops the database, `server`, `ui` or the watchdog.
6. Postgres down: log `postgres_down`, distinct from `api_unavailable`, and try to bring the database up (M12).
7. Log under `logs/` with rotation; never echoes compose config or environment; the log size is set here.

**Acceptance command**
- Fast loop: `.venv/Scripts/python.exe -m unittest tests.test_watchdog -q`
- Gate: full unittest run.
- Tests: starts only due sources; never starts a running one; first pass sequential in server order, later passes parallel; restart order and backoff sequence; `docker stop` after max runtime; nothing started on a non-200 response or a timeout; no secrets in the log (a canary string in the token file never appears in the log); the compose command line contains `--no-deps` and `--name collector-<source>`.

**Must not change**
- The collector containers' behaviour and the `collect.py` interface.
- No Docker socket mount into any container.
- `scanner/watchdog` opens no database connection (a test asserts the module imports no `psycopg`).
- No system configuration is changed (Task Scheduler registration) without the user's approval.

**Tool-call limit.** 40.

---

## 9. Decisions needed from you

Each question is one the split spec or the requests file leaves to you. I give a default where I have one; none is applied until you say so.

1. **Filings spec status.** The requests file says the filings spec is "described as approved (revision 4, 2026-11-10); the overview calls it a draft". Is it approved? The slices do not depend on it except for the names `events_source`, `EVENTS_API_BASE_URL` and `HOME_EVENTS_INGEST_TOKEN_FILE`.
2. **S0 first.** Every slice here assumes the S0 report exists (run times, pacing, the symbol-update job name, `ath_scan` inputs). Do you want S0 dispatched first, as the split spec requires, or do you accept S1a and S2 starting before it? Default: S0 first (it is report-only).
3. **Field name in `config/collector_services.json`.** The requests file says `exchange` per entry; the filings spec section 2 says `host`; the cooldown is host-keyed, so `host` is the consistent name. Default: `host`.
4. **Table name.** Requests file: rename `exchange_cooldown` to `source_cooldown` ("you decide"). Since the old table was never created, S2 creates `source_cooldown` directly. Confirm the name, and that the split spec text (4.3, 4.2, S2, S5a) gets repointed by you, since I do not edit it.
5. **Cooldown row shape.** S2's DDL columns (`host`, `backoff_class`, `cooldown_until`, `block_count`, `last_block_at`, `last_reason`, `updated_at`) are my proposal. Also: the eleven seed hosts (`nse`, `bse`, `upstox`, `screener`, `rbi`, `federal_reserve`, `fred`, `bls`, `mospi`, `investing_com`, `cnbc_tv18`) are seeded in 049; is seeding right, or should rows appear only through `ensure_source_row`? Default: seed.
6. **Killed-run finalisation without a database path.** The watchdog has no database access, yet must mark a killed run `failed` / `killed`. Options: (a) a small token-gated Fastify endpoint the watchdog calls after `docker stop` (needs the `collector_runs` update grant for the app role, a new migration number); (b) the next run-once for that source finalises any stale `running` row of its own when it takes the advisory lock (the lock proves the earlier process is dead, so no new endpoint or grant); (c) the watchdog connects to the database after all (reverses decision 2). Default: (b), because the advisory lock already proves liveness (C3). This is also a change to S1a's scope if chosen.
7. **Migration numbers.** I proposed 049 (S2), 050 (S5a), 051 (S8), 052 (filings T1), and a later number for S2a. You said "you decide best", so these stand unless you object. Note one consequence: S5a's grant migration 050 depends on S2's 049 being merged first.
8. **S5a depends on S2.** The split spec lists S5a's dependency as S1a only, but `/internal/due` reads `source_cooldown`. Confirm the corrected dependency (S1a and S2).
9. **Holiday calendar.** Python `due_sources` and the TypeScript rule are weekday-only; the holiday list lives only in `ui-v2/src/lib/marketSession.ts`. Holidays cost one wasted container start per tick. Accept weekday-only for now (default), or require a trading-day check in `/internal/due`?
10. **Report CSV and xlsx fate (NB4).** Still listed as open in the split spec 7. Not in these six slices (it belongs to S2a), but S2a cannot be written until you decide whether `scanner/report.py` keeps its human CSV and xlsx exports (the split spec says yes, human-only).
11. **Risk 3 fallback.** If S0 measures container start-up above about 20 s, `announcements` and `filings` might stay long-running, which contradicts decision 1. You said this can wait for the S0 measurement. It gates S3's service set for those two, not these slices' code.
12. **Task Scheduler registration.** S4 builds the launcher and a documented registration command but does not register the logon task (system configuration change). Do you want the slice to register it when it merges, or will you do it?
13. **Cron dependency for Fastify.** S5a adds one pinned cron library to `server/package.json`. The split spec leaves the choice to the slice. Do you approve a dependency add (default `cron-parser`, version pinned in the PR), or prefer a small hand-written evaluator for the few cron shapes in use?
14. **`filings` host.** The split spec marks the fetch host inside `stage_filings` as unverified (S0 checks). `filings` (the existing source) is assumed `nse` in S2 and S8. Confirm after S0.
15. **Stale text in the split spec.** S1a still says "the next migration is 047"; S1b says nothing on numbers; M14 says "latest is 046"; S2 text says the latest file is 048 (correct); 4.3 and the S2 row say `exchange_cooldown` with four exchanges and a 2 h cap (superseded by the host-keyed table and the 15 min to 1 hour class); the four "filings spec 4.7" citations (its 4.2, 4.6 weekly-sweep row, S5a, S7) still point at a stub. These are yours to edit; I did not touch the file.
