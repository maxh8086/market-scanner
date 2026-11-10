# Review: collector-split-spec.md (EGM default, six lenses)

Target: `docs/designs/collector-split-spec.md` (draft 2026-11-10). Reviewed by six fresh Goldfish agents (design, codebase-details, zoom-out, comprehension, implementation-readiness, structural), deduplicated. Section 2 decisions were not re-litigated. Spot-checks of section 3 against compose, scheduler.py, collect.py and sources.py mostly held; the exceptions are listed below. Counts: 5 blockers, 15 majors, 14 minors.

## 1. Verdict

NOT READY. Five blockers: a `skipped` row defeats catch-up, the run-once path reuses code that does not write run rows, the watchdog cannot evaluate cron as described, "the API" is undefined and its gate contradicts decision 4, and the no-CSV decision breaks `ath_scan`, `filings` and `fundamentals` with no table task. No task should be dispatched until these are resolved.

## 2. Blockers

B1. `skipped` (and `failed`, and stale `running`) rows suppress catch-up. Location: 4.5, 4.2, decisions 4 and 5. `get_last_runs` (scheduler.py ~141) takes MAX(started_at) over any status and `due_sources` treats a slot as done once it is not newer than that. An `api_unavailable` skip therefore consumes the slot and it is never made up. Fix: last-run for scheduling counts only successful runs (`/internal/schedule` returns last success and last attempt separately); add the test "skip, API up, same slot runs"; decide a retry rule so a skip or failure does not retrigger every watchdog poll (retry at next slot or after a minimum delay). Also correct 4.5 wording: `due_sources` does not read status, the real change is `get_last_runs`.

B2. Run-once reuses code that does not exist. Location: 4.1, 4.5. `cmd_run` (collect.py:55-94) writes no run row and ignores trigger and `collector_requests` linkage; `start_run`/run/`finish_run` live inline in `cmd_serve` (collect.py:173-207). Fix: S1 first extracts a shared `execute_source(name, trigger, request_id)` used by `serve`, `run` and `run-once`; state it in 4.1 and the S1 acceptance.

B3. The watchdog cannot share `due_sources`. Location: 4.2. The watchdog is PowerShell on a host with no stated Python; `due_sources` needs croniter, pytz and `scanner`. Fix: pick one. Recommended: `GET /internal/schedule` returns the computed `due` list (server runs `due_sources`), so the watchdog has no cron logic and risk 8 disappears. Alternative: require the host venv and call it. Also state the never-run rule (a never-run source is due only if a slot fell today, so new sources do not run on first deploy on a weekend) and the trigger for event-driven `fundamentals` (not `mode=scheduled`, so `due_sources` skips it).

B4. "The API" is undefined and the API-down gate contradicts decision 4. Location: 2.4, 4.2, 4.4, 4.5. The repo has the `ui` service (:8080, secrets) and the Node `server/`; the spec does not say which hosts `/internal/schedule`, which is health-checked, which is restarted, or how the host watchdog authenticates. 4.5 makes every run-once container skip when the API is down, but decision 4 says only events sources stop; `candles_eod`, `index_eod`, `corporate_actions` do not use the events DB. Also the watchdog's only schedule source is the API, so everything stops when it is down. Fix: add a table (service, URL, health endpoint, auth); define "events sources" and gate only those; either let the watchdog use a cached schedule, or state plainly that all sources pause (which departs from decision 4 and needs the user).

B5. The no-CSV decision breaks three sources and is unplanned. Location: 3, S6, S8. Section 3 is wrong that only `filings` reads the CSV: `fundamentals` (sources.py ~376-418) also skips with "no ath_scan_*.csv", and `AthScan` (sources.py:468-472) raises if no CSV is written. `ath_scan.main()` is not DB-native. S6 moves `ath_scan` before S8 moves `filings`, while the old loop's `filings` still reads a CSV that no longer exists, and no task creates the candidates table. Fix: add an explicit task (table DDL, migration, `ath_scan` writer, `filings` and `fundamentals` readers, staleness rule) before S6; keep the CSV written and `./output` mounted until S9; resolve the `enrich`/`conclude` question in S0 before S6 is written.

## 3. Majors

M1. Run lock and overlap guard undefined (4.1, 4.2). "Per-source run lock" has no mechanism; a container killed by sleep or Docker restart leaves a `running` row (current guard has a 3600 s timeout). The watchdog has no DB, so how it sees "in progress" is unspecified; `docker compose run` containers have unique names. Fix: one guard only, either `--name collector-<source>` checked via `docker ps`, or an advisory lock plus heartbeat with stale-row reaping at watchdog start; add a max runtime with `docker stop` (4.4 "stop" is otherwise empty).

M2. `exchange_pacing` (4.3, S2) is under-specified and arguably unneeded. Gap values per exchange, breaker threshold, cooldown, reset of `consecutive_failures`, half-open probe, max wait, behaviour when the table or DB is unreachable, and reuse of `REQUEST_INTERVAL_SECONDS`/`RETRY_BACKOFF_SECONDS` in `factors_postgres.py` are all missing; waiting containers recreate head-of-line blocking and cause overlap skips. See cut C1. If kept: S0 must read existing pacing first, and a max wait that exits `skipped: pacing_wait`.

M3. Catch-up semantics (4.2, risk 5). No order, concurrency cap or poll interval; at laptop start the API may be down so every catch-up start writes a skip. Fix: define priority order (Upstox and events first), max concurrency 2, watchdog polling interval, and wait for API health before the catch-up pass. Make "each source back-fills its own gap" an S0 acceptance item, since only the latest slot runs.

M4. Manual requests have no path (4.2). Watchdog has no DB, `GET /internal/schedule` has no request data, and `claim_requests` (scheduler.py:72-93) claims one row despite its docstring. Fix: either the run-once container claims its own request filtered by source (watchdog sees a pending flag), or add an API claim endpoint; pass `--request-id` and keep `link_request_to_run`.

M5. Duties of `serve` vanish with the loop. `settings.ensure_sources()` (collect.py:108-114), `first_run.tick` (collect.py:121-126, queues the first ATH scan) and `split_registered` are not assigned. Without `ensure_sources` a fresh install has no `collector_settings` rows. Fix: assign to watchdog start or API startup hook; add to S1 or S4.

M6. No cutover mechanism so the old loop and new container do not both run a source (S6-S8). Fix: add an exclusion list (for example `COLLECTOR_LOOP_SKIP`) to S1, updated by each move task.

M7. Risk 1 recommendation is a feature change inside an infrastructure split, and has no owner. 4.6 makes the 15 min cron conditional on a market-wide 2-day fetch rewrite that is in no S-task, while decision 6 fixes 15 min. The "likely defect" is unconfirmed (`was_fetched_today_pg` exists at factors_postgres.py:146; `record_coverage`/`missing_windows` live in `scanner/coverage.py`, not in factors). Fix: separate spec or explicit prerequisite task before S8; until then 30 min or 15 min with a note it adds no new data.

M8. Banner and watchdog liveness undefined (4.5, risk 4, 4.4). No response field, source of truth, staleness threshold, or false-positive rule ("status request fails" should need N consecutive failures); the banner cannot show when the API itself is down unless the UI does so itself. Fix: watchdog writes a heartbeat via API, API exposes `collector: {paused, since}`; add to S5.

M9. Migration of cron defaults (4.6) names no old values, number or idempotence rule, so it is untestable. Decision 1 also names the new home-events sources and reconciler, which have no schedule, service or task. Fix: list old default strings, use `UPDATE ... WHERE value = old`; add tasks or a "later spec" note; say what `fundamentals` runs on in S7 if the queue is not ready.

M10. Mongo and docstore in the service template (3, 4.1). State which services get `DOCSTORE_BACKEND` and Mongo network access (option A) and which set none; confirm other sources do not import `docstore` at load.

M11. Build order and gating. S5 (`/internal/schedule`) is needed by S4 but follows it; S0 should gate S2, S3 and S6, not just report; risk 3 fallback (long-running `announcements`/`filings`) contradicts decision 1 and must be a user decision with the 20 s start-up measured in S0.

M12. Skipped write needs a DB that may be down (4.5). The watchdog restarts the DB too. Fix: define behaviour when Postgres is down (exit 3, no row, watchdog logs "postgres_down" distinct from `api_unavailable`), or let the API or watchdog record skips (also avoids a container start per tick).

M13. Watchdog implementation choices left open (4.4, S4). Task Scheduler vs hidden process, single-instance guard in `start.ps1`, project path and env file for `docker compose up -d`, log path and rotation, and the test framework (Pester?) for "stubbed docker" tests; the repo's acceptance command is Python unittest. Fix: decide in the spec (recommended Task Scheduler at logon with restart on failure plus heartbeat), or write watchdog logic in Python with a thin PowerShell launcher.

M14. `skipped` status plumbing (4.5, risk 7, S1, S2). Check for a CHECK constraint or enum on `collector_runs.status`, list UI consumers (`settings.py:173,183`, run listing) in S1's file list, give the real migration number (not "04x"), and add the `/internal/schedule` auth test to S5.

M15. `docker compose run` specifics (4.2, 4.1). Add `--no-deps` and `--profile collectors`; confirm run-once containers join the project network and reach `ui:8080` (S3 acceptance); watchdog log must not echo compose config or env (risk 6).

## 4. Minors

- Section 3 heading says "verified" but contains unverified rows; use a separate "Unverified" subsection. The `ath_scan` row says "not read" though sources.py:434-481 is readable (writes `output/ath_scan_<date>.csv` via `ath_scan.main()`); remaining unknowns are hosts and Mongo.
- Section 7 asks the user for risk items 1-4 only; add the Mongo A/B question.
- Undefined terms for a naive reader: EGM, ATH, `home_filings`, "B2", "filings spec 4.7", `sessionBanner`, `collector_requests`, `feed_coverage`, the `ui` service. Add a glossary or links. List the seven sources once.
- 4.4: "never stopped" (database, API) vs "stop only containers the watchdog started": state they are outside the stop path.
- 4.6: `index_eod` has two slots a day and only the latest missed runs (confirm intended); `filings` last slot 20:52 vs `announcements` 20:45 (confirm end time); `ath_scan` "manual" must match the DB row mode.
- 4.2 "start lead time about 2 minutes" has no owner; tie to S0 or remove.
- Holiday runs cost a container start every 15 min (risk 8, risk 3); optional trading-day skip or holiday list via `/internal/schedule`.
- S1 says `tests/test_collect_sources.py:171-175` is updated, but run-once does not change SOURCES; move it to the task that registers new sources.
- S2 acceptance should require a real Postgres test for slot atomicity.
- S3/S9: the compose header comment (docker-compose.yml:4, "ui and collector are the two long-running services") becomes wrong.
- 4.1: dropping `./output` also drops report output for `ath_scan`; confirm in S0.
- 4.3: SQL shape and column list are implementation detail for a design doc; move to S2 if it survives.
- S3 and S4 acceptance for the watchdog are weak (see M13); the `filings` evidence-table row mixes three claims in one cell.
- Never-run first-deploy of new sources needs a manual trigger or rule (see B3).

## 5. Cuts or simplifications proposed (decisions for the user, not applied)

C1. Drop `exchange_pacing` and S2. Keep in-process pacing and let the watchdog serialize starts per exchange (it is the only starter, including manual requests). Reinstate the table only if S0 shows overlapping same-exchange runs the watchdog cannot prevent.
C2. Make the API compute `due` (B3 option b), so the watchdog is a thin loop with no cron code.
C3. Use one overlap guard: the watchdog checks `docker ps` for a fixed container name; drop the in-container lock.
C4. Split the `announcements` market-wide fetch rewrite into its own spec; keep this spec to infrastructure.
C5. Treat the catch-up pass as "wait for API, then at most 2 at a time in priority order", dropping bespoke pacing logic.
C6. Move SQL shape and column lists out of section 4.3 into the task.

## 6. What is blocked on what

- S1 blocked by B1, B2, M5, M6, M12, M14.
- S2 (if kept) blocked by M2 and S0 reading existing pacing.
- S3 blocked by M10, M15 and the S0 start-up measurement.
- S4 blocked by B3, B4, M1, M3, M13 and by S5 (swap order).
- S5 blocked by B4, M4, M8.
- S6 blocked by B5 (table task) and S0 CSV findings.
- S7 blocked by the filings-spec queue and M9.
- S8 blocked by M7 and B5.
- S9 blocked by all moved sources and the compose comment fix.

## 7. Path to READY

1. User decides: API gate scope (B4), Mongo A or B, risk 3 fallback policy (M11), C1 to C4.
2. Revise the spec: fix section 3 (fundamentals CSV, ath_scan facts, verified vs unverified), define the API table, `/internal/schedule` contract (due list, last success vs attempt, running, pending request, heartbeat), skipped semantics and the lock or guard.
3. Add tasks: execute_source extraction, ath_scan candidates table, cutover exclusion list, announcements fetch change, tasks for new sources and reconciler; reorder S5 before S4.
4. Run S0 as a hard gate (run times, start-up cost, existing pacing, CSV and Mongo consumers, status constraint, migration number).
5. Re-run the review on the revised spec.
