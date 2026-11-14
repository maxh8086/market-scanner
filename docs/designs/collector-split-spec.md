# Collector split and watchdog: one container per source

Status: DRAFT for review. Not approved. No task is dispatched from this document.
Date: 2026-11-10. Parent decisions: D9 and D10 in `home-events-filings-spec.md` (sections 4.6 and 4.7, section 9).

## 1. Goal

Replace the single looping collector container with one run-once container per source, started on schedule by a host-side watchdog, so idle sources use no resources. Also: a source that is blocked or slow no longer delays the others, and a missed run is made up when the laptop is next started.

## 2. Decisions already made by the user

1. All seven existing sources are split, plus the new home-events sources and the reconciler.
2. A small host-side watchdog starts and stops containers by schedule, restarts the database, `ui` and `server` (Fastify) when they are down, and never uses the Docker socket from inside a container.
3. Only the API touches the events database. The collector keeps its existing direct access to the main database and to Mongo (not changed by this spec).
4. When the API (Fastify `server`) is down, the watchdog starts no source at all, including the sources that do not use the events database (decided by the user 2026-11-10, option a; see 4.2). The dashboard shows a banner through the market-status banner mechanism (`ui-v2/src/App.tsx:52`, new kind `collector_paused`). An events source that starts while the API is unavailable records `skipped` (`api_unavailable`); that is a race guard only (4.5).
5. A run that was due while the laptop was off runs at the next start.
6. Schedules: `filings` every 15 min (offset). `announcements` stays at 30 min until the freshness spec lands, then 15 min. `index_eod`, `candles_eod`, `corporate_actions` and `ath_scan` unchanged. `fundamentals` driven by filed results with automatic catch-up.

## 3. Current state (verified from the code, 2026-11-10)

- One service `collector` in `docker-compose.yml:117`: image `ath-enrich`, entrypoint `python collect.py serve`, `restart: always`. It mounts `./data`, `./output`, `./logs`, `./config` and the collector token file, and gets the secrets API at `http://ui:8080`.
- `scanner/collect/sources.py:616` registers seven sources. Sources run one after another in the serve loop, with a 60 s sleep.
- `scanner/collect/scheduler.py:15` `due_sources` already does slot-based catch-up: a source is due when a cron slot has passed since its last run.
- `collect.py` already has `run` for one source (`cmd_run`) and `_get_source`.

**Exchange or provider each source calls**

| Source | Calls | Evidence |
|---|---|---|
| `candles_eod` | Upstox | token from `service_client.fetch_secret("upstox_analytics_token")` |
| `index_eod` | Upstox | same token |
| `announcements` | NSE | docstring, `factors.collect_announcements` per symbol |
| `corporate_actions` | NSE | docstring, `factors.collect_corporate_actions` per symbol |
| `filings` | NSE per docstring. Reads the local file `output/ath_scan_*.csv`, uses Mongo (`docstore`) and `enrich.stage_filings` | the fetch host inside `stage_filings` is **not verified** |
| `fundamentals` | screener.in | docstring |
| `ath_scan` | **not read** | needs a check |

**Cross-source file dependency (decided by the user 2026-11-10: database for machine use, no CSV as source or destination).** Today `filings` reads the latest `output/ath_scan_*.csv` written by `ath_scan`. After the split no collector and no other machine reader uses a CSV as input or output, and no collector mounts `./output`. Human-facing exports stay: `scanner/report.py` (writer at `scanner/report.py:83-98`) still writes its CSV and xlsx for people to read. That output is never machine input.
- `ath_scan` writes its candidate list to a main-database table, `ath_scan_candidates` (DDL in S2a), and stops writing `output/ath_scan_*.csv`. It fails on zero rows written to the table (`AthScan` raises when no CSV is written today, `sources.py:434-481`).
- `filings` reads its candidates from that table and skips with `skipped: no ath_scan candidates` when it is empty.
- Machine readers of `output/ath_scan_*.csv` that move to the table (from review 2, NB4; S0 confirms the complete list): `sources.py:376-418` (fundamentals reader), `sources.py:301,342`, `enrich.py:78,1008`, `record_run.py:111`, `portfolio.py:67`, `crosscheck.py:67`, `start.ps1:207,228`, and the tests `tests/test_collect_ath_scan.py` and `tests/test_empty_scan.py`. `conclude.py` is not a reader of this file; it reads `ath_enriched_*.csv`.
- S0 decides how `portfolio.py` and `crosscheck.py` get their data from the table, since they run outside the collector, and separates the human export from machine use.
- Because the writer and all machine readers must change together (a reader on the CSV would see nothing), the change ships as ONE branch and merge (task S2a), not source by source.

**Mongo (decided by the user 2026-11-10, option A).** `filings` stages filing text in Mongo through `stage_filings`, and `has_filing_text` checks it. Mongo is also referenced by `enrich.py`, `conclude.py`, `ath_scan.py`, `graph_sync.py`, `scanner/runs.py`, `scanner/retention.py` and `scanner/fundamentals.py` (31 files in all, not read), so it stays in the repo. The split adds no Mongo dependency unless a task names one (below). Which source uses Mongo beyond `filings` (`ath_scan`, `fundamentals`) is not verified; task S0 checks.

**Decided by the user, 2026-11-10: Mongo is allowed for announcement and results text too.** Mongo stays as the document store for raw text that inference reads (filing, announcement and results text). The summaries and structured results that inference produces are inserted into the SQL database, so the SQL side stays small and queryable. Rules that follow:
- Mongo holds raw text only. Nothing the UI or the home feed shows is read from Mongo; it reads SQL (through the API, per the UI rule).
- Any new collector that stages text in Mongo says so in its task, with the collection name and a retention rule (`scanner/retention.py` is the existing precedent, not read).
- Summaries for events go to the events database only through the API (4.6 of the filings spec), not by a direct write from the inference job. Summaries for other tables follow the existing path for that table.
- Open: which service writes the summary (the collector after staging, or a separate inference job), and the field on `home_events` that holds it. Not decided here; the filings spec does not have the field yet.

## 4. Design

### 4.1 Run-once container
- B2, accepted 2026-11-10: first extract one shared function `execute_source(name, trigger, request_id)` from the inline run-row logic in `cmd_serve` (`collect.py:173-207`: start_run, run the source, finish_run, mark the request). `cmd_run` (`collect.py:55-94`) writes no run row today, so it cannot be reused as is. `serve`, `run` and `run-once` all call `execute_source`, so every path writes a run row and `skipped` is written in one place. `collect.py run-once --source <name>` (new): check API health (events sources only, see 4.5), take the per-source advisory lock (4.2), call `execute_source`, exit. `execute_source` honours `args.dry_run` (`collect.py:186`). Exit code non-zero on failure. A database that is unreachable exits 3 with no row (M12).
- One compose service per source from a shared template (YAML anchor), all with `profiles: [collectors]`, `restart: "no"`, the same mounts and secrets as today, minus `./output` (no CSV, section 3). `docker compose up` does not start them.
- The old `collector` service stays until the last source is moved (section 6).

### 4.2 Scheduler in the watchdog
- **C2, decided 2026-11-10: the API computes what is due.** The watchdog contains no cron code. It polls `GET /internal/due` (contract in 4.5a) and starts `docker compose run --rm <service>` for each source returned that is not already running. The endpoint applies the due rule below (TypeScript, S5a), including catch-up, and returns only sources listed in `config/collector_services.json` (NM4). The watchdog connects to no database.
- **Blocker 4, decided by the user 2026-11-10: "the API" is the Fastify server (`server/src`), for `/internal/due` as well as the events endpoints.** I recommended the Python `ui` service; the user chose Fastify, so the spec follows that. Consequences, checked against the repo:
  - Fastify has no cron library and does not read `collector_settings` today. It needs a cron dependency (for example `cron-parser`, evaluated in `Asia/Kolkata`; choice made in S5a and the version pinned). It already reads `collector_runs` (`server/src/collectorRefresh.ts:59`, `status = 'ok'`) and inserts `collector_requests` (`:42`); migrations 042 and 043 grant both to `market_scanner_app`. The new grants are `SELECT` on `collector_settings` and `SELECT` on `source_cooldown` (S5a; D7 edit: renamed from exchange_cooldown). The second is needed by the cooldown check below.
  - The due rule is implemented in TypeScript (S5a). The Python `due_sources` is frozen after the ok-only fix (S1a) and is retired in S9. Both read one shared JSON file of cases (cron, now, last ok run, last attempt, cooldown, expected due). Each case carries an `engines` field: `["py","ts"]` or `["ts"]`. The ok-only and never-run cases run on both the Python and the TypeScript test. The retry-gap cases (failed, `skipped`, `already_running`) and the cooldown cases are TypeScript only, because the Python `due_sources` is frozen after the ok-only fix (S1a) and cannot apply the retry and cooldown rules. The vectors file is deleted in S9, and its cases move into the server test.
  - Slot catch-up counts only runs with status `ok` as the last run (not `skipped`, `failed` or `running`), so a skipped tick never hides a missed slot. `get_last_runs` in Python gets the same rule in S1a.
  - Deviation from S1a, decided 2026-11-13: the Python serve due check uses `get_last_attempts` (any run except `skipped`) so a failed run waits for the next slot. `get_last_runs` stays ok-only for status reporting. This closes the hot-retry window until S5a; the 15-minute retry rule and exchange cooldown still land in S5a and S2.
  - The Python `ui` service keeps the Master configuration screen and the secrets endpoint; it is not part of scheduling.
  - **Fastify down (B4, decided by the user 2026-11-10, option a):** the watchdog gets what is due only from `/internal/due`, so while Fastify is down the watchdog starts no source at all, including `candles_eod`, `index_eod`, `corporate_actions` and `fundamentals`, which do not use the events database. The dashboard banner (4.5) is the signal. The watchdog first tries to bring the database, `ui` and `server` up (4.4). After recovery, catch-up (C5) makes up the missed slots.
  - **Never-run rule (B3):** a source with no `ok` run is due only if a cron slot fell today (same as `due_sources`); this stops new sources running on first deploy. The shared test vectors include this case. A source with only failed or skipped rows counts as never-run; this is intended.
  - **Retry rule:** the last attempt of any status counts too. After a `failed` or `skipped` run (including `already_running` and `exchange_cooldown`), the source is not due again until 15 minutes have passed (one retry per 15-minute gap) or the next slot starts, whichever comes first. `/internal/due` does not return a source whose exchange has an active `cooldown_until` (table in 4.3). The shared vectors cover these cases.
  - **Failing poll:** if `/internal/due` returns anything other than 200, or times out, the watchdog starts nothing and logs it without secrets.
  - **`fundamentals` (B3):** it is seeded `mode=scheduled` with cron `0 7 * * *` (`db/migrations/001_core.sql` line 95), and its filed-results trigger with a durable queue and catch-up is in filings spec 4.7. `/internal/due` returns `fundamentals` when its queue has pending items or its daily staleness check (`max_age_days`) finds a stale symbol; the watchdog starts it like any other source.
- **C5, decided 2026-11-10: catch-up runs one container at a time.** The watchdog takes the due list from `/internal/due`. The first pass after start runs one container at a time, in the server's order (`index_eod`, `candles_eod`, then the rest, as sorted by the endpoint), starting the next when the previous container exits. Later passes start due sources in parallel, since the categories are independent (4.3a). Only the latest missed slot runs. Manual requests (`collector_requests`) also start the matching container. The poll runs every 60 s (proposed, section 8 M3).
- **C3, decided 2026-11-10: keep both overlap guards.** (1) The watchdog checks `docker ps` for the source's fixed container name and does not start a second one. (2) Inside the container, the run takes a Postgres advisory lock per source, `pg_try_advisory_lock(hashtext('collector:' || source))`, held on the run connection for the whole run. It is released automatically if the process dies, so no expiry is needed. A second container that cannot take it exits as `skipped` (message `already_running`). The watchdog runs `docker rm -f collector-<source>` before starting, to clear a leftover fixed-name container after a hard kill. If a run is still going at its next slot, that slot is skipped and logged.
- Start lead time about 2 minutes only if container start-up is measured to be slow; default is to start at the slot.

### 4.3 Exchange cooldown across containers (C1 and C6, decided 2026-11-10)
Sources are not grouped into shared containers (that would bring back head-of-line blocking). Each source keeps its own in-process pacing (for example the 3 s gap in `factors_postgres.py:28`). Only the block cooldown is shared, held in the main database table `source_cooldown` so every container obeys it (D7 edit: renamed from exchange_cooldown): one row per exchange (`nse`, `bse`, `upstox`, `screener`), read by every caller before fetching and written on a block. Behaviour is in 4.3a. The columns and DDL are in task S2, not here (C6).

### 4.3a Each category is independent (decided by the user, 2026-11-10)
- `announcements`, `corporate_actions` and `filings` each have their own wait time between requests, in their own container. One category's pace, run length or failure never delays another. Separate containers already give this independence, so no thread is needed.
- The symbol update (the job that refreshes the symbol list; which source or script it is was not identified, task S0 names it) runs separately and must not delay or block those three.
- The one thing shared is the exchange cooldown. If any NSE caller gets a 403 or a block, every NSE caller backs off for the cooldown period, because the block is on our IP, not on a category. The same for BSE and Upstox, each on its own. A symbol update that hits a 403 starts the same NSE cooldown.
- So the only shared table is `source_cooldown` (shape in S2; D7 edit: renamed from exchange_cooldown). Per-request pacing is not shared: each source keeps its own gap constant. No `exchange_pacing` table is built.
- Cooldown rule (D7 edit): flat 1 hour per host (D7, decided 2026-11-14): block sets `cooldown_until` = now + 1 h, an active cooldown is never shortened, reset clears it. Triggers are HTTP 403, 429 or a block page; a success resets it. A container reads it before each run and, for long runs, before each request, and ends the run as `skipped` with message `exchange_cooldown` if active.
- **The same-day bug is per helper, not per category.** `announcements` and `corporate_actions` share one helper (`_fetch_nse_feed`, `factors_postgres.py:44`), so both have the defect described in risk 1 (today is recorded as covered after its first fetch). `filings` works differently (it fetches filing text for candidates that have none, not by date coverage), so it does not have this defect and needs its own check in S0. Each category's freshness is tested separately in its own task.

### 4.4 Watchdog resource rules
- Stop: only containers the watchdog started that run past their max runtime (`docker stop`; the value per source is in `config/collector_runtime.json`, measured in S0 and set in S4). Run-once containers exit by themselves, so "stop" mostly means "do not start".
- Never stopped: the database, `server` (Fastify), `ui` (serves secrets), and the watchdog. These are outside the stop path entirely.
- Restart: health check every 30 s for `server` (`GET /api/health`) and for `ui` (its health path set in S4). After 3 failures, `docker compose up -d` for the database, then `ui`, then `server`, in that order, with backoff 1, 5, 15 minutes then every 15 minutes, logged without secrets.
- `restart: always` on any long-running service conflicts with stop-by-schedule, so split services use `restart: "no"`.
- M13, decided by the user 2026-11-10: the watchdog logic (health checks, restart order and backoff, calling `/internal/due`, catch-up order, overlap guard, `docker compose run` and `docker stop` calls) is written in Python, so the normal unittest command covers it. A thin PowerShell launcher only starts the Python process; it is started at logon by Task Scheduler with restart on failure, with a single-instance guard, started or checked by `start.ps1`. The watchdog log goes under `logs/` with rotation and never echoes compose config or environment. Task Scheduler at logon with restart on failure is the decided form; the log size is set in S4. The watchdog reads its bearer token for `/internal/due` from a host file outside the repo, since `ui` (the secrets endpoint) may be down. The Docker socket stays with the host-side watchdog, never the collector containers (decision in section 2).

### 4.5 API down and skipped ticks
- **Events sources:** `home_filings`, the reconciler and the other new home-events sources (they write through the events endpoints of the filings spec 4.6). Only these check Fastify health at start; down means exit with a `skipped` run, message `api_unavailable`, no fetch, no cooldown change. The seven existing sources (`candles_eod`, `index_eod`, `announcements`, `corporate_actions`, `filings`, `fundamentals`, `ath_scan`) keep their direct access to the main database and Mongo (D9) and do not check Fastify themselves; the check is a race guard only, because the watchdog starts nothing while Fastify is down (4.2). `skipped` is already allowed by `collector_runs.status` (`001_core.sql:104`); the run writer needs a path that writes it (S1a).
- **Services (NB2, decided by the user 2026-11-10):**

| Service | What it is | Restart | Health check | Reachable from |
|---|---|---|---|---|
| `server` | Fastify, a new compose service: `/internal/due`, events endpoints, `/api/events`, status | `unless-stopped` | `GET /api/health` (`server/src/app.ts:126`) | `http://server:<SERVER_PORT>` from containers. Listens on 0.0.0.0 inside the container, published to `127.0.0.1` only on the host |
| `ui` | Python: Master configuration screen and secrets endpoint; not used for scheduling | as today; watchdog restarts it (4.4) | none in compose today; watchdog probe, path set in S4 | `http://ui:8080` |
| database | Postgres, main and events databases | as today; watchdog restarts it (4.4) | as today | as today |
| watchdog | Host Python process, started by Task Scheduler at logon | Task Scheduler restarts it on failure | none; `start.ps1` checks it | no database access |
| `collector-<source>` | Run-once containers, one per source | `restart: "no"` | not applicable | as today |

The watchdog authenticates to Fastify with its own bearer token, held in a host file outside the repo (the secrets endpoint is served by `ui`, which may be down), and has no database access. `start.ps1` no longer starts a host Node server; compose starts `server` (S3). Ports and health paths are confirmed in S4.
- Dashboard banner: the status response carries `collector.paused` (4.5a), shown by a new `collector_paused` kind in `sessionBanner`, the market-status banner mechanism at `ui-v2/src/App.tsx:52`. The UI also shows it after 3 consecutive failed status requests, so it renders when `server` is down.

### 4.5a Endpoint contracts (Fastify `server`)
Each caller has its own bearer token. Responses are JSON.

`GET /internal/due` (watchdog token), 200:
```json
{"generated_at": "2026-11-10T08:35:00+05:30", "sources": [{"name": "index_eod", "service": "index_eod", "reason": "slot", "request_id": null, "order": 1}, {"name": "filings", "service": "filings", "reason": "request", "request_id": 42, "order": 3}]}
```
- `sources` is sorted by the server in priority order: `index_eod`, `candles_eod`, then the rest. `order` is the 1-based position. Only sources listed in `config/collector_services.json` appear. Sources in a retry gap or with an active exchange cooldown are omitted (4.2).
- `reason` is one of `slot`, `catchup`, `request`, `queue`, `stale`. `request_id` is the `collector_requests` id when the reason is `request`, otherwise `null` (the id type is confirmed in S5a).
- Other responses: 401 for a bad or missing token; 503 when the database is unavailable; 500 for any other error. The watchdog treats any non-200 response, and any timeout, the same way: it starts nothing and logs it (4.2).

Status (the existing market-status response; its path is confirmed in S5b) adds:
```json
{"collector": {"paused": false, "since": "2026-11-10T08:34:00+05:30"}}
```
- `since` is the time of the last `/internal/due` poll, held in memory by `server`; `null` until the first poll after a `server` restart.
- `paused` is `true` when `since` is `null` or older than 3 minutes (the watchdog polls every 60 s).
- There is no heartbeat endpoint. The `/internal/due` poll is the heartbeat, so no database write and no new grant are needed.

### 4.6 Schedules
| Source | Cron (IST) |
|---|---|
| `candles_eod` | `35 18 * * 1-5` (unchanged) |
| `index_eod` | `45 8,15 * * 1-5` (unchanged, catch-up applies) |
| `announcements` | 30 min as today until the freshness spec lands; then `*/15 8-20 * * 1-5` (section 5, risk 1) |
| `corporate_actions` | `0 */6 * * *` (unchanged) |
| `filings` | `7,22,37,52 8-20 * * 1-5` |
| `fundamentals` | event-driven plus daily staleness check plus weekly sweep (see the filings spec 4.7) |
| `ath_scan` | manual |

Change via a migration in S8 that updates `collector_settings` for `filings` only, with `UPDATE ... WHERE value = <old default>`, so a value changed in the UI is kept. The `announcements` cron change belongs to the freshness spec.

### 4.7 Scope split (C4, decided 2026-11-10)
This spec is infrastructure only: containers, watchdog, scheduling, cooldown. The freshness fix (today and yesterday re-fetched every run for `announcements` and `corporate_actions`, natural-key upsert, and the check of `filings`) is a separate spec, `collector-freshness-spec.md`, not yet written. The two specs are reviewed and built independently. Until the freshness spec is built, `announcements` keeps its current 30 min cron; the 15 min cron in 4.6 is applied by the freshness spec, not here. Risk 1 below is the evidence the freshness spec starts from.

## 5. Risks and open questions
1. **`announcements` at 15 min: recommendation from the code (not a timing measurement).** What the code does (`scanner/marketdata/factors_postgres.py:44-118, 324-382, 385-430`):
   - The NSE call is market-wide: one request per calendar-month window for all symbols (`index=equities`, URL `corporate-announcements`), with a 3 s pause before each request and 10 s before a retry. It is not one request per symbol.
   - The source still loops over every symbol (`sources.py:215`). For each, it reads coverage and counts rows in Postgres (two COUNT queries plus the gap query). When no gap exists it loads from the database and makes no NSE call and no sleep.
   - So the run time is database work times the number of symbols, not 3 s times symbols. The head-of-line concern in the filings review was overstated for steady state. It is real only for a first or back-fill run (many months of gaps, 3 s each).
   - **Likely defect to confirm:** `from_date..today` is recorded in `feed_coverage` after a successful fetch, so a second run the same day finds no gap and fetches nothing. If that is so, a 15 min cadence adds no new announcements until the next day, and today's behaviour with a 30 min cadence is the same. Verify in S0 by reading `record_coverage` and `missing_windows` for how today is treated.
   - **Recommendation:** (a) do not rely on the gap logic for intraday freshness. Replace the per-symbol loop with one market-wide fetch of the last 2 days each run, upserted by a natural key, then coverage is only for back-fill. That makes a run a single NSE request plus one upsert, seconds not minutes, and 15 min is then comfortable. (b) For the news-style, deduplicated intraday feed, the new `home_filings` source (filings spec) already fetches exchange feeds every 5 min, so `announcements` at 15 min is a back-fill and analytics feed, not the live one. (c) Until S0 confirms the coverage behaviour, schedule `announcements` at 15 min only after change (a); otherwise keep 30 min.
   - Still unmeasured: real run time. S0 records it from `collector_runs` (started_at to finished_at) for the last 30 runs of each source, which needs database access through the postgres MCP, not read here.
2. The fetch host in `stage_filings`, `ath_scan`'s inputs and outputs, and which sources besides `filings` import `docstore` are unverified. Task S0 covers all three. The CSV and Mongo decisions in section 3 are made; S0 only lists the consumers and confirms the other sources' Mongo use.
3. Docker start-up cost per run (several seconds to start a Python image, import pandas, connect) for a source that runs every 15 min. Acceptable if under about 20 s; otherwise keep `announcements` and `filings` as long-running with a loop (decide after S0).
4. The watchdog is a new always-on host process. If it dies nothing is scheduled. Mitigation: Task Scheduler restarts it on failure (4.4), and `start.ps1` checks it. A stale poll shows the `collector_paused` banner after 3 minutes (4.5a).
5. Laptop off for days: only the latest missed slot runs. Whether each source back-fills its own gap is unverified.
6. Secrets: each run-once service needs the collector token file mounted. No secret values are put into compose, the watchdog log or the docs.
7. The migration runs on the main database, so `rows_rejected` and the new `skipped` status must not break the UI's existing run listing (check consumers).
8. The Python `due_sources` and the TypeScript due rule in `/internal/due` must use the same timezone (`Asia/Kolkata`) and the same weekday rule. The holiday calendar question stays open: Python is weekday-only, and the holiday list is only in `ui-v2/src/lib/marketSession.ts`. Holidays cause a run that finds nothing, which is harmless.

## 6. Build order (each step its own branch and merge, old loop keeps unmoved sources running)

| Task | Depends on | Content | Acceptance |
|---|---|---|---|
| S0 | none | Measure `announcements` and `corporate_actions` run times (last 30 runs per source from `collector_runs`) and start-up time; read `filings.stage_filings` and `ath_scan` for hosts, files and Mongo use; list every consumer of `output/ath_scan_*.csv` with the columns each reads (input to S2a); name the symbol-update job; record existing pacing; decide how `portfolio.py` and `crosscheck.py` get their data from the table; separate the human export from machine use. Report only. | Note file `docs/progress/collector-split-s0.md` containing: run times, start-up time, existing pacing, hosts, CSV and Mongo consumers, symbol-update job name, `ath_scan` inputs and outputs, portfolio and crosscheck data needs. |
| S1a | S0 | Extract `execute_source` from `cmd_serve` (B2), and make `serve`, `run` and `run-once` all call it so every path writes a run row (`run` writes none today). `collect.py run-once --source` (new). `execute_source` honours `args.dry_run` (`collect.py:186`). A write path for `skipped` (no migration: `001_core.sql:104`). API health check for events sources only. `get_last_runs` uses the ok-only rule. Per-source advisory lock (4.2). `trigger` allows only `schedule` and `manual`; the next migration is 047. | Tests: unknown source rejected; run-once exits after one run and writes a run row; `dry_run` honoured; a run that cannot take the lock writes `skipped` with `already_running`; events-source skip on API down, using a fake events source (none is registered yet); ok-only last-run rule; the UI run listing still works with `skipped` (`settings.py:173,183`). |
| S1b | S1a | `collect.py init` (M5: `settings.ensure_sources()`, `first_run.tick`, `split_registered`), run by `start.ps1` after migrations and before the watchdog starts. `config/collector_services.json`: the list of sources that have a container; `serve` skips them, and `/internal/due` returns only them (NM4). `claim_requests` claims one request per source, filtered by source or `DISTINCT ON (source)` (`scanner/collect/scheduler.py:72-93`; unique partial index `collector_requests_one_open`). `link_request_to_run` is added and called (`scheduler.py:123`; not called today). | Tests: `collect.py init` creates the settings rows; `serve` skips a listed source; claim returns one request per source. |
| S2a | S0 | `ath_scan_candidates` table in the main database, with its DDL written in the task: migration (number taken when written), columns (scan date, symbol, the fields the CSV carries today as found in S0), unique key (scan date, symbol), run id (type matched to `collector_runs` ids), retention, rollback. Staleness rule: which scan date readers use when the table is empty or old. `ath_scan` writes it and no longer writes the CSV; every machine reader found in S0 reads it (list in section 3); `./output` mount removed for collectors. Hard stop: if S0 finds a consumer outside Python, the task stops and goes back to the user. Fixtures converted from the CSV samples. One branch. | Tests: scan writes rows; zero rows fails the run; each reader returns on a fixture the same candidates it returned from the CSV; no machine reader of `ath_scan_*.csv` remains (the human export from `scanner/report.py` is allowed); full unittest run passes. |
| S2 | S0 | `source_cooldown`, flat 1 hour (D7 edit: D7 decided 2026-11-14; was `exchange_cooldown`; C1, decided 2026-11-10; the larger `exchange_pacing` table and slot claiming are dropped), one row per exchange (`nse`, `bse`, `upstox`, `screener`), migration 049 (047 is `company_reference`, 048 is `index_constituents`; the latest file in `db/migrations/` is 048). Read and written by every caller of those four exchanges (4.3a). | Tests: a block on each exchange sets only its own cooldown; a fresh process reads it and ends `skipped` with `exchange_cooldown`; success resets it; a symbol-update 403 blocks the three NSE categories; a real Postgres test for the cooldown write. |
| S5a | S1a | `GET /internal/due` (contract in 4.5a) with the TypeScript due rule: slot catch-up on ok runs, never-run rule, retry rule and exchange cooldown check (4.2), sort order, filter by `config/collector_services.json`. Cron dependency chosen and pinned. `SELECT` grants on `collector_settings` and `source_cooldown` (D7 edit: renamed from exchange_cooldown). Shared test vectors (JSON) including the failed, `already_running` and `exchange_cooldown` cases; each case carries `engines` (4.2), and the TypeScript test runs every case. `fundamentals` queue and staleness stub (returns nothing until S7). Watchdog token check. | Server test: every shared vector case passes; due never returns an unlisted source; a bad token gets 401; a database outage gets 503; the `fundamentals` stub returns no source; the auth test for `/internal/due` (M14). |
| S5b | S5a | Status response field `collector: {paused, since}` (4.5a) and the `collector_paused` banner (4.5). No heartbeat, no database write, no grant. | Server test and `ui-v2` test: `paused` is true with no poll for 3 minutes; the banner shows on `paused` and after 3 failed status requests. |
| S3 | S1a, S5a | Compose template and services: one run-once service per source from a shared template (YAML anchor), `profiles: [collectors]`, `restart: "no"`, same mounts and secrets as today minus `./output`. New `server` service (Fastify): `restart: unless-stopped`, healthcheck `GET /api/health`, listens on 0.0.0.0 in the container, published to `127.0.0.1` on the host, reached at `http://server:<SERVER_PORT>`. `start.ps1` stops starting a host Node server. Confirm the fixed-name collision check (`docker rm -f`, 4.2). Compose header comment corrected (`docker-compose.yml:4`). Status 2026-11-14: the `server` service is built (compose, docker/server/Dockerfile, SERVER_HOST override, start.ps1). Its ingest token is mounted as the single file /run/app-keys/home_events_ingest_token (secrets-and-roles decisions 2, 10, 15); SERVICE_TOKEN_DIR=/run/app-keys. Its database login is the dedicated role `market_scanner_server` (decided 2026-11-14; migration 057 holds the grants, the user creates the role and sets its password out of band); the password is the single file /run/app-keys/server_db_password, read via POSTGRES_PASSWORD_FILE. The run-once template services and the compose header comment fix are not part of this slice. S3b (token fetch): implemented in PR (branch feat/s3b-server-token-fetch), not merged. | `docker compose --profile collectors config` valid; `server` reports healthy; a run-once container joins the project network and reaches `ui:8080` and `http://server:<SERVER_PORT>` (M15). |
| S4 | S3, S5a | Python watchdog (`scanner/watchdog/` or the path chosen here) plus a thin PowerShell launcher and a Task Scheduler entry at logon with restart on failure. Health checks and restart order (4.4), backoff, `/internal/due` poll every 60 s, first pass one at a time and later passes parallel (C5), overlap guard (`docker ps` check and `docker rm -f` before start), max-runtime `docker stop` from `config/collector_runtime.json`, bearer token from a host file. Log under `logs/` with rotation; never echoes compose config or environment. | Unittest with a stubbed `docker` runner and a fake API: starts only due sources; never starts a running one; first pass one at a time in server order, later passes parallel; restart order and backoff; `docker stop` after max runtime; nothing started on a non-200 response or a timeout; no secrets in the log. |
| S6 | S2a (full: it moves the `ath_scan` writer), S2, S3, S4, S5a | Move `candles_eod`, `index_eod` (Upstox) and `ath_scan` (idle-heavy, local). Each adds its source to `config/collector_services.json`. `ath_scan` is the writer of `ath_scan_candidates`, so S6 depends on S2a in full, not only for the `./output` mount removal. | `candles_eod` and `index_eod` each run once on schedule in their container and not in the old loop; `ath_scan` (manual) runs when requested through `collector_requests`. |
| S7 | S2a, S6, external filings-spec fundamentals queue (filings spec 4.7) | Move `fundamentals` once its queue exists (filings spec 4.7; replaces the S5a stub), then `corporate_actions`. Each adds its source to `config/collector_services.json`. | `fundamentals` runs in its container for the queue or staleness reason; `corporate_actions` runs on schedule; neither runs in the old loop. |
| S8 | S2a, S7, freshness spec (for `announcements`) | Move `announcements` and `filings`. The `filings` cron (`7,22,37,52 8-20 * * 1-5`) is set by the migration here (4.6). `announcements` keeps 30 min until the freshness spec changes its cron. Each adds its source to `config/collector_services.json`. | Each runs on schedule in its container and not in the old loop; measured runtime fits the slot. |
| S9 | S6, S7, S8 | Retire the old `collector` service and the `serve` loop; remove the Python `due_sources` and the vectors file (its cases move into the server test); correct the compose header comment (`docker-compose.yml:4`). | Full unittest run passes; `serve` and Python `due_sources` are gone from the repo; the compose header comment is correct. |

Each task gets exact paths, one acceptance command (`.venv/Scripts/python.exe -m unittest discover -s tests -t . -q` where it applies), and what must not change, when written. `tests/test_collect_sources.py:171-175` (exact SOURCES set) is updated in S1.

## 7. Next steps
1. User confirms the Proposed rows in section 8 (M1, M3, M4, M5, M6, M8, M9, M10, M12, M14, M15) or moves any of them to the open list.
2. User answers the remaining open items: the holiday calendar and the report CSV and xlsx fate (NB4). Resolved and removed from this list: the `source_cooldown` grant (4.2, S5a; D7 edit: renamed from exchange_cooldown), the `engines` split of the vectors (4.2), the S1b and S5a test split, and the `ath_scan` writer dependency for S6 (NM11).
3. Write `docs/designs/collector-freshness-spec.md` (covers `announcements` cron and the M7 freshness rules).
4. Re-run the six-lens EGM review on the revised spec before any dispatch.
5. Then S0 first, since its measurements settle risks 1 to 3.

## 8. Response to review majors and minors (2026-11-10)
Source: `docs/progress/collector-split-spec-review.md`. "Decided" means a user decision already recorded above; "Proposed" means a default written here that the user has not confirmed; "Open" needs the user.

| Item | Status | Resolution |
|---|---|---|
| M1 run lock | Decided (C3) + Proposed | The lock is a Postgres advisory lock per source (`pg_try_advisory_lock(hashtext('collector:' || source))`, 4.2). Containers get a fixed name (`--name collector-<source>`); the watchdog runs `docker rm -f` on a leftover before start, and the `docker ps` check stays. There is no stale-running rule: the advisory lock releases when the process dies. Max runtime per source is in `config/collector_runtime.json` (values measured in S0, set in S4); the watchdog runs `docker stop` past that limit. |
| M2 pacing | Decided (C1, 4.3a) | Small `source_cooldown` table (D7 edit: flat 1 hour, renamed from exchange_cooldown); per-request gaps stay in each source and reuse `REQUEST_INTERVAL_SECONDS` and `RETRY_BACKOFF_SECONDS`. S0 reads existing pacing first. If the database is unreachable the container exits per M12. |
| M3 catch-up | Decided (C5) + Proposed | The first pass after the watchdog starts runs one container at a time in server order (the user's choice replaces the review's cap of 2). Later passes run in parallel. The watchdog takes the due list from `/internal/due` and does no cron evaluation of its own. Proposed: poll interval 60 s. S0 acceptance item: each source back-fills its own gap, since only the latest slot runs. |
| M4 manual requests | Proposed | `GET /internal/due` returns `pending_request` and `request_id` per source (4.5a). The watchdog passes `--request-id` to run-once. `link_request_to_run` is added and called (`scheduler.py:123`; it is defined but not called today). S1b fixes `claim_requests` (`scheduler.py:72-93`) so it claims one request per source. No new grant: Fastify already has the grants on `collector_requests` from migrations 042 and 043. |
| M5 duties of `serve` | Proposed | `settings.ensure_sources()`, `first_run.tick` and `split_registered` move to a new `collect.py init` step that `start.ps1` runs after migrations and before the watchdog starts. Added to S1. |
| M6 cutover | Proposed | `config/collector_services.json` lists the sources that have a container. The old `serve` loop skips them, and `/internal/due` returns only them. Each move task (S6 to S8) adds its source to the file, so the old loop and the new container never both run a source. Replaces the `COLLECTOR_LOOP_SKIP` env var. |
| M7 freshness | Decided (C4) | Separate `collector-freshness-spec.md`. `announcements` stays at 30 min until it lands; `filings` at 15 min is unaffected. |
| M8 banner and liveness | Proposed (heartbeat cut) | No heartbeat endpoint and no heartbeat table. The status response carries `collector: {paused, since}` (4.5a), and the `collector_paused` banner shows when `paused` is true or after 3 consecutive failed status requests (4.5). Added to S5b. |
| M9 cron migration | Proposed | S8 sets the `filings` cron (`7,22,37,52 8-20 * * 1-5`) with an idempotent `UPDATE ... WHERE value = <old>`. `announcements` moves to the freshness spec, not this spec. Schedules, services and tasks for the new home-events sources and the reconciler belong to the filings spec plan. `fundamentals` stays in the old loop until its queue exists (S7). |
| M10 Mongo in services | Proposed | Only `announcements`, `filings` and `fundamentals` services get `DOCSTORE_BACKEND` and Mongo network access (option A); the others get none. S0 confirms the other sources do not import `docstore` at load. |
| M11 build order | Proposed + Open | S5 is built before S4 (S4 needs `/internal/due`). S0 gates S2, S3 and S6. Open: the risk 3 fallback (keep a long-running `announcements` or `filings` container if start-up cost is too high) contradicts decision 1, so it needs the user's decision once S0 measures the start-up time. The user said (2026-11-10) the risk 3 question can wait for the S0 start-up measurement. |
| M12 Postgres down | Proposed | If Postgres is unreachable the container exits with code 3 and writes no row; the watchdog logs `postgres_down`, distinct from `api_unavailable`, and tries to bring the database up (4.4). The banner covers the visible case. |
| M13 watchdog implementation | Decided (user) | Python watchdog logic with a thin PowerShell launcher (see 4.4); tests run under the normal unittest command with a stubbed `docker` and a fake API. |
| M14 `skipped` plumbing | Proposed | No migration needed: `collector_runs.status` already allows `skipped` (`001_core.sql:104`). The UI consumers (`settings.py:173,183` and the run listing) are covered by the S1a test. The next migration is 047 (the latest is 046). S5a adds an auth test for `/internal/due`. |
| M15 compose run | Proposed | The watchdog starts containers with `docker compose --profile collectors run --rm --no-deps --name collector-<source> <service>`. S3 acceptance: a run-once container joins the project network and reaches `ui:8080`. The watchdog log never echoes compose config or environment. |

Minors:
- Section 3 gets a separate "Unverified" subsection for rows not read; the `ath_scan` row records what is known (`sources.py:434-481` writes the scan output through `ath_scan.main()`); hosts and Mongo use remain unknown. (S0)
- Mongo option A is already decided; section 7 needs no Mongo question.
- Glossary to add at the top in the next edit: EGM (the review method), ATH (all-time high), `home_filings`, `sessionBanner`, `collector_requests`, `feed_coverage`, the `ui` service, and the seven sources listed once.
- 4.4: the database, the API and the watchdog are outside the stop path entirely.
- 4.6, confirmed by the user 2026-11-10: `index_eod` has two slots a day and after a long gap only the latest missed slot runs; `filings` runs until 20:52. Still to check in S6: `ath_scan` "manual" matches its database row mode.
- Start lead time of 2 minutes: removed unless S0 measures slow start-up.
- Holiday runs cost one container start per tick; optional trading-day skip via `/internal/due` (later).
- `tests/test_collect_sources.py:171-175` (exact SOURCES set) is updated in the task that registers new sources, not in S1.
- S2 acceptance includes a real Postgres test for the cooldown write.
- S3 and S9: the compose header comment (`docker-compose.yml:4`, "ui and collector are the two long-running services") is corrected.
- Dropping `./output` also drops report output of `ath_scan`; S0 confirms what reads it (see S2a).
- 4.3 SQL shape stays in S2 (C6, done).
- S3 and S4 acceptance: S4 tests use a stubbed `docker` and a fake API; the `filings` evidence row is split into three rows in the next edit.
- Never-run first deploy: stated in 4.2 (B3); a manual request starts a never-run source.
