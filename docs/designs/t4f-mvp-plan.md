# T4f home events MVP plan (PROPOSED, audit-revised 2026-11-13, not approved)

Status: PROPOSED, audit-revised 2026-11-13, not approved. Nothing in this file is dispatched until the user approves it. Scope basis: present plan, no C1 (LLM stage) and no C2 (Telegram) change.

## 0. Decisions recorded 2026-11-13

The user's replies below override section 1 and later text where they conflict.

- D1 (MVP scope): the MVP includes the read route GET /api/events and the Home feed slice. The "no Home display" wording in section 1 is superseded. Sizing: NEW-HOME-FEED in section 4 (a planning estimate, to be confirmed).
- D2 (feed): keep nse:Sast_Regulation31 (High-Priority, filings spec line 228). Corporate_action is the catalyst tier (line 229). The sample match rates are 10 of 20 for Sast_Regulation31 and 35 of 58 for Corporate_action (filings spec line 375). Status: explained to the user; awaiting their confirmation. With D6 the feed choice no longer selects the only feed; Sast_Regulation31 stays the O1 named-test feed. Audit note: the all-feed full-NSE-list result (111 matched, 0 ambiguous, 31 unmatched of 142) is at filings spec line 375. Only the per-feed Sast_Regulation31 count on the full nse_csv list is missing (docs/designs/t4f-d8-sast31-values.md line 68). The Corporate_action fallback is moot under D6.
- D3 (split-spec track): approved to start now. S0 is closed (report docs/progress/collector-split-s0.md, 2026-11-12). S1a is dispatched first. S1b, S2, S3, S5a and F-T1 follow in that order, one code writer at a time.
- D4 (S4): keep S4 in the MVP.
- D5 (migration numbers): accept the 049 to 052 gap. Nothing is held: migration 048 is applied (checked in the market_scanner database on 2026-11-13). The runner applies unrecorded files in filename order and does not require contiguous numbers (scanner/pg/migrate.py lines 71 to 81).
- D6 (feeds in the MVP): all eight feeds. The user chose this on 2026-11-13. Outcome O10 (one-feed restriction) and NEW-ONE-FEED-SWITCH are dropped. Each tick requests all eight NSE feeds. Parsers and fixtures exist for all eight (tests/fixtures/home_events/ has eight NSE XML files; scanner/home_events.py has the feed registry). Risk: all eight share one NSE host and one NSE cooldown (D7), so one 403 pauses all eight for the cooldown.
- D7 (cooldown): DECIDED, flat 1 hour per host (user, 2026-11-14). A flat hour is the simplest rule that stops hammering a blocking host; the per-class backoff (15, 30, 60 minutes) and the 2 hour figure are dropped. S2 must match the existing Cooldown Protocol signatures active(host, now), block(host, now, reason) and reset(host) in scanner/home_events.py lines 229 to 238, not block(host, reason, now).
- D8 (Sast_Regulation31 values): decided 2026-11-13, option B. No size threshold: the Sast31 feed carries no share count, value or percentage (see docs/designs/t4f-d8-sast31-values.md), so the Home cap of 3 events per stock is the only limiter, and a size rule waits for a source that carries one. Age floor: ingest_floor_days = 730 for all eight feeds, applied at ingest. The 730 value keeps all 20 Related_Party_Trans fixture items (oldest 628 days).
- Totals: see section 5. The earlier totals are superseded (revised 2026-11-13).

## 0a. Audit result (2026-11-13)

A 79-agent read-only audit checked the code against this plan. It changed no code.
No item is a full re-implementation of existing code.
The biggest shrinks are F-T4f, F-T5c, MT1 (done), F-T1, F-T9 and NEW-ALL-EIGHT-FEEDS.
Removed or shrunk items, condensed from the audit:

- MT1: removed from Must; done 2026-11-12; a monthly refresh checklist stays.
- F-T4f: 4-7 days down to a fixture regression test and spec or doc fixes. The library is already built and tested. The loader call moves to F-T4d.
- F-T5c: down to events pool config, pool swap, health ping, token decision, checkIngestToken test and smoke POST. The route, auth, validation and dedupe SQL exist.
- S3: slightly smaller. The "stop Node" edit is a no-op. Anchors, token mount and the compose test loader exist. Per-source instances move to S6-S8 and T9.
- F-T1: down to an optional two-INSERT migration. Row creation is automatic once SOURCES['home_filings'] exists.
- F-T9: down. The mode and cron flip uses the existing PUT /api/config route. The 052 row and the run-once service are counted elsewhere.
- F-T4d: about the same, now glue only. It absorbs the loader call, the cooldown adapter and NEW-DOCSTRING-FIX.
- NEW-ALL-EIGHT-FEEDS: down to two fixture-driven run_cycle tests. The registry, parsers and fixtures exist.
- NEW-SAST31-MEASURE: down to a one-off script merged with F-T4f. The all-feed figure exists (filings spec line 375).
- NEW-T4F-SPEC-TESTS: down to a doc edit. The tests exist.
- NEW-LIVE-NSE-RUN: warm-up dropped. The first run merges into F-T9 acceptance. A second-day check remains.
- NEW-DOCSTRING-FIX: folded into F-T4d.
- NEW-MVP-DECISIONS: closed by D8.
- BUILT-CLAIMS verification gate: removed. All five claims are verified built.
- S7 (deferred): the "queue exists" dependency is dropped. The seeded cron in db/migrations/001_core.sql lines 93 and 95 is enough.
- S8 (deferred): the S8-on-S7 dependency is dropped.

## 1. MVP definition

All eight NSE feeds (D6) and the read route with the first Home feed slice (D1) are in scope. Each tick, for each of the eight feeds, the home_filings runner (run_cycle in scanner/home_events.py):
1. fetches the feed;
2. parses it;
3. resolves each company name to exactly one (symbol, ISIN) pair from company_reference source nse_csv;
4. drops unresolved or ambiguous names as universe rejections;
5. posts the resolved rows to POST /internal/events/batch, one POST per feed (up to eight per tick);
6. stores them in the events database with dedupe_key idempotence.

The MVP ends at stored, deduplicated events, plus GET /api/events and the first Home feed slice (NEW-HOME-FEED). GET /api/events is specified in the ui-redesign spec (line 424). The Home event feed is Not built (ui-redesign-spec.md line 289).

The LLM stage, Telegram, RSS, Upstox and the llm-client tasks (t4f LC0 to LC7) are not on this path.

Feed choice is moot under D6. Sast_Regulation31 stays the O1 named-test feed (D2).

## 2. Outcomes the MVP must meet

- O1 Parser: the named test for nse:Sast_Regulation31 passes on its real 20-item fixture. Every parsed item has an http or https source_url and a headline of 500 characters or fewer. Coverage: the parser test exists, but the per-item http/https and headline assertion must be added (tests/test_home_events_parsers.py:187 lacks it).
- O2 Resolution: on the same 20 items, name resolution against company_reference nse_csv gives a recorded resolved count and rejected count. Ambiguous count is 0. Each rejected item counts as reason universe. The run message reports rejected universe=<n>. Coverage: needs a committed universe snapshot, or stays a recorded measurement.
- O3 ISIN agreement: a name-resolved item whose ISIN disagrees with an ISIN the item carries is rejected, not stored (test_name_resolved_item_with_disagreeing_isin_is_rejected, tests/test_home_events_run.py:540).
- O4 Post: each feed posts its resolved rows in one request of at most 500 rows (up to eight requests per tick). inserted + duplicates + invalid equals rows sent, and invalid is 0 on the sample. The due path posts via post_events, and collect.api_base_url() supplies the API base.
- O5 Idempotence: a second tick on an unchanged feed inserts 0 new rows (INSERT ... ON CONFLICT (dedupe_key) DO NOTHING). Coverage: needs a two-tick test or real Postgres (homeEventsBatch.test.ts:76 checks SQL text only).
- O6 Stored row shape: exchange NSE, feed Sast_Regulation31, non-null symbol and ISIN, published_at with UTC offset, http or https source_url. A row that fails validation is counted in invalid and the run ends failed with invalid:<n>.
- O7 Schedule: the home_filings row is created manual with cron */5 8-20 * * 1-5 (filings spec lines 268 to 282). F-T9 flips it to scheduled through PUT /api/config/home_filings. The O7 check runs after that flip. The runner starts at most once per 5-minute slot on weekdays, and the latest collector_runs row for home_filings reads status ok. Coverage: not built (no home_filings seed or runner yet).
- O8 Block handling: a 403 or 429 from NSE stops the run with no retry. During the cooldown window the due check omits home_filings and the run makes zero requests (tests 403_is_blocked_without_retry and cooldown_active_skipped_zero_requests, filings spec line 595). Coverage: 429 is tested only in the pure classifier (tests/test_home_events_pure.py:232), so a 429 case is added at fetch and run level. The due-check half depends on S2 and S5a.
- O9 Scope: an MVP run makes zero calls to llm-client and reads no provider key.
- O10 All eight feeds (decision D6): an MVP run requests all eight NSE feeds. This supersedes the one-feed restriction. No per-feed switch is needed.

## 3. Must items and effort (person-days)

Revised figures are planning estimates, not measured.

| Item | Status | Old low-high | Revised low-high | What remains |
| --- | --- | --- | --- | --- |
| MT1 operator refresh of nse_csv company_reference | Done 2026-11-12 | 0.25-0.5 | 0-0.1 | Monthly refresh due 2026-12-12. Run scripts/check_loader_grants.py first. |
| S0 report-only measurement | Done | 0.5-1 | 0 | Report docs/progress/collector-split-s0.md (2026-11-12). Closed. |
| S1a execute_source, run-once, health for events sources | Merged (PR 120, commit 3e7b5b5) | 2-3 | 0 | The status contract (failed and skipped to collector_runs) moves into F-T4d. |
| S1b collector_services.json and claim_requests | Merged (PR 120, commit 3e7b5b5) | 1-2 | 0 | Committed with S1a. |
| S2 source_cooldown table, migration 049 | In progress | 0.5-1 | 0.5-1 | Table source_cooldown (migration 049 with down file) plus scanner/collect/cooldown.py PgCooldown with the flat 1 hour rule (D7, decided 2026-11-14). Protocol adapter for host nse only. tests/test_source_cooldown.py on real Postgres. Legacy fetcher wiring deferred. Grants arrive with 050 (S5a). The filings spec claim that source_cooldown exists is wrong. Gates S5a and F-T4d. |
| S3 compose service per source | S3 server service built (PR pending), run-once services deferred | 2-3 | 1.5-2.5 | Compose and server container. Reuse the x-persist, x-scanner-db-env and &persist-config anchors, the token-mount pattern and the tests/test_compose_llm_network.py loader. Start.ps1:418 only runs compose up -d ui collector, so add server. Per-source instances defer to S6-S8 and T9. Decide: how the server container gets .env and data/secrets.env, and SERVER_HOST (server/src/index.ts:46 hard-codes 127.0.0.1). Status 2026-11-14: the `server` service is built, and SERVER_HOST is in place. Run-once services are deferred. The container's database login is decided (2026-11-14): new role `market_scanner_server`, grants in migration 057 (never applied until the user creates the role and sets its password), password file mounted at /run/app-keys/server_db_password. Database-backed routes connect once the role exists and 057 is applied. S3b (token fetch) is implemented in a PR on branch feat/s3b-server-token-fetch, not merged: the server fetches its Upstox and Kite keys from the ui secrets endpoint. |
| S5a GET /internal/due and due rule, migration 050 | Not built | 1-2 | 1-2 | server/src/collectorDue.ts (TS due rule: ok-only slot catch-up, never-run, 15-minute retry gap, cooldown omission, services filter). collectorDueRoute.ts with watchdog token (401, 503, 500). app.ts registration. Migration 050 grants (collector_settings and source_cooldown to the app role). Pinned cron-parser dependency, needs user approval before install. Vectors file tests/data/collector_due_vectors.json with a Python test. Needs S2. |
| F-T1 home_filings registration, migration 052 | Not built | 0.5-1 | 0.25-0.5 | Optional two-INSERT migration with down file. Inserts the home_filings collector_settings row as mode manual with cron */5 8-20 * * 1-5. ensure_sources creates the row anyway once SOURCES['home_filings'] exists. If the "migrate --status lists it" acceptance is dropped, the migration can be replaced by a flip in F-T9. |
| F-T4d HomeFilings source and cooldown adapter | Not built | 1-2 | 1-1.75 | Glue only. HomeFilings(Source) in scanner/collect/sources.py. run() loads the nse_csv index with load_index_for_source and passes .universe and .by_name (by_name=None silently skips resolution). Plain Session with browser headers and no warm-up. Reads the ingest token file. Calls run_cycle with post_events and the DB-backed Cooldown adapter over S2's table. Registers SOURCES['home_filings'] and updates tests/test_collect_sources.py lines 172 to 175. Also: align the flag name (S1a ships events; filings spec and slices use events_source), surface failed and skipped run_cycle status to collector_runs (collect.py lines 142 to 148), and reuse collect.api_base_url(). Needs S1a and S2. Absorbs NEW-DOCSTRING-FIX. |
| F-T4f name resolution (O2, O3) | Done 2026-11-14 (fixture-crossing test built and passing; library part verified done). Wiring left to F-T4d. | 4-7 | 0.5-1 | Offline test that crosses the eight fixtures with a small committed name fixture and records resolved and rejected counts (O2). Optional pure count_isin_conflicts test. Correct the spec text. Absorbs the per-feed counts of NEW-SAST31-MEASURE and NEW-ALL-EIGHT-FEEDS. The H9 dependency is removed and the MT1 dependency is done. |
| F-T5c events pool and index.ts wiring (O4 to O6) | Partly done 2026-11-14: items 1 and 5 built and passing (eventsPoolConfig, checkIngestToken tests). Items 2, 3 and 6 left; item 4 (token path) complete via S3 (ingest token) and S3b (secrets token fetch). | 1-1.5 | 0.5-1 | (1) eventsPoolConfig(env) in server/src/config.ts using POSTGRES_EVENTS_DB (default market_scanner_events), DSN and parts forms, with tests. (2) Second Pool in server/src/index.ts passed to makeEventsTx (index.ts lines 27 and 38 pass the main pool today, so a live batch returns 500), ended in onClose. (3) Events ping in /api/health via an optional AppDeps dependency, outside the session gate. (4) Token path: decided and applied 2026-11-14 in the S3 slice (SERVICE_TOKEN_DIR=/run/app-keys, single-file mount); the user still provisions the secret file. Item 2 also needs INSERT on home_events for the server login (market_scanner_server) in the events database: db/events_migrations/002_server_role_grants.sql (written with S3, not applied). (5) checkIngestToken unit test (none exists). (6) Smoke run: post the same row twice on a migrated events DB (inserted 1, then duplicates 1). Also fix filings spec 4.6 and CHANGELOG.md line 33, which say 413 precedes auth. Must finish before F-T9 and NEW-HOME-FEED. |
| F-T9 runner wiring and cron (O7) | Not built | 1-2 | 0.5-1.25 | Config, compose and live acceptance run. Add home_filings to config/collector_services.json (settle host versus exchange first; the file is untracked and holds {"sources": {}}). Add config/collector_runtime.json with the 330 s limit if S3 defines it. Add the home_filings compose service under the collectors profile (copy the collector block). Flip mode to scheduled via PUT /api/config/home_filings. Prove with one run-once start and a collector_runs row with status ok. Dependencies unchanged: F-T1, F-T4d, F-T5c, S1a, S1b, S2, S3, S5a. |
| Must remaining subtotal (MT1, S2, S3, S5a, F-T1, F-T4d, F-T4f, F-T5c, F-T9) | | 11.25-20 | 5.75-11.1 | Old is 14.75-26 for all 12 rows, minus S0, S1a and S1b (0.5+2+1 = 3.5 low, 1+3+2 = 6 high). Revised is the sum of the revised column. |

Conditional, kept (D4 keep): S4 watchdog and max-runtime stop. Old 1-2; revised 1.5-2. Greenfield: there is no reusable code (no scanner/watchdog, no scripts/watchdog.ps1, no config/collector_runtime.json). Needs S3 and S5a. Cheaper alternative: a Task Scheduler call running docker compose --profile collectors run --rm --no-deps <service> with a timeout wrapper on the S3 services. config/collector_runtime.json needs S0 measurements (collector-split-s0.md exists).

## 4. New items (added by the MVP workflow)

| Item | Status | Old low-high | Revised low-high | What remains |
| --- | --- | --- | --- | --- |
| NEW-ONE-FEED-SWITCH | DROPPED (D6, 2026-11-13) | 0.5-1 | 0 (dropped) | Not counted. |
| NEW-SAST31-MEASURE: measure resolved and rejected counts (O2) | Partly open | 0.25-0.5 | 0.1-0.25 | Only the per-feed Sast_Regulation31 count on the full nse_csv list is missing (t4f-d8-sast31-values.md line 68). Merged into F-T4f. Not a separate task. |
| NEW-T4F-SPEC-TESTS: resolution tests in the spec table | Done 2026-11-14 (doc corrections; DOC-CORRECTIONS in CHANGELOG) | 0.25-0.5 | 0.1-0.25 | List the existing tests in spec section 8 (test_company_reference; tests/test_home_events_run.py lines 527 and 540). Change the T4f acceptance command at filings spec line 630 to tests.test_company_reference plus tests.test_home_events_run. Refresh the T4c count (42 tests; spec says 40). Fix home-events-t4f-design.md lines 243 and 388. Write no new resolution tests. |
| NEW-LIVE-NSE-RUN: live NSE access check | Open | 0.5-1 | 0.25-0.5 | Cookie warm-up removed. F-T4d uses a plain Session with browser headers and no warm-up. The first live run merges into F-T9 acceptance. Keep one second-trading-day observation from the same host or container as production. The T0 headers cannot be confirmed (data/home_samples/ is absent). enrich.py lines 284 to 285 say nsearchives rejects a cold client. |
| NEW-DOCSTRING-FIX | Folded into F-T4d | 0.1 | 0 | Remove the sentence at scanner/home_events.py lines 695 to 696 when F-T4d adds the caller. Fix lines 5, 53 and 583. Do not point it at T9 (filings spec line 379 names T9 for loader wiring, so the pointer is ambiguous). |
| NEW-HOME-FEED: GET /api/events read route and Home feed slice (D1) | Planning estimate, not from a spec | 2.5-4.5 | 2.25-4 | Includes a 0.25-0.5 day contract addendum before dispatch (GET params, response shape, event tiers). Prerequisite: F-T5c. The 3-per-stock cap and shortlist rule cite home-event-sources.md lines 164 to 173 (ui-redesign-spec.md records them as Not built at lines 191 and 289). First slice is filings-only, with shortlist inputs from stock_snapshots.metrics. Reuses the session gate, apiGet, StateView, the results.ts client pattern and the route-test helper. No database migration. |
| NEW-ALL-EIGHT-FEEDS (D6): test-only | Done 2026-11-14 (both run_cycle tests built and passing) | 1-2 | 0.25-0.75 | FEEDS (scanner/home_events.py lines 586 to 595) and PARSERS (lines 795 to 804) already cover all eight. Tests: (1) one run_cycle test with real FEEDS and home_events.parse over the eight fixtures, asserting eight requests and eight feed codes; (2) a variant where the Nth feed returns 403, asserting one cooldown.block and no later requests. The per-tick runner belongs to F-T4d and F-T9. |
| NEW-DATE-FLOOR (D8): ingest age floor | Done and verified (merged PR 121, commit 99e8a19; suite passing 2026-11-14) | 0.25-0.5 | 0.25-0.5 | ingest_floor_days = 730 for all eight feeds, applied one step before filter_items in run_cycle (scanner/home_events.py, call site near line 496). New rejection reason date_floor. Config key in _run_config with an upper-bound guard, and the run message. Add the key to scanner/collect/settings.py lines 206 to 209. Update tests/test_collect_settings_sources.py lines 68 to 73 and filings spec lines 366 to 371, 657 and section 7. Tests: boundary kept, older dropped and counted, all-rejected, bad config (0, negative, bool, huge). The API checks only ISO 8601 for published_at (homeEventsBatch.ts lines 65 to 88), so the floor lives in the runner. |
| NEW-O1-O8-ACCEPTANCE: per-outcome test gaps | Done 2026-11-14 (per-item assertions and 429 tests built and passing) | n/a | 0.25-0.5 | Per-item http/https and headline of 500 characters or fewer assertions in the Sast31 parser test. A 429 test at fetch and run level. Tags on which outcomes depend on unbuilt wiring. |
| NEW-MVP-DECISIONS: insider threshold and age floor | Closed (D8, 2026-11-13) | 0.25-0.5 | 0 | Removed from the open list and the effort table. |

New items subtotal: old 5.1-9.6 (sum of the old column without NEW-ONE-FEED-SWITCH; the earlier line 1.85-3.6 was wrong). Revised 3.45-6.75 (sum of the revised column).

## 5. Totals

- Remaining work without S4: 9.2 to 17.85 person-days (5.75-11.1 Must plus 3.45-6.75 new). Old plan for the same remaining work: 16.35 to 29.6 (old totals 19.85 to 35.6 minus S0, S1a and S1b at 3.5 to 6).
- Remaining work with S4: 10.7 to 19.85 person-days. Old plan for the same remaining work: 17.35 to 31.6.
- S0, S1a and S1b are done or built, so they are no longer counted.
- The old totals 19.85 to 35.6 without S4 and 20.85 to 37.6 with S4 are superseded.
- These are planning estimates, not measured. The audit's stated new-items figure of 6.85 does not match its rows, which sum to 6.75. The row sum is used.
- Calendar: these are effort figures, not dates. The split-spec track (D3) runs as a chain, one code writer at a time.

## 6. Deferred and dropped

- Deferred (not in the MVP): all LLM items (LC1 to LC7 and the GAP-LC items), S2a, S5b, S6, S7, S8, S9, F-T8 (order-win feed), F-Z2-BSE, F-4.4 reconciler, F-NSE-BACKFILL, DT-2 to DT-6, DT-8, DT-9, H4, H6, H7, H8, cal-06, cal-07, A3, DEC-BENCH-EXTRACTCHECK, LC-GATE-GOLDFISH, DEC-M22-VS-DB2.
- Audit notes on deferred items:
  - S2a: NOT_EXISTS. On the critical path for any later move of the filings, fundamentals or ath_scan containers. Needs the NB4 decision first.
  - S5b: needs a new session-gated route, not /api/health. The spec's "existing market-status response" does not exist. Market status is computed client-side (ui-v2/src/lib/marketSession.ts line 16).
  - S6: compose and config only (candles_eod, index_eod, ath_scan). Needs a trigger (S4 or S5a) first.
  - S7: splits into S7a corporate_actions and S7b fundamentals (after S2a).
  - S8: needs a cron decision first. The announcements source goes ahead of filings.
  - S9: must re-home claim_requests and the lost periodic first_run.tick re-check.
  - F-T8: reword to expose order wins from announcements and enrich values.
  - F-NSE-BACKFILL: the fetcher is reusable (factors.py lines 638 to 706, factors_postgres.py). The real work is event_type mapping and dedupe-key alignment.
  - DT-2: gate is done. Define DT-N in this plan as db-touchpoint-v2.md rollout step N.
- Dropped: F-T10 (fundamentals queue moved out), and the C1 and C2 items (dep-c1-api-gateway, dep-c1-db-writes-move, DEC-LLM-DIRECT-WRITES, dep-c2-token-files, gap-scanner-token-unused, comp-token-mounts, gateway-allowlisted-llm-route, server-no-llm).
- DT-7 (mount ingest route) stays deferred but links to F-T5c. POST /internal/events/batch is registered in the production entrypoint (server/src/index.ts lines 37 to 38, app.ts lines 307 to 308) but is pointed at the main-database pool, so it cannot store events until F-T5c lands.
- H9: not a real item. No doc defines it.

## 7. Migration numbers

- 047 company_reference: taken (file exists).
- 048 index_constituents: applied 2026-11-12 (checked in the market_scanner database on 2026-11-13). The earlier PENDING note is stale.
- 049 S2 source_cooldown: free. Assigned 2026-11-12 (docs/progress/collector-split-spec-requests.md line 19).
- 050 S5a grants: free. Must apply after 049, because it grants SELECT on source_cooldown. It also grants SELECT on collector_settings and source_cooldown (and any other table the due query reads) to the app role. Only 042 and 043 grant collector_requests and collector_runs today.
- 051 S8 filings cron: free. S8 is deferred, so 051 is not needed for the MVP. Keep it reserved. If used, it is a data migration with a guard UPDATE ... WHERE source='filings' AND cron='10,40 8-20 * * 1-5' and a down file. The legacy filings cron still needs a user decision.
- 052 F-T1 home_filings registration: optional (see F-T1). The filings spec NNN placeholders (lines 44, 268, 275, 331, 619) must be updated.
- 053 fund_daily, 054 llm_provider_store, 055 llm_calls_provider: taken (files exist).
- S2a: 056. S2a is deferred.
- 057 server_role_grants: grants for the new `market_scanner_server` login (S3). The role is created out of band with its password set by the user; the migration holds no secret and is not applied by this work.
- Runner behaviour (scanner/pg/migrate.py lines 44 to 82): files are sorted by filename, each unrecorded file is applied in order, and gaps are tolerated. An edited applied file raises an error. On a database that already has 053 to 055, 049 to 052 apply after them. This is safe as long as no migration reads schema from 053 to 055. 049 and 050 share no dependency on those.
- Do not use db/events_migrations/ for main-database work.
- Doc-status conflict: home-events-t4f-design.md D12 says "Recommendation, needs approval", while docs/progress/collector-split-spec-requests.md line 19 records the user accepting the 049 to 052 assignment on 2026-11-12. Confirm which status is current before the split spec is approved.

## 8. Dependency corrections from verification

- S1b: needed (F-T9 and S5a). Moved from defer to must.
- S4: conditional (decision D4).
- H9: undefined, removed from F-T4f.
- DT-7: moved to defer (the route exists; it needs F-T5c to store events).
- S0: moved to must (S1a, S2 and S3 need it). Now done.
- Verified built on main: T2a, T5b, T4a, T4c and T6 (commits ebeefe2, 7c48bec, 109b5a4, 902e90f, 089a975 and 0d55e24 are ancestors of HEAD). T4c and T6 have no production caller until F-T4d. T2a's 10 Postgres tests were not run. T5b has no checkIngestToken test. The pre-dispatch re-check gate is removed.
- MT1: done.

## 9. Open decisions (the user must answer)

Decided: D1, D3, D4 (keep S4), D5, D6, D7 (flat 1 hour, 2026-11-14), D8. See section 0. Token path and secret mounts: decided 2026-11-11, applied 2026-11-14 (see the "Token path" bullet below).

Open:
- D2: awaiting the user's confirmation. Only the per-feed Sast31 count on the full nse_csv list is missing (NEW-SAST31-MEASURE).
- D7: DECIDED 2026-11-14, flat 1 hour per host (user). The per-class backoff and the 2 hour figure are dropped. S2 must match the Cooldown Protocol signatures active(host, now), block(host, now, reason) and reset(host).
- Legacy filings cron for S8: db/migrations/001_core.sql line 94 says 10,40 8-20 * * 1-5. The spec's */5 applies only to home_filings. S8 must not conflate the two.
- Token path (decided 2026-11-11, applied 2026-11-14, no longer open): bearer tokens between our own services are read from a per-token file under /run/app-keys, never from the DB, an env value or the repo. The home-events ingest token is /run/app-keys/home_events_ingest_token. The `server` service mounts only that file, read-only, as a single-file bind mount. The host path comes from APP_HOME_EVENTS_INGEST_TOKEN_FILE with a `:?` guard, so compose refuses to start when it is unset. The server never mounts the folder that holds app_master_key (only `ui` holds it). SERVICE_TOKEN_DIR=/run/app-keys is set in the server environment. The code default (/run/service-tokens) is unchanged.
- Server container database login (decided 2026-11-14, user): the server container uses a NEW dedicated login role `market_scanner_server` (pattern of `market_scanner_loader`), not the `scanner` login. Migration 057 grants it least privilege and does not create it; the user creates the role and sets its password out of band. The password is a single-file read-only mount at /run/app-keys/server_db_password (host path from APP_SERVER_DB_PASSWORD_FILE with a `:?` guard), read by `POSTGRES_PASSWORD_FILE` support in server/src/config.ts. No env_file, no ./data mount, no key folder. Upstox and Kite tokens are fetched from the ui internal secrets endpoint (S3b, implemented in PR on branch feat/s3b-server-token-fetch, not merged). The server mounts a second single file, /run/app-keys/server_secrets_token, read-only from APP_SERVER_SECRETS_TOKEN_FILE. It reads that file through SECRETS_TOKEN_FILE, with the base URL in SECRETS_API_URL. Open after S3b: (a) kite_access_token is runtime-only and not served to any service, so Kite holdings report "unconfigured" in the container until the user decides how the daily access token is delivered; (b) the server uses the analytics token for live feeds and the old UPSTOX_ACCESS_TOKEN fallback is dropped, so a separate non-analytics live token needs its own key.
- Flag name: events (S1a, scanner/collect/sources.py lines 40 to 43) versus events_source (filings spec line 447 and slices doc).
- collector_services.json field name: host (filings spec line 40) versus exchange (line 636).
- NB4 CSV or xlsx fate: blocks S2a.
- Whether to drop migration 052.
- cron-parser dependency for S5a: needs user approval before install.
- claimed_at COALESCE in link_request_to_run.
- Whether to commit config/collector_services.json with S1b.

## 10. Tasks, paths and acceptance (for the per-task spec written after approval)

Acceptance command for every Python task: .venv/Scripts/python.exe -m unittest discover -s tests -t . -q
Acceptance for server tasks: npm test in server/ (vitest), including the due route tests.
A full-suite run needs Postgres for the pgschema tests. Postgres-backed new tests: test_source_cooldown, the F-T1 registration test and test_collect_claim_pg. A skip is not a pass.

- O1: tests/test_home_events_parsers.py (-k Sast_Regulation31). Parser code in scanner/home_events.py.
- O2 and O3: scanner/company_reference.py (fill_from_name at line 236, load_index_for_source at line 269); scanner/home_events.py (filter_items at line 145, run_cycle at line 408); tests/test_company_reference.py lines 200 and 208; tests/test_home_events_run.py line 527 (name-only resolution, test_name_only_items_resolve_through_by_name) and line 540 (name supplied with a conflicting ISIN, rejected as isin_conflict, test_name_resolved_item_with_disagreeing_isin_is_rejected).
- O4 to O6: server/src/homeEventsRoute.ts; server/src/app.ts; server/src/config.ts; server/src/index.ts; server/src/homeEventsAuth.ts; server/src/homeEventsRoute.test.ts; scanner/home_events.py run_cycle. F-T5c status 2026-11-14: the token path part is done in the S3 slice (SERVICE_TOKEN_DIR=/run/app-keys). The events pool swap is still open.
- O7: config/collector_services.json (exists, untracked, currently {"sources": {}}; S1b and S3 work); config/collector_runtime.json (S3 and S4); the S3 compose service; db/migrations/052_home_filings_registration.sql (+ down file, optional). S3 status 2026-11-14: server service built (PR pending); run-once services deferred.
- O8: scanner/collect/cooldown.py; tests/test_source_cooldown.py; db/migrations/049_source_cooldown.sql (+ down); db/migrations/050_internal_due_grants.sql (+ down); the S5a due handler in server/ (server/src/collectorDue.ts, collectorDueRoute.ts); tests/data/collector_due_vectors.json with a Python test that runs the vectors against scheduler.due_sources.
- O10: all eight feeds (D6). No switch is needed.
- scanner/collect/services.py and tests/test_collect_*.py are S1a and S1b work in the dirty tree. They must be committed before S2 starts.

What must not change without a new decision:
- Files already applied: 047, 048, 053, 054, 055 (the runner raises an error if an applied file is edited).
- db/events_migrations/ (not for main-database work).
- llm-client code and its provider settings.
- Secrets handling: tokens stay in the file path /run/app-keys/home_events_ingest_token, as the spec defines (filings spec line 427).
- UI reads go only through the Fastify API.

## 11. Critical path and risks

Critical path, in order (one code writer at a time, D3):
1. Done: S1a and S1b are merged (PR 120, commit 3e7b5b5).
2. Finish S1a's status contract: failed and skipped must reach collector_runs.
3. S1b (commit config/collector_services.json with it).
4. S2: migration 049.
5. S5a: migration 050 (needs 049).
6. S3: compose service and server container. Status 2026-11-14: server service built (PR pending); S3b token fetch implemented (PR on branch feat/s3b-server-token-fetch, not merged); run-once services deferred. The container's database login is decided: role `market_scanner_server`, migration 057, password file mount (see section 9).
7. F-T9: config, compose service, mode flip and live run.

Side notes on the path:
- F-T4d needs S1a and S2, and finishes before F-T9.
- F-T1 (optional 052) needs nothing and can go any time before F-T9.
- F-T5c must finish before F-T9 and before NEW-HOME-FEED.
- S4, if kept, comes after S3 and S5a and is not on the F-T9 path.
- NEW-HOME-FEED follows F-T5c and the contract addendum. It does not need the collector track.
- Parallel, no collector track needed: NEW-DATE-FLOOR, the F-T4f fixture test, the NEW-T4F-SPEC-TESTS doc edit and the spec corrections. They touch scanner/home_events.py, tests and docs only.
- S2a is on the critical path only for later moves of filings, fundamentals or ath_scan, not for the MVP.
- Decisions needed before their tasks start: flag name (before F-T4d); collector_services.json field name (before F-T9).

Risks (new, from the audit):
- F-T5c wrong database: server/src/index.ts lines 27 and 38 pass the main pool to makeEventsTx, and no migration in db/migrations creates home_events. Batches return 500 until fixed.
- Failed runs recorded as ok: collect.py lines 142 to 148 store ok unless run() raises, so a blocked run looks healthy. S1a's status contract must be finished, or HomeFilings must raise.
- Flag name conflict: events (sources.py lines 40 to 43) versus events_source (filings spec line 447, slices doc).
- D7 backoff conflict: RESOLVED 2026-11-14, flat 1 hour per host (D7). The S2 block signature must match the Protocol (scanner/home_events.py lines 229 to 238).
- Filings spec is stale: it says name resolution is unbuilt (lines 552 and 610), says source_cooldown exists, and says 413 precedes auth.
- One 403 on the shared NSE cooldown pauses all eight feeds (scanner/home_events.py lines 461 to 519). The loop posts per feed (line 509), so up to eight POSTs per tick.
- Feed GETs go out with the default python-requests User-Agent unless HomeFilings sets browser headers (scanner/home_events.py line 246). Live NSE access was measured with unknown T0 headers.
- Server collisions: S3, F-T5c, S5a and NEW-HOME-FEED all touch server/src (index.ts, app.ts). Sequence them.
- Token path mismatch: index.ts line 28 reads SERVICE_TOKEN_DIR (default /run/service-tokens), while the spec uses /run/app-keys. docker-compose.yml has no mount, so every token gets 403 until decided and provisioned. Resolved 2026-11-14: the path is /run/app-keys, one file is mounted, SERVICE_TOKEN_DIR is set, and the code default is unchanged. The token file still has to be provisioned by the user.
- S5a adds a cron-parser dependency (none in server/package.json). Ask the user before installing.
- S5a grants: only 042 and 043 grant collector_requests and collector_runs. Migration 050 is required before the route works.
- Two due-rule implementations (Python scheduler.due_sources and the new TS rule) can drift. The shared vectors file does not exist yet. collect.py cmd_status still uses due_sources, against the spec's "due_sources gone" (affects S9).
- S1a and S1b are merged (PR 120). Plan line references can change. S6 depends on run-once.
- NB4 conflict for S2a: the spec says ath_scan stops writing the CSV, but about nine readers were found (including start.ps1, a non-Python consumer). Raise with the user.
- collector-split-spec.md line 72 says fundamentals is not scheduled, but db/migrations/001_core.sql lines 93 and 95 seed it scheduled. corporate_actions max runtime is 1585.5 s, so the limit must exceed 26 minutes.
- Listing a source in collector_services.json makes serve skip it. If a source moves before a trigger (S4 or S5a) exists, nothing runs it.
- Lost behaviour at S9: the periodic first_run.tick re-check disappears, and claim_requests (manual Refresh) has no home until S5a or run-once --request-id is wired.
- Filings spec has two names for one field: host (line 40) versus exchange (line 636) for collector_services.json.
- Filings cron ambiguity: the */5 applies to home_filings. The legacy filings source (db/migrations/001_core.sql line 94, 10,40 8-20) is a different source. S8 must not conflate them.
- Test limits: the one-bad-feed and cooldown behaviour are tested only with FakeCooldown and three invented feeds. No test covers a real DB-backed cooldown. 429 is only tested in the pure classifier.

Unverified (from the audit):
- MT1 data load (nse_csv 2633, upstox_master 2757, seven index counts) rests on docs (company-reference-handoff.md line 21, home-events-t4f-design.md lines 194 to 197, ledger). No database was queried.
- T2a's 10 Postgres tests were not run. The F-T1 registration test, S2 tests and collect_claim_pg need real Postgres and were not run.
- The per-feed Sast_Regulation31 match count on the full nse_csv list is not measured. Known: 10 of 20 under the old 751 universe, and the all-feed 111/0/31 figure.
- Live NSE access with the headers HomeFilings will use is unverified. T0 headers cannot be confirmed (data/home_samples/ is absent, no probe script). enrich.py lines 284 to 285 conflict with the cold-200 result.
- Working-tree lines (collect.py lines 76 to 92 and 142 to 148; sources.py lines 40 to 43; scheduler.py; services.py) belong to S1a work in progress and can change. They were compared with HEAD only, not re-opened.
- The 3-day Mongo and ./output requirements of fundamentals and filings containers, and the 26-minute corporate_actions handling (S7), are estimates from docs, not tested.
- DT-3 to DT-6 and DT-9 route counts (about 14 legacy ui routes) come from db-touchpoint-v2.md and are not re-counted. The 18 to 30 day range is a planning estimate.
- Only the two plan documents were re-opened in this step. All code evidence is from the audited records.
- Whether test_collect_settings_sources, test_home_events_run and test_home_events_client still pass after the other agent's edits is unchecked.

## 12. Doc corrections still to make (not done in this edit)

- DONE 2026-11-14: Filings spec lines 552 and 610 call name resolution unbuilt. It is built.
- DONE 2026-11-14: Filings spec claims source_cooldown exists. It does not.
- DONE 2026-11-14: Filings spec 4.6 and CHANGELOG.md say 413 precedes auth. It does not.
- Filings spec lines 366 to 371, 657 and the section 7 table need ingest_floor_days.
- DONE 2026-11-14: Filings spec T4f acceptance command: changed to tests.test_company_reference plus tests.test_home_events_run.
- Filings spec NNN placeholders (lines 44, 268, 275, 331, 619).
- Spec line 40 says host; line 636 says exchange (collector_services.json field name).
- Spec line 447 says events_source; code uses events (scanner/collect/sources.py lines 40 to 43).
- DONE 2026-11-14: collector-split-spec.md line 72 said fundamentals is not scheduled; db/migrations/001_core.sql line 95 seeds it scheduled (corrected).
- scanner/home_events.py docstrings at lines 5, 53, 583 and 695 to 696 are stale.
- DONE 2026-11-14: home-events-t4f-design.md line 243 said the MT2 tests are not written (corrected; the four tests exist in tests/test_company_reference.py).
- DONE 2026-11-14: O1 per-item assertions exist (tests/test_home_events_parsers.py lines 187 to 191, called at line 232: http or https source_url, headline of 500 characters or fewer). The O2/O3 fixture-crossing name-resolution test exists (tests/test_home_events_resolution.py, committed snapshot tests/fixtures/home_events_resolution/name_index.json). Both modules ran OK (26 tests). The status rows in sections 2 to 4 (O1, F-T4f, NEW-O1-O8-ACCEPTANCE) were left unchanged for the orchestrator to update against plan_add.
