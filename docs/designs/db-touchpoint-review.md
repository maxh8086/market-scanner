# DB touchpoint design review: critic findings

Status: NOT APPROVED. No task has been dispatched. Source: endpoint-design critic run (69 findings: 65 confirmed, 4 refuted by verification pass).

## Decisions the user must make

D1. Which service is "the API". Option A: the ui FastAPI service (the current proposal). Option B: the Fastify server in server/src. docs/designs/collector-split-spec.md:62-66 records a 2026-11-10 decision that Fastify is the API and that ui is not part of scheduling. Choosing B moves the collector, runs and market routes to server/src.

D2. The user rule is "no container or feature accesses the database directly; all access goes through the API." Under that rule, ui's own direct reads (ui/app/api.py:15, :30) and its import of scanner/collect/settings.py write functions are not exempt. Decide: route them through the API, or write a named exception with a reason.

D3. The /api write routes PUT /api/config/{source} and POST /api/config/{source}/run have no auth and no CSRF check. Decide: remove them, require a session or CSRF token, or accept the risk in writing.

D4. Collector request claim semantics: per-source claim (one open request per source, per docs/designs/collector-split-slices.md:106) and a lease token with expiry so a lost response or a skipped request is recovered. Decide the lease length and whether skipped requests are re-queued or recorded.

D5. Scope of R6 (removing DB logins from containers): remove the DB logins from the collector and graph services' env_file access, not only the POSTGRES_DSN line. Confirm the approach for graph and collector env blocks.

## Coverage gaps

1. Severity: high
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scripts/pull_upstox_5y.py
- Issue: Unmapped. Default mode writes the upstox_pull_log ledger to Postgres, and load_universe SELECTs via company_reference (lines 176, 185 per inventory). Not in any route group. E4 names only load_upstox_5y_to_pg.py.
- Fix: Add pull_upstox_5y.py to E4 by name, or route the ledger write and the universe read through a group.

2. Severity: high
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/ath_scan.py
- Issue: Reads at lines 265 (history), 354 and 355 (factors fetch_corporate_actions and fetch_announcements) reach Postgres through the marketdata default. No design mapping. Lines 354-355 have no GET route in Corporate events.
- Fix: Map 265 to Market reads and add GET routes for announcements and corporate actions, with ath_scan as a caller.

3. Severity: high
- File: design: Corporate events (POST /internal/factors/*:batch)
- Issue: Write-only group. factors.py facade reads (341-1070) and factors_postgres fetch paths have no GET route, so read-side scanner jobs have no route.
- Fix: Add GET routes for announcements and corporate actions, or state that these reads stay direct and why.

4. Severity: high
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/coverage.py
- Issue: Design lists coverage.py under Market reads, but the group has only GET candles and GET index-candles/last-date. Inventory says coverage.py:120-124 reads feed_coverage. No feed_coverage read route exists.
- Fix: Add GET /internal/market/feed-coverage or move that read into the group.

5. Severity: high
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/marketdata/postgres_backend.py
- Issue: force_refresh deletes and commits candles (lines 136-139) before the network fetch. Market writes has no DELETE or replace operation.
- Fix: Add a candles delete or replace operation to Market writes, and decide whether delete and refetch become one transaction.

6. Severity: high
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/docker-compose.yml
- Issue: COMPOSE step is wrong for graph-sync. POSTGRES_DSN at line 141 sits in the service with entrypoint collect.py serve (line 134) and env_file (line 135), which is the collector. graph-sync (entrypoint graph_sync.py line 103, env_file .env line 104) has no DSN line and gets POSTGRES_* from .env.
- Fix: R6 must edit graph-sync's env_file contents (its POSTGRES_* values), not remove a line 141 DSN.

7. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/docker-compose.yml
- Issue: Inventory labels line 56 as the collector service block. Line 56 is the enrich: service. The collector service key was not identified (inventory open question 8).
- Fix: Correct the label and identify the collector service name before R6 edits docker-compose.yml.

8. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/docker-compose.yml
- Issue: COMPOSE step omits Postgres access in other services. The scanner service (line 32) mounts the loader password file at lines 40 and 48. conclude (line 122) gets POSTGRES_* from env_file to record LLM calls. enrich (lines 59, 73) gets database logins for candles and filings.
- Fix: Add these to R4 (loader mounts) and R5 (conclude) compose steps, and to the enrich env cleanup.

9. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/expiry_alerts.py
- Issue: Contradiction. Dead-code section says expiry_alerts.py has no non-test caller (grep confirms only tests/test_expiry_alerts.py imports it). Secrets row still maps its reads at lines 91, 92, 99, 125 and lists it as a caller. Inventory count is also inconsistent: 2 touchpoints under Other, but 4 read lines in section 4.
- Fix: Remove the expiry_alerts from the Secrets mapping and delete it with its test, or keep it and drop the dead-code claim.

10. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/collect/sources.py
- Issue: Unmapped. The filings source (line 295, coverage and docstore) has no route. docstore.py was not read (inventory open question 2), and ath_scan.py:454 is unverified.
- Fix: Read docstore.py and assign line 295 and ath_scan.py:454 to a group or an exception.

11. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/intensity.py
- Issue: Unmapped. Listed as a host pipeline library with Postgres touchpoints, and symbol_sector.py is in the line-drift list. Neither has a design mapping.
- Fix: Map both to a route group or mark them as touching no Postgres after reading.

12. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/history.py
- Issue: Facade reads at lines 152, 259 and 335 (candles) are not in the design. Inventory says history.py is missing from the inventory entirely.
- Fix: Add history.py to the Market reads row and list its scanner-job callers.

13. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/enrich.py
- Issue: Unmapped. Lines 112, 175, 619, 747 and 754 touch Postgres per inventory and have no design mapping.
- Fix: Assign each line to a group or to a scanner-job route.

14. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/start.ps1
- Issue: Unmapped. Lines 250-270 run psql through docker exec to create the events database owned by the app login (lines 269-270); it only checks that the app login exists (lines 264-266) and does not set up roles. That is an admin path, but E1 covers only migrate.py, pgschema.py and db/migrations.
- Fix: Add start.ps1 events-database creation (CREATE DATABASE ... OWNER <app login>) to E1 as operator-only, with the admin role from the host.

15. Severity: low
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/db/events_migrations
- Issue: E1 names db/migrations only. db/events_migrations/*.sql is matched by inventory but omitted from E1.
- Fix: Add db/events_migrations to E1.

16. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/server/src/config.ts
- Issue: Matched by the sweep but not inspected. The Fastify server may be a Postgres client, and the design is silent on it.
- Fix: Inspect server/src/config.ts and any Fastify Postgres use, then map or exempt it.

17. Severity: low
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/constituent_membership.py
- Issue: build_membership_from_db has no production caller. Its index_constituents read is test-only but is absent from the dead-code list and the route mapping.
- Fix: Add build_membership_from_db to the dead-code list.

18. Severity: medium
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/tests/test_runs.py
- Issue: Live test writes runs, and snapshot_changes at lines 192 and 217. It is not in E3, and R7 covers only the E3 set.
- Fix: Add test_runs.py, test_migration_054.py and test_pg_migrate_events.py:98 to E3 and R7.

19. Severity: medium
- File: design: Collector control and Runs groups
- Issue: Mislabel. Design maps collect.py:110 to Runs and snapshots, but inventory says collect.py:110 writes collector_sources and collector_settings. It belongs under Collector control (PUT sources).
- Fix: Move collect.py:110 to Collector control.

20. Severity: low
- File: design: Market writes
- Issue: Label conflict. Design says postgres_backend.py:95 is a candles write, but inventory section 4 says it is a symbol_stats write.
- Fix: Confirm line 95 and fix the label. Both candles:batch and symbol-stats exist, so coverage is unaffected.

21. Severity: medium
- File: design: Corporate events callers
- Issue: Caller mismatch. Callers list only collector, but ath_scan and the factors facade reads come from scanner jobs.
- Fix: Add scanner jobs to the callers, and add the GET routes from the earlier finding.

22. Severity: medium
- File: design: Reference data callers
- Issue: Caller mismatch. Callers list collector and the refresh job, but constituents.py (host pipeline) and scripts/pull_upstox_5y.py (company_reference SELECTs) also call this group.
- Fix: Add the host scanner jobs and pull_upstox_5y.py to the callers, or move the pull script under E4.

23. Severity: medium
- File: design: Collector control callers
- Issue: Caller mismatch. Callers list only collector, but api.py:491 and :507 (the ui service) import scanner/collect/settings.py and would call this group. The open point leaves it unresolved.
- Fix: Add the ui service as a caller with its own token, or move the writes into the collector control group now.

24. Severity: medium
- File: design: token model (one service token per caller)
- Issue: Ambiguity. scanner jobs spans ath_scan, enrich, conclude, final_report, record_run and host-side runs, but the design treats it as one caller. Host-side callers also need a token file location.
- Fix: Define one token per job or one shared scanner-jobs token, and state where host-side tokens live.

25. Severity: low
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/ui/app/queries.py
- Issue: Dead-code list names 7 of 21 constants. Grep shows the other 14 are used by api.py (lines 82-438). COLLECTOR_RUNS_HISTORY (api.py:411, 468) is a collector read, and the UI exception names only runs, results and stock data.
- Fix: Add collector run history to the UI exception list.

26. Severity: low
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/app_secrets.py
- Issue: Design does not say where decryption runs once scanner jobs call GET /internal/secrets. app_secrets.py is described as the only process that decrypts.
- Fix: State that decryption stays in the ui service and app_secrets becomes a route client.

27. Severity: low
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/pg/db.py
- Issue: Shared factory with no route or exception entry. After R6 its remaining direct users (ui api and internal_secrets, migrate, backfill, import_sqlite) are not listed.
- Fix: List the remaining direct users of db.py explicitly in R0 decisions.

28. Severity: low
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/fundamentals.py
- Issue: Unread files: fundamentals.py (enrich:140), screener.py and secrets_store.py have no mapping and no Postgres check. secrets_store is likely file-backed (api.py:525), which is unverified.
- Fix: Read these files and record Postgres yes or no before R0 is approved.

29. Severity: low
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/tests/test_ui_api.py
- Issue: Inventory corrections are unapplied (section 4). The design relies on line numbers that still carry known errors: sources.py:642 is an import, not a connect; company_reference_job.py:186 is make_conninfo; api.py:525 is file-backed; coverage.py:120-124 targets feed_coverage.
- Fix: Apply the section 4 corrections before R0, so the route plan rests on verified lines.

## Wrong citations and labels

1. Severity: high
- File: docker-compose.yml
- Issue: COMPOSE claim cites the collector block at line 56 and its DSN at 141. Line 56 is the `enrich` service. The collector is service `collector` (line 131), entrypoint at 134, POSTGRES_DSN at 141. It already sets SECRETS_API_URL (142) and SERVICE_TOKEN_FILE=/run/app-keys/collector_token (143), so 'gain a service token file' is already declared.
- Fix: Cite collector at docker-compose.yml:131-143. Restate the token step as 'confirm the token file is provisioned for collector' rather than 'add it'. Do not read the token file itself.

2. Severity: high
- File: docker-compose.yml
- Issue: COMPOSE claim says graph-sync loses POSTGRES_DSN 'at docker-compose.yml:141'. Line 141 is inside the collector service. The graph service (named `graph`, lines 100-107, entrypoint graph_sync.py at 103) has no explicit POSTGRES_DSN. It gets POSTGRES_* from the x-scanner-db-env anchor (25-28) and env_file .env (104-105).
- Fix: Remove the graph claim from line 141. State that graph's DSN comes from the anchor and .env, and that its service name is `graph`, not graph-sync.

3. Severity: medium
- File: scanner/collect/settings.py
- Issue: Collector control row cites settings.py lines 11, 26, 42, 98, 141, 170 as reads and writes. Line 11 is `import psycopg`, not a DB op. The real ops are: get_settings SELECT (26-28), ensure_sources writes (42-53, INSERTs at 48 and 52, not listed), update_setting UPDATE (98-115), request_run INSERT into collector_requests (141-143, not routed), list_runs SELECT (170-183).
- Fix: Replace line 11 with the ensure_sources writes (48, 52). Add the request_run INSERT (141-143) and list_runs read (170-183) to the mapping, and give request_run a route.

4. Severity: medium
- File: scanner/collect/first_run.py
- Issue: Row cites first_run.py 62 and 69 as reads. Both are def lines (`_run_in_progress` at 62, `_queue_run` at 69). The actual ops are the connect at 65, which calls scheduler.is_running (SELECT collector_runs, scheduler.py:151-165), and line 71, which calls settings.request_run (INSERT collector_requests, settings.py:142). The inventory's 'reads missed at 62 and 69' is wrong.
- Fix: Cite first_run.py:65 and :71 instead. Note that is_running (collector_runs read) and request creation both need routes or an explicit exclusion.

5. Severity: medium
- File: scanner/collect/scheduler.py
- Issue: Claim route is described as one request per source (docstring 73-75, comment 80). The SQL at 81-90 uses ORDER BY source, requested_at with LIMIT 1 over the whole table, so it claims one row total. collect.py:146 consumes the list, so the route semantics differ from the docstring.
- Fix: Specify POST /internal/collector/requests/claim as a single-row claim, or change the SQL deliberately. Fix the docstring either way.

6. Severity: high
- File: collect.py
- Issue: Row cites collect.py:200 as a 'collector_requests update'. Line 200 is scheduler.finish_run, which updates collector_runs (scheduler.py:112-113). The only collector_requests UPDATE for a link is scheduler.link_request_to_run (scheduler.py:123-127), which has no caller anywhere in the repo. collector_runs start and finish writes (scheduler.py:96-121, called at collect.py:182 and :200) have no route.
- Fix: Correct the cite to collect.py:200 -> collector_runs. Add collector_runs writes to a route group, or mark them out of scope. Add scheduler.link_request_to_run to the dead-code list, since it is unused and not listed.

7. Severity: medium
- File: collect.py
- Issue: Listed under 'Runs and snapshots' as replacing collect.py:110. Line 110 is settings.ensure_sources(), which writes collector_sources and collector_settings (settings.py:42-53). It belongs to collector control, not runs.
- Fix: Move the row to Collector control and cite settings.py:42-53.

8. Severity: high
- File: record_run.py
- Issue: Row cites record_run.py:50 as a stock_snapshots write. Line 50 is `runs.compute_changes(run_id)`. The stock_snapshots writes are runs.py:140 (record_snapshots, called from record_run.py:44) and runs.py:254 (compute_changes). The design's snapshot-changes route covers only the change rows, so the stock_snapshots write has no route.
- Fix: Cite record_run.py:44 for record_snapshots and runs.py:140 and :254 for the table writes. Add a route for stock snapshots, or list it as out of scope.

9. Severity: medium
- File: scanner/marketdata/postgres_backend.py
- Issue: Market writes row cites 'candles write (95)'. Line 95 is a candles read, _load_cached_candles_pg, inside _update_symbol_stats_pg. The candles write is _save_candles_pg (67-91, executemany at 80, INSERT at 82). get_history's force_refresh DELETEs candles and symbol_stats at 136-137, and no route covers those deletes.
- Fix: Cite 67-91 for the candles write and 102-121 for symbol_stats. Add the force_refresh deletes (136-137) to the market writes or exclude them explicitly.

10. Severity: low
- File: graph_sync.py
- Issue: Graph row cites graph_sync.py 85 and 86. Line 86 is the pg.connect(), and the SELECT FROM v_announcement_summary is at 88-89. Line 85 is not a DB op. The compose service is `graph` (docker-compose.yml:100), not graph-sync.
- Fix: Cite graph_sync.py:86 (connect) and :88-89 (SELECT). Use the service name `graph`.

11. Severity: medium
- File: scanner/metrics.py
- Issue: LLM metrics row lists only POST /internal/llm/calls, which replaces record_call (77). metrics.py also has _ensure_run_exists (51-62, read), flush_pending (154-197, writes), finalize (200-250, writes via cursor and commit, called at 211 and 426), and summarize (321-, reads, called at 428). None has a route.
- Fix: Add routes for finalize and summarize, or state that the metrics CLI stays direct. Add flush_pending to the same decision.

12. Severity: medium
- File: scanner/expiry_alerts.py
- Issue: Secrets row cites expiry_alerts 91, 92, 99 and 125 as replaced by the secrets route. Those lines are correct (get_value at 91-92, get_meta at 99 and 125). But the dead-code section proposes deleting expiry_alerts.py, which has no non-test caller. The two sections contradict each other. Its token_alert_sent writes (_record, line 63) are not listed.
- Fix: Resolve the contradiction: remove expiry_alerts from the secrets row if it is deleted, or keep it and remove it from the dead-code list.

13. Severity: low
- File: scanner/constituents.py
- Issue: Reference data row cites constituents.py 46 and 48. Line 46 is `from scanner.pg import db`, an import. The DB op is 48-49.
- Fix: Cite constituents.py:48-49 only.

14. Severity: medium
- File: scanner/isin_resolver.py
- Issue: Reference data row cites isin_resolver.py:49 (correct, load_master_from_db read). Missing writes: record() at 109 writes isin_history (_UPSERT_HISTORY, line 100) and symbol_alias (_UPSERT_ALIAS, line 104). No route covers them. Also resolve() at line 60 calls load_master() with no connection, and load_master raises at line 48, so the latent defect remains.
- Fix: Add the isin_history and symbol_alias writes to a route group. Fix or document the no-connection fallback at line 60 before routing reference reads through HTTP.

15. Severity: medium
- File: scanner/marketdata/factors_postgres.py
- Issue: Corporate events row covers the write batches only. factors_postgres has fetch_metadata reads and writes (was_fetched_today_pg 156-160 and mark_fetched_pg 172-177, reached from factors.py:341 and :374), cached reads (_load_cached_announcements_pg 264, _load_cached_corporate_actions_pg 311), and symbol_listing reads (collect_announcements 414, collect_corporate_actions 469). None has a route. sources.py:217 and :261 call the factors.py facade (factors.py:1051 and :1070), not factors_postgres directly.
- Fix: Add routes for fetch_metadata and symbol_listing reads and for the cached reads. Note in the table that sources.py goes through the factors.py facade.

16. Severity: medium
- File: scanner/history.py
- Issue: Replaces and callers columns omit history.py. Its delegations to postgres_backend are cached_closes (153), get_history (260) and collect_eod (336). postgres_backend.cached_closes (22-29) is a connect-based read that the table does not mention.
- Fix: Add history.py to the callers of the market routes and list cached_closes in market reads.

17. Severity: low
- File: scanner/coverage.py
- Issue: Market reads row lists 'coverage.py reads', but no GET route for feed_coverage is defined. The only feed-coverage route is POST. missing_windows (41-59) reads feed_coverage and is called from postgres_backend.collect_eod at line 198. announcement_coverage (151-170) reads its own query.
- Fix: Add GET /internal/market/feed-coverage, or state that the collector reads feed coverage through a different route.

18. Severity: high
- File: ui/app/api.py
- Issue: Collector control callers column lists only 'collector'. The current writers and readers of collector settings and requests are the ui process: api.py:491 (update_setting), api.py:507 (request_run), and reads at api.py:402 and :456 (get_settings). Lines 491 and 507 are calls; the import is api.py:17.
- Fix: Add 'ui (self)' to the callers for PUT /internal/collector/sources/{source} and for request creation. Correct 'import' to 'call' for lines 491 and 507, and cite api.py:17 for the import.

19. Severity: low
- File: ui/app/queries.py
- Issue: Dead-code claim checked and confirmed: UPDATE_COLLECTOR_SETTING (287), INSERT_COLLECTOR_REQUEST (293), STOCK_SNAPSHOT (82), RESULTS_QUERY (163), RESULTS_COUNT (185), COLLECTOR_SETTINGS (245), COLLECTOR_SETTING_BY_SOURCE (256) have no .py reference. ui\app\EGM.md:26 still describes UPDATE_COLLECTOR_SETTING and INSERT_COLLECTOR_REQUEST as in use, so the doc is stale.
- Fix: Keep the dead-code list. Update ui\app\EGM.md:26 when the constants are deleted.

20. Severity: medium
- File: C:\Users\vaibh\AppData\Local\Temp\claude\a0d1dd8c2c919690\19abc57e-f83d-434b-a387-c20ff3c61ec1\tasks\waj99knn3.output
- Issue: Several design citations were carried over from inventory errors: collect.py:200 (collector_requests), first_run.py 62 and 69 (reads), record_run.py:50 (stock_snapshots), settings.py:11 (read), collector compose block at line 56, graph_sync 85, and postgres_backend 95. The inventory's own section 4 corrections do not apply to these cites.
- Fix: Re-verify each cited line against the source before the design is approved, and update the inventory to match.

## Hazards

1. Severity: high
- File: scanner/collect/scheduler.py:72-93 and collect.py:144-166
- Issue: Claim is committed before any run, with no lease or claim token. link_request_to_run is defined (scheduler.py:123) but never called. A request claimed at collect.py:146 is silently dropped if is_running is true (collect.py:161) or the source is missing (collect.py:166). A claimed row is never re-selected (claimed_at IS NULL). Over HTTP, a claim committed on the server whose response is lost is orphaned the same way.
- Fix: Return a claim token with a lease expiry from the claim route. Require that token on the status route. Reclaim expired leases. Call link before running. Re-queue or record a skip instead of dropping. Make claim retries idempotent with a client request id. Add tests for lost response and for is_running true.
- Evidence: scheduler.py:72-93 claim commits (claimed_at = NOW()) before any run; collect.py:146 claim; :161 is_running drop; :166 missing-source drop; link_request_to_run (scheduler.py:123) uncalled; no lease token.

2. Severity: medium
- File: scanner/collect/scheduler.py:72-93 vs docs/designs/collector-split-slices.md:106 and docs/designs/collector-split-spec.md:195
- Issue: The SQL claims one row for the whole table (LIMIT 1, ORDER BY source, requested_at), though the docstring says one per source. The project's own slice S1b requires one open request per source. The design treats claim_requests as already per-source. A route that copies the current SQL keeps the alphabetical starvation and the one-per-tick throughput limit.
- Fix: Specify the per-source claim (DISTINCT ON source, or a unique partial index collector_requests_one_open) in the design before R2. Add a test that two open sources are both claimed in one call.
- Evidence: scheduler.py:88 LIMIT 1 over whole table; docs/designs/collector-split-slices.md:106 requires one open request per source; collector-split-spec.md:195 (M4) relies on per-source claim.

3. Severity: high
- File: docs/designs/collector-split-spec.md:62-66 vs the proposal (ui /internal/collector/*)
- Issue: The repo records a user decision from 2026-11-10 that the API is the Fastify server (server/src). Fastify owns /internal/due and the scheduling. The spec says the Python ui 'is not part of scheduling'. The proposal puts collector control and the runs routes on the FastAPI ui. Fastify already inserts collector_requests (spec line 63, collectorRefresh.ts:42). Two services would then write the same collector tables.
- Fix: Resolve the host service before R0 approval. If Fastify is the API, move the collector, runs and market routes to server/src and reuse its role-keyed token check (homeEventsAuth.ts) and its 413-before-auth batch limit (homeEventsRoute.ts:28-32). Drop the duplicate routes on ui.
- Evidence: docs/designs/collector-split-spec.md:62-66 says Fastify is the API (decided 2026-11-10) and ui is not part of scheduling (:66). server/src/collectorRefresh.ts:42 inserts collector_requests; ui/app/api.py:491, :507 write the same tables. Proposal text not in repo.

4. Severity: high
- File: ui/app/internal_secrets.py:65-95
- Issue: _authenticate resolves only two identities, collector and llm_client, from two token files. _secret_name_allowed is keyed by service name. No route-group map exists. The proposal needs one token per caller (collector, scanner jobs, graph, reference job, llm-client). The scanner service (docker-compose.yml:32-53) has no token mount today.
- Fix: Replace the two-token check with a role-to-route-group table, fail closed with 403 when a role has no token (as homeEventsAuth.ts does). Add one token file per caller and a test for each deny case: caller A on group B, and a missing token file.
- Evidence: ui/app/internal_secrets.py:65-89 _authenticate resolves only collector and llm_client identities; :92-95 _secret_name_allowed keyed by service name. Caveat: scanner service mounts an LLM chat token file (docker-compose.yml ~:50), so 'no token mount' is literally inaccurate. Core claim holds.

5. Severity: medium
- File: ui/app/main.py:43-44 and ui/app/api.py:487-516; docker-compose.yml:170-171
- Issue: The /api write routes PUT /api/config/{source} and POST /api/config/{source}/run have no auth. The UI is published on 127.0.0.1:8080, and the code says 'the UI has no login'. main.py has no CSRF check. POST /run takes no body, so a cross-site form POST may queue a run (not verified against browser private-network rules). Routing api.py:491 and :507 through /internal does not close this unless the /api write routes are removed or gated.
- Fix: State in the design that the /api write routes are removed or require a session or CSRF token. Do not rely on the loopback bind.
- Evidence: ui/app/main.py:43 include_router(api.router, prefix='/api'); ui/app/api.py:487 PUT /config/{source} and :503 POST run have no auth dependency; docker-compose.yml:170 127.0.0.1 loopback with comment 'the UI has no login'; no CSRF check (main.py:35-41 only sets cache header).

6. Severity: high
- File: ui/app/api.py:17 and scanner/collect/settings.py:98-156
- Issue: The UI still imports scanner/collect/settings.py, which holds update_setting and request_run. The UI also keeps the DSN (api.py:15, 30). Moving only api.py:491 and :507 leaves write code and DB credentials in the UI process. The design's own open point (UI PROCESS section) stays unresolved.
- Fix: Remove the write functions from the import used by the UI, or split a read-only module for the UI. Decide the UI's DB role explicitly (read-only or none) and record it in R1.
- Evidence: ui/app/api.py:17 imports scanner/collect/settings (update_setting, request_run at settings.py:98-116, :141-148); api.py:15 and :30 use db.connect for DB access.

7. Severity: high
- File: docker-compose.yml:135-143 and :100-109; docker-compose.yml:14-16 comment; scanner/pg/db.py:65-78
- Issue: R6 removes only the POSTGRES_DSN line. The collector and graph services still get .env through env_file (docker-compose.yml:135-136, 104-105). The file holds the project's database logins, and db.dsn() falls back to POSTGRES_HOST, USER and PASSWORD. The password therefore stays in the container. Graph-sync sets no POSTGRES_DSN at compose level (only line 141 does), so R6 is a no-op for graph-sync.
- Fix: Give collector and graph-sync an env block without DB logins, with no env_file .env (or a filtered one). Verify with docker compose config and a container env check. Describe R6 as removing logins, not only the DSN.
- Evidence: docker-compose.yml:14-16 says secrets reach containers via env_file .env, which holds DB logins; collector env_file :135-136; graph env_file :104-105; scanner/pg/db.py:70-74 falls back to POSTGRES_USER/PASSWORD.

8. Severity: high
- File: scanner/marketdata/postgres_backend.py:134-140
- Issue: force_refresh deletes candles and symbol_stats and commits (lines 136-138) before the network fetch (line 139). A failed fetch leaves the symbol with no cached candles and no stats. Moving this to HTTP as delete-then-fetch keeps the defect.
- Fix: Fetch first into memory, then delete and insert in one server-side transaction. If a route must be split, make the refetch the server's job.
- Evidence: scanner/marketdata/postgres_backend.py:136-138 DELETE candles and symbol_stats and commit before network fetch at :139.

9. Severity: medium
- File: scanner/marketdata/postgres_backend.py:142-150 and :196-230; scanner/pg/db.py:88-98
- Issue: The connection uses psycopg's default non-autocommit mode. The first SELECT (line 142) opens a transaction, and the network fetches at lines 144, 149 and 207 then run while that transaction is open. collect_eod holds one connection across all gap fetches. Under HTTP each fetch becomes a separate call, so the design must say which statements share a transaction.
- Fix: Keep the network fetch outside any open transaction. Document the transaction scope of each route in the design.
- Evidence: postgres_backend.py:142 SELECT in get_history with network fetches at :144 and :149; collect_eod connect :196, missing_windows :198, fetch :207. db.py:88-98 uses psycopg default non-autocommit.

10. Severity: medium
- File: scanner/marketdata/postgres_backend.py:90,122 and :232; the proposed symbol-stats route
- Issue: The candle batch commits (line 90). The symbol_stats upsert commits separately (line 122). _update_symbol_stats_pg (line 95) reads all candles for the symbol to compute the ATH. The design lists candles:batch and symbol-stats as separate POSTs with no defined inputs. A failure between them leaves candles updated and stats stale. The design does not say whether the server or the client computes the stats.
- Fix: Define symbol-stats as a server-side recompute after the batch in the same transaction, or pass the computed values in the same request. Define runs with snapshot-changes as one unit (runs.py uses db.transaction, db.py:101).
- Evidence: postgres_backend.py:90 commit after candle save; :122 commit after symbol_stats upsert; :95 reads candles for ATH. db.transaction at scanner/pg/db.py:101-105 exists for runs.

11. Severity: medium
- File: scanner/pg/db.py:88-98; scanner/marketdata/postgres_backend.py:67-90; scanner/marketdata/factors_postgres.py:217 and :253
- Issue: db.connect sets no connect_timeout and no statement_timeout (only scripts set connect_timeout=5, e.g. scripts/pull_upstox_5y.py:122). _save_candles_pg and the factor saves send whole lists with no chunking. cached_closes chunks at 500 (postgres_backend.py:31-33), which is the local convention. Fastify has MAX_BATCH_ROWS=500 (server/src/homeEventsBatch.ts:12). Candle upserts are idempotent (ON CONFLICT, postgres_backend.py:84), which helps retries.
- Fix: Set a row cap and a body-size limit on every batch route, with 413 before auth. Set per-route timeouts on the HTTP client and on the server connection. Keep the ON CONFLICT upserts.
- Evidence: scanner/pg/db.py:88-98 connect sets no connect_timeout or statement_timeout; scripts/pull_upstox_5y.py:122 uses connect_timeout=5; postgres_backend.py:31-33 chunks at 500; server/src/homeEventsBatch.ts:12 MAX_BATCH_ROWS=500; upsert ON CONFLICT at postgres_backend.py:84.

12. Severity: medium
- File: scanner/collect/sources.py:642-647 and scanner/company_reference_job.py:168-180; docker-compose.yml:135-150
- Issue: The monthly reference refresh runs inside the collector process and calls loader_dsn(), which needs POSTGRES_LOADER_PASSWORD_FILE and a readable file. The loader file is mounted only on the scanner service (docker-compose.yml:40, 48). The collector has no such mount. The E2 assumption that the loader role runs from the collector container may already fail at runtime.
- Fix: Confirm whether the in-process refresh path at sources.py:618-643 is reachable and whether it works today. Decide E2 on that evidence before R4.
- Evidence: scanner/collect/sources.py:642-647 psycopg.connect(loader_dsn()); scanner/company_reference_job.py:168-180 loader_dsn reads POSTGRES_LOADER_PASSWORD_FILE; docker-compose.yml:40, :48 loader mount on scanner only; collector block :131-150 has no loader mount.

13. Severity: medium
- File: scanner/collect/sources.py:127,207,251,295,370,550,565,642 (lazy imports) and sources.py:12-13 (top-level imports)
- Issue: The collector's in-process modules (history, factors, constituents, coverage, index_candles, fundamentals, docstore) keep their own db.connect() calls, many of them missed by the inventory. A route-only change leaves them connecting. The UI is clear of this: settings.py imports sources.py, and sources.py imports only service_client and mongo at module level (sources.py:12-13), so the UI loads no Postgres marketdata modules at import.
- Fix: Add each marketdata and factors module to the route migration list, with its connect calls, and make the design say which callers still hold a connection after each rollout step.
- Evidence: scanner/collect/sources.py:12-13 top-level imports are service_client and mongo (pytz and requests also, non-DB); lazy DB-touching imports at :127, :207, :251, :295, :370; :565 is a lazy non-DB import (upstox broker client); scanner/collect/settings.py:16 imports sources.SOURCES.

14. Severity: medium
- File: ath_scan.py:265,354-355; scanner/pg/db.py; inventory section 2 (host pipeline libraries)
- Issue: Host-run pipeline scripts (ath_scan.py, enrich.py, start.ps1) reach Postgres directly through the marketdata defaults, with .env on the host. The design's exceptions E1 to E4 do not cover them, and the callers in the route table say only 'scanner jobs'. Host jobs would need tokens too, and they run outside compose.
- Fix: Add the host pipeline to the exceptions or to the callers, with a token distribution plan for host runs.
- Evidence: Host-side DB access exists: ath_scan.py:265, :354-355; enrich.py:112, :175; start.ps1:250-270 psql via docker exec. E1-E4 coverage text is not in repo.

15. Severity: low
- File: collect.py:176 and scanner/collect/settings.py:98
- Issue: collect.py:176 calls scheduler.get_settings(db.connect()) once per source per loop without closing the connection. Several connections are opened per 60-second tick. With HTTP these become calls, but the leak should not be carried over.
- Fix: Close or context-manage the connection, or fetch settings once per tick through the collector control route.
- Evidence: collect.py:176 scheduler.get_settings(db.connect()) opens a connection per source per tick and never closes it.

16. Severity: low
- File: scanner/service_client.py:16 and docker-compose.yml:152-174
- Issue: Bearer tokens travel in plain HTTP (http://ui:8080) on the default and llm compose networks. The ui service is attached to both networks (docker-compose.yml:172-174). Low risk on a bridge network, but it is an unstated trust boundary for the new per-caller tokens.
- Fix: Record the transport choice and its risk in the design, or move to TLS on the internal network.
- Evidence: scanner/service_client.py:16 DEFAULT_BASE_URL http://ui:8080 (plain HTTP); docker-compose.yml:172-174 ui attached to default and llm networks.

## Refuted by verification

1. Status: not confirmed; kept for the record
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/scanner/pg/import_sqlite.py
- Issue: Contradiction. Market writes lists import_sqlite as a replaced writer, while E4 says import_sqlite.py stays direct, host-side only.
- Verifier note: Contradiction is between design/E4 text, which is not in the repo. Code fact only: scanner/pg/import_sqlite.py:79, :174 write candles and announcements. Contradiction not confirmable.

2. Status: not confirmed; kept for the record
- File: C:/Users/vaibh/Downloads/Projects/Market-Scanner/tests/test_company_reference.py
- Issue: DB-touching tests without a classification: test_company_reference.py 223 and 263, test_factors_backend.py:188, test_secrets_cli.py:46, test_secrets_cli_s6.py:138 (missing from inventory), test_fund_writer.py:234 and test_fund_daily_writer.py:137.
- Verifier note: Listed tests use fake connections, not a live DB: test_company_reference.py:223 (_ExecConn), :263 (_FakeConn); test_factors_backend.py:188 (fake pg via mock); test_secrets_cli.py header 'Offline' with FakeConn; test_secrets_cli_s6.py:138 Conn() fake; test_fund_writer.py:234 and test_fund_daily_writer.py:137 _FakeConn with 'no DB' headers.

3. Status: not confirmed; kept for the record
- File: design: LLM metrics callers
- Issue: Possible caller mismatch. Inventory lists scanner/metrics.py among libraries the collector loop reaches, but callers list only scanner jobs.
- Verifier note: The collector path does not call metrics.record_call (summary-level check: collect.py and sources.py path has no record_call); the suspected caller mismatch does not exist.

4. Status: not confirmed; kept for the record
- File: scanner/pg/import_sqlite.py
- Issue: Market writes row lists import_sqlite as replaced by the market writes routes. E4 keeps import_sqlite.py direct and host-side. The table and E4 contradict each other. E4 also keeps backfill.py direct, which the table does not mention.
- Verifier note: Contradiction concerns design text (Market writes row, E4 decision) not in repo. Code facts confirmed: import_sqlite.py:79, :174 write; backfill.py:35 uses db.connect. Contradiction not confirmable.

## Counts

- Total critic findings: 69
- Confirmed: 65
- Refuted by verification: 4

Confirmed by lens:
- coverage: 29
- accuracy: 20
- hazards: 16

Confirmed by severity:
- high: 17
- medium: 34
- low: 14

Confirmed by lens and severity:
- coverage: high 6, medium 15, low 8
- accuracy: high 5, medium 11, low 4
- hazards: high 6, medium 8, low 2
