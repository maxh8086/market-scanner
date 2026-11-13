# DB routing v2: all database access through the Fastify API

Status: APPROVED 2026-11-13 by the user's "go ahead", adopting the Section 8 recommendations. See Section 1.
Date: 2026-11-13
Replaces (where decided): the recommended fixes in docs/designs/db-touchpoint-review.md.

Citation convention: file:line refers to the current file on disk. Review findings are cited as docs/designs/db-touchpoint-review.md, then the section name and number (for example "Hazards 7"). That file has no global finding IDs. The ID "M-22" appears in docs/designs/home-events-t4f-design.md:45, not in the review file.

---

## 1. Status and scope

This design (v2) sets one rule: Fastify (server/src) is the only process that holds database credentials. Every other container, including ui, reaches data by calling Fastify over HTTP. Section 2 records the user's decisions. Section 3 lists the planner's recommendations, which the user must approve; each is marked RECOMMENDED and is not decided. The recommended fixes in docs/designs/db-touchpoint-review.md are replaced by this design only where Section 2 or an approved Section 3 item decides them. The review file's own "Decisions the user must make" (db-touchpoint-review.md:5-15) use different numbers and are not the decisions in Section 2.

**Status: APPROVED by the user on 2026-11-13 with the single message "go ahead".** That approval adopts the planner recommendations in Section 8 as written. The user did not answer questions 1, 2, 6, 7, 9, 10 and 18 one by one, so the approval covers them as recommended. Section 7 step 1 (settle the open questions) is complete. Steps 2 to 9 have not started. Nothing has been committed or dispatched.

This design does not cover: code changes, migrations applied, grants changed, compose edits, token files created, or any task dispatched. Section 8 lists the open questions. Section 10 lists what was not verified.

---

## 2. Decisions made by the user

Quoted verbatim from the user's messages.

- D1 (Fastify as the API): "fastify, this was my decision recorded earlier"
- D2 (only the API has direct DB access): "its logical if i am routing everything through api, and only api will have direct access (it was recorded during planning phase) api will always remain exception"
- D3 (write gating): "gate them with session or csrfm, rest you decide the best"
- D4 (claim and lease): "go ahead, rest you decide the best"
- D5 (remove DB logins from collector and graph): "go ahead"
- Standing rule: "there would never be direct db access to any container or feature. all db access will be routed through api"

The D1 decision matches the repo record at docs/designs/collector-split-spec.md:62-66 (decided 2026-11-10: "the API" is the Fastify server). The D2 rule conflicts with the split spec at docs/designs/collector-split-spec.md:14, which keeps direct main-DB and Mongo access for the collector. See Section 8, question 1.

---

## 3. Planner recommendations (RECOMMENDED, for user approval)

Each item below is a recommendation. None is decided.

### R1 Fastify runs as a compose service (RECOMMENDED)

Today Fastify is a host process. It reads SERVER_PORT at server/src/index.ts:19 and binds 127.0.0.1 at server/src/index.ts:39-40, where the comment says "Loopback only. Never bind 0.0.0.0." (Correction: the brief gave lines 19-22 for the bind. The bind is at lines 39-40.) docker-compose.yml has no service named `server` (checked in the compose survey; the services are listed at docker-compose.yml:32-259). A container cannot reach a host 127.0.0.1 bind.

Proposed: run Fastify as a compose service on the default network (docker-compose.yml:267 names that network `market-scanner`). Publish the host port on loopback only, for example "127.0.0.1:8081:8081". Inside the container the process must bind an address that other containers can reach. That is not 127.0.0.1, so it differs from the comment at server/src/index.ts:39. The exact bind choice is open question 7.

### R2 Browser path: browser to ui to Fastify (RECOMMENDED)

Browser calls go: browser, then ui (serves static files and proxies /api/* to Fastify, holds no DB login and no master key), then Fastify. The browser never calls Fastify directly.

- Today ui loads the master key at startup (ui/app/main.py:15-23) and mounts a router at /api (ui/app/main.py:43). Both must stop (Section 4).
- Session and CSRF checks run in Fastify. ui must pass Set-Cookie and the CSRF response header through.
- Path overlap: ui and Fastify both define paths under /api. Fastify already serves /api/runs/:runId/results (server/src/app.ts:145), and ui serves /api/runs/{run_id}/results (ui/app/api.py:146). Fastify has /api/runs/latest (app.ts:133), but ui has /api/runs (api.py:74). The shapes must be compared before the proxy switches path by path.
- Today the browser sends no CSRF header (ui/app/static/app.js:845-847 and :863).

### R3 Write gating with session and CSRF (D3, RECOMMENDED details)

- Fastify sets an HttpOnly, SameSite=Strict session cookie from GET /api/session.
- Every POST, PUT and DELETE under /api requires header X-CSRF-Token equal to the CSRF token bound to that session. Compare with crypto.timingSafeEqual.
- Cookie parsing and token generation use node:crypto and hand parsing. No new npm dependency is needed. Current dependencies are in server/package.json:13-19 (fastify 5.12.7 at :15). server/src has no cookie or CSRF code today (a grep of server/src for cookie|csrf|session finds no cookie or CSRF code. The 'session' matches are collectorRefresh.ts:31 (IST trading-session comment), holdings/kiteHoldings.ts:83 (Kite session expired message), and holdings/kiteHoldings.test.ts:71 and :74 (same message). All are unrelated.)
- Sessions live in memory with a 12-hour expiry. That is fine for one Fastify process. A restart clears sessions, so the browser must call GET /api/session again.
- Existing unauthenticated writes that must gain session and CSRF: POST and DELETE presets (server/src/app.ts:265 and :275, path at :276), and POST collector refresh (server/src/collectorRefresh.ts:95). ui writes at ui/app/api.py:487 and :503 are covered in Section 6.
- Existing unauthenticated GET routes on /api (server/src/app.ts:130-357, for example /api/holdings at :307 and /api/live/indices at :324) are reachable by any container on the default network. Open question 9 asks whether GET routes also need the session.

### R4 Service callers get a bearer token and an explicit route allowlist (RECOMMENDED)

Each service caller (collector, graph, scanner jobs, llm-client, watchdog, events ingest, and any Telegram poller) gets its own bearer token, read from a file at startup. Each token maps to an explicit route allowlist.

- Replace the two-token check in ui/app/internal_secrets.py:65-89 (only collector and llm_client identities, keyed by file names at :39-40) and SERVICE_ALLOWED at :41 with a role-to-route table. Fail closed with 403 when a role has no token. The model is server/src/homeEventsAuth.ts:9 (403 when the role has no expected token) and :15 (checkIngestToken, role-keyed).
- Token file locations today: the collector token is mounted at /run/app-keys/collector_token (docker-compose.yml:149) and at /run/service-tokens/collector_token in ui (docker-compose.yml:167). The same host file has two container paths. Recommend one container folder for service tokens (/run/service-tokens) and keep /run/app-keys only for the master key.
- The master key (Decision 15 in docs/designs/secrets-and-roles.md:96) is loaded only by Fastify. Decision 15 says the collector's token is "the only credential the collector holds" and "the master key stays in the API container only" (secrets-and-roles.md:96).
- Decrypt location: scanner/app_secrets.py:4 says "The API is the only process that decrypts". get_value decrypts at scanner/app_secrets.py:74-82. That stays in Fastify (the review's open point at Accuracy 26).

### R5 Claim lease replaces the advisory lock (D4, RECOMMENDED; needs approval)

- collector_requests gains lease_token (uuid) and lease_expires_at. A claim sets both. Expiry is the run timeout plus 5 minutes. The run timeout is RUN_TIMEOUT_SECONDS = 3600 (scanner/collect/first_run.py:35, used at :66). collect.py:156 and :161 hardcode timeout_seconds=3600 instead.
- A stale lease (lease_expires_at in the past) is reclaimed by the next claim call. Open question 3 asks the user to confirm who reclaims.
- A running collector extends its lease through a heartbeat route.
- A skipped request (already_running, exchange_cooldown) returns to queued with not_before set to now plus 15 minutes. That matches the retry rule at docs/designs/collector-split-spec.md:69. It is never marked done silently. Today a claimed request is dropped when is_running is true (collect.py:161) or the source is missing (collect.py:166-171, which only logs), per db-touchpoint-review.md Hazards 1. collect.py is at the repo root, not under scanner/collect/.
- The advisory lock at docs/designs/collector-split-slices.md:71 (pg_try_advisory_lock on the run connection) is replaced by the lease. An advisory lock is held by one database connection and cannot follow a collector that talks HTTP.
- The new columns (lease_token, lease_expires_at, not_before) need a migration. Migration 049 is already claimed by S2 (docs/designs/collector-split-slices.md:132). Number to be assigned. See open question 14.
- Claim retries should be idempotent with a client request id (review Hazards 1).

### R6 Neo4j and Mongo count as all DB access (RECOMMENDED; needs approval)

Graph (graph_sync.py, Neo4j reads and writes) and collector Mongo writes also go through Fastify. ui imports the Mongo helper at ui/app/api.py:16 (scanner.mongo _redact). The split spec keeps the collector's direct Mongo access at docs/designs/collector-split-spec.md:14. That conflicts with D2; see open question 1 and open question 5.

### R7 Migrations run only in a one-shot admin job (RECOMMENDED)

- Only a one-shot admin job runs DDL, and it uses the Fastify image. No other container runs migrations.
- Migration 048 privilege fix (InsufficientPrivilege, docs/designs/collector-split-slices.md:320) stays an admin step outside migrations. The table is owned by market_scanner_admin, and the runner connects as market_scanner_app (same line). (Stale: 048 is applied, verified 2026-11-13; no 048 owner step remains.)
- record_run.py:28 imports the db module (from scanner.pg import db). record_run.py:92-93 imports and runs the migrate module (from scanner.pg import migrate; migrate.apply()). Both must move. (Correction: the brief said both lines import migrate. Line 28 imports db.)
- Today the migrate stage is in start.ps1 (docs/designs/home-events-filings-spec.md:410 names start.ps1 lines 283 and 288).

### R8 Ingest route mounted with checkToken and eventsTx (RECOMMENDED; ordering needs approval)

- POST /internal/events/batch is defined at server/src/homeEventsRoute.ts:24. It is not mounted in the shipped server. server/src/index.ts:26-33 passes only query, logger, live and kite to buildApp. app.ts:301-302 registers the route only when checkToken and eventsTx are both passed.
- v2 passes checkToken and eventsTx from index.ts, with the token map from R4 files.
- Order of checks today: a batch with more rows than MAX_BATCH_ROWS returns 413 before auth (homeEventsRoute.ts:28-29, auth at :32). The file's header comment (homeEventsRoute.ts:7) states that this order is deliberate. The test at server/src/homeEventsRoute.test.ts:107-122 asserts that checkToken is not called in that case (test name not read in this pass).
- RECOMMENDED: auth first, then the row limit. This reverses a documented decision and changes that test. Open question 10.
- Body-size limit: Fastify default bodyLimit with installed Fastify 5.12.7. The ordering of the body limit versus the 413 check is unverified (Section 10).

### R9 Cooldown cap conflict (RECOMMENDED: 1 hour for class "other"; needs approval)

- The split spec says the cap is 2 hours: "on HTTP 403, 429 or a block page ... doubling to 2 h on repeats" (docs/designs/collector-split-spec.md:84). That line is labelled "to be tuned".
- The S2 row of docs/progress/collector-split-spec-requests.md:18 records the user's backoff classes (2026-11-10): API class (upstox, fred) starts at 3 minutes, caps at 15 minutes; other class (every other host, including nse, bse and rbi) starts at 15 minutes, caps at 1 hour.
- Governing rule: docs/designs/home-events-filings-spec.md:7 says the collector-split spec governs on the cooldown. That rule points to 2 hours. The 2026-11-10 user decision in the requests file points to 1 hour. These two sources conflict. RECOMMENDED: 1 hour for class other, because it is the later and more specific user decision, and revise split spec line 84 to match. The user must confirm (open question 11).
- Table name: the split spec calls it exchange_cooldown (split spec line 83). The requests file renames it to source_cooldown (progress :18). docs/designs/collector-split-slices.md:132 says exchange_cooldown was never created and S2 creates source_cooldown directly. v2 uses source_cooldown.

### R10 Filings cron conflict (RECOMMENDED: */5 8-20; needs approval)

- The split spec says 7,22,37,52 8-20 * * 1-5 at docs/designs/collector-split-spec.md:135, and repeats it at :175 and :200.
- The filings spec says */5 8-20 * * 1-5 at docs/designs/home-events-filings-spec.md:278, and its Q1 at :672 says "Cron stays `*/5 8-20 * * 1-5`."
- RECOMMENDED: the filings spec value, and correct split spec lines 135, 175 and 200. Open question 12.

### R11 Watchdog finalisation of killed runs (RECOMMENDED; needs approval)

- docs/designs/collector-split-slices.md:284 says the killed-run row is finalised as "section 9, Q6". The file has no section 9. Lines 105, 132, 147 and 284 are cross-references to "section 9 Q3/Q4/Q5/Q6", and none of those Q numbers has an entry in the file. The open items sit undated in the "## Decisions" block (line 310), in the "Still open" list (line 325).
- RECOMMENDED: the API writes the killed-run row, through the finish route (Section 6) with status failed and message killed. The watchdog only calls the API. The watchdog has no database access (slices:284).

### R12 Stale migration numbers (RECOMMENDED: correct to 049)

- docs/designs/home-events-filings-spec.md:44 and docs/designs/collector-split-spec.md:205 say S2 takes 047. Correct both to 049.
- Evidence: docs/designs/collector-split-slices.md:132 says "049 (already claimed)". On disk, db/migrations has 040 to 048, then 053 and 054 (047, 048, 053 and 054 exist). 049 to 052 are not on disk.

---

## 4. Current DB touchpoints to remove (inventory)

Each entry gives the file and line, and the target. Target route names are in Section 6.

### ui/app/api.py

- Line 15: `from scanner.pg import db`. Target: removed. Fastify is the only DB client.
- Lines 27-30: safe_connection() calls db.connect(). Target: removed.
- Line 14: `from scanner import secrets_store`. Target: GET /api/secrets, open question 8.
- Line 17: `from scanner.collect import settings as collector_settings`. Target: removed. Writes move to Fastify (lines 491 and 507). Reads at lines 402 and 456.
- Read routes that query the DB: :74 (GET /runs), :87 (GET /runs/{run_id}), :146 (GET /runs/{run_id}/results), :255 (GET /stocks/{symbol}), :291 (GET /cost), :326 (GET /cost/{run_id}), :348 (GET /report), :398 (GET /config), :452 (GET /config/{source}), :583 (GET /stocks). Target: Fastify GET routes in Section 6.
- PUT /config/{source}: lines 487-501, update_setting call at :491. Target: PUT route, session plus CSRF (D3).
- POST /config/{source}/run: lines 503-516, request_run call at :507. Target: POST route, session plus CSRF (D3).
- GET /secrets: lines 522-525 (reads secrets_store.status()). Target: open question 8.
- PUT /secrets: lines 527-538. Returns 410 at :536. Stays 410.
- Extra review finding: ui/app/queries.py (COLLECTOR_RUNS_HISTORY used at api.py:411 and :468) is a collector read (db-touchpoint-review.md, Coverage 25).

### ui/app/internal_secrets.py

- Line 32: `from scanner.pg import db`. Target: removed.
- Lines 65-89: _authenticate with the two-token check (COLLECTOR_TOKEN_FILE and LLM_CLIENT_TOKEN_FILE, read at :72-73). Target: R4 role table in Fastify.
- Lines 92-95: _secret_name_allowed keyed by service name. Target: R4 route allowlist.
- Lines 98-116: GET /internal/secrets/{name}. Decrypts with load_master_key() at :107 and app_secrets.get_value at :109. Target: Fastify (R4 decrypt). Route kept, see Section 6.
- Lines 119-137: GET /internal/llm/providers/{provider_id}. Raw SELECT on llm_provider at :129. Target: Fastify route.

### ui/app/main.py

- Line 10: `from scanner.secret_crypto import load_master_key`. Target: removed from ui.
- Lines 15-23: check_master_key() and lifespan. ui holds the master key today. Target: removed. Fastify loads it.
- Lines 43-44: include_router for api and internal_secrets on the same port. Target: removed. ui keeps only static files and the proxy.

### llm_client/registry.py

- Line 20: constructor takes secrets_api_url. Line 35-36: bearer header from the token file. Lines 43-44: GET /internal/llm/providers/{id}. Lines 57-58: GET /internal/secrets/{name}.
- The URL value http://ui:8080 comes from compose, not from registry.py (docker-compose.yml:180 for llm-client, :142 for collector). Correction: the brief said registry.py:36 holds the URL; no SECRETS_API_URL string exists in registry.py.
- Target: point these at Fastify. The llm-client refusal contract stays as written (Section 11).

### Collector (scanner/collect and collect.py)

- collect.py:31 imports `from scanner.pg import db`. Connects at collect.py:65, 130, 145, 154, 176, 181, 199 and 229.
- scanner/collect/scheduler.py:12 imports db. Claim SQL at :72-93 (UPDATE at :82, ORDER BY at :87, LIMIT 1 at :88). start_run INSERT at :100. finish_run UPDATE at :113. link_request_to_run UPDATE at :127 (never called). get_settings at :133. is_running at :151.
- scanner/collect/settings.py:15 imports db. get_settings SELECT at :28. ensure_sources INSERTs at :49 and :53. update_setting UPDATE at :113. request_run INSERT at :143. list_runs SELECT at :173 and :183.
- scanner/collect/first_run.py:65-66 (connect and is_running), :69-71 (_queue_run calls request_run at :71). scanner/collect/first_run.py:63 is a lazy `from scanner.pg import db` import inside _run_in_progress() (lines 62-66). The top-level service_client import is at :25.
- scanner/collect/__init__.py:23 imports service_client.
- scanner/collect/sources.py:12-13 imports service_client and mongo. Lazy DB imports at `sources.py:127, 207, 251, 295, 370, 550, 642` (db-touchpoint-review.md, Hazards 13). sources.py:565 is a lazy non-DB import (`from scanner import upstox`, broker client).
- Target for all: the collector calls Fastify routes in Section 6. Its DB login is removed (D5).

### ath_scan.py (host script)

- Lines 59-60, 73-74, 85-86: `from scanner.pg import db` and db.connect() inside functions.
- Also: ath_scan.py:265 (history reads) and :354-355 (factors fetch_corporate_actions and fetch_announcements) reach Postgres through the marketdata defaults (db-touchpoint-review.md, Coverage 2). Target: scanner-job routes (shape TBD).

### graph_sync.py (graph service)

- Line 86: pg.connect() (grep). Lines 88-89: SELECT FROM v_announcement_summary (db-touchpoint-review.md, Wrong citations 10). Target: a graph route group (shape TBD). The compose service is named `graph` (docker-compose.yml:100).

### record_run.py (repo root)

- Line 28: `from scanner.pg import db`. Lines 92-93: migrate import and apply. Target: db removed; migrate moves to the admin job (R7). Also record_snapshots at runs.py:140 and compute_changes at runs.py:254 write stock_snapshots (db-touchpoint-review.md, Wrong citations 8).

### Files with no direct import found in the planning grep (checked 2026-11-13)

- conclude.py: no direct import, but it reaches the main DB transitively through a lazy import of scanner/metrics.py at scanner/conclude.py:566 and :588, and scanner/metrics.py imports .pg db at module level (scanner/metrics.py:23). final_report.py, portfolio.py, crosscheck.py: no DB path found in their direct imports or in scanner/workbook.py and scanner/portfolio.py. See Section 8, item 24.
- enrich.py: the review says lines 112, 175, 619, 747 and 754 touch Postgres (db-touchpoint-review.md, Coverage 13). That conflicts with the "no direct import" note. To verify before approval.

### Other review-listed touchpoints (unmapped in the design)

- scripts/pull_upstox_5y.py: default mode writes upstox_pull_log, and load_universe reads company_reference (db-touchpoint-review.md, Coverage 1).
- scanner/coverage.py:120-124 reads feed_coverage with no GET route (Coverage 4).
- scanner/marketdata/postgres_backend.py:136-139 deletes candles and symbol_stats before the network fetch (Hazards 8).
- scanner/isin_resolver.py:109 record() writes isin_history and symbol_alias (Wrong citations 14).
- scanner/metrics.py: _ensure_run_exists (:51-62), flush_pending (scanner/metrics.py:154-197), finalize (scanner/metrics.py:200-250), summarize (:321-) (Wrong citations 11).
- start.ps1:250-270: psql through `docker compose exec -T scanner-postgres` creates the events database owned by the app login (lines 269-270, guarded by NOT EXISTS). It only checks that the app login exists (lines 264-266). It does not set up roles. (Coverage 14)

### Frontend

- ui/app/static/app.js:845-847 (PUT /api/config/{source}, JSON header, no CSRF header) and :863 (POST /api/config/{source}/run, no CSRF header). Also :870 and :913 (GET and PUT /api/secrets). v2 adds X-CSRF-Token to every write.

---

## 5. Compose changes (docker-compose.yml)

Verified line numbers in this pass:

- Remove the POSTGRES_* login values from every env_file load:
  - collector: env_file .env at :135-136. POSTGRES_DSN is set at :141 from ${POSTGRES_DSN_CONTAINER}. Remove both.
  - graph: env_file .env at :104-105 (named NEO4J_URI and NEO4J_AUTH in the comment). The service is named `graph` (:100), not graph-sync. Its DB host values come from the anchor x-scanner-db-env at :25-29 (hosts only, no logins). Remove .env from this service or filter it.
  - ui: env_file .env at :154-155. The anchor at :157 sets hosts only.
  - scanner: env_file .env at :34-35. Loader password file mount at :48 only. Line :40 is the `POSTGRES_LOADER_PASSWORD_FILE` environment variable that names the container path. LLM chat token read-only mount at :50 only. Line :42 is the `LLM_CHAT_TOKEN_FILE` environment variable. A second mount of the same token exists at docker-compose.yml:185 for another service.
  - enrich: env_file .env at :59-60.
  - enrich-timesfm: env_file .env at :73-74 (comment: database logins for reading candles and filings).
  - portfolio: env_file .env at :94.
  - conclude: env_file .env at :122-123 (POSTGRES_* to record LLM calls).
- Only Fastify keeps DB login values.
- Add a Fastify service (R1). Give ui, collector, graph, scanner, enrich, portfolio, conclude, llm-client and any Telegram poller only the Fastify base URL and their own token file.
- Remove the ui master key mount at :164 and APP_MASTER_KEY_FILE at :158. The master key mounts only into Fastify.
- The ui service publishes 127.0.0.1:8080:8080 (:171) with the comment "loopback only: the UI has no login". That comment is wrong after R3 and must change.
- Note: .env contents were NOT read. Compose reads .env for variable substitution, and collector line :141 uses ${POSTGRES_DSN_CONTAINER}. Whether .env defines POSTGRES_DSN is unverified. The plan must include an owner step that lists which key names .env holds (names only, never values). See open question 20.
- No Telegram poller service exists in docker-compose.yml (grep found none). See open question 18.

---

## 6. Route table (draft)

Auth values: "session" means the browser cookie from R3. "session + CSRF" also needs X-CSRF-Token on writes. "service token: NAME" means the bearer token for that caller, mapped by R4. "shape TBD" means the request and response shape is not decided.

| Method | Path | Replaces (file:line) | Caller | Auth | Notes |
| --- | --- | --- | --- | --- | --- |
| GET | /api/session | new (R3) | browser via ui | none | Sets the HttpOnly SameSite=Strict cookie and returns the CSRF token. Body shape TBD. |
| GET | /api/runs | ui/app/api.py:74 | browser via ui | session | Fastify has /api/runs/latest (app.ts:133) instead. Shape TBD. |
| GET | /api/runs/{run_id} | ui/app/api.py:87 | browser via ui | session | Shape TBD. |
| GET | /api/runs/{run_id}/results | ui/app/api.py:146 | browser via ui | session | Fastify already serves this path (app.ts:145). Compare shapes first. |
| GET | /api/stocks | ui/app/api.py:583 | browser via ui | session | Shape TBD. |
| GET | /api/stocks/{symbol} | ui/app/api.py:255 | browser via ui | session | Fastify serves /api/stocks/:symbol/candles (app.ts:233), a different path. Shape TBD. |
| GET | /api/cost and /api/cost/{run_id} | ui/app/api.py:291 and :326 | browser via ui | session | Shape TBD. |
| GET | /api/report | ui/app/api.py:348 | browser via ui | session | Shape TBD. |
| GET | /api/config | ui/app/api.py:398 (reads at :402) | browser via ui | session | Collector settings read. Shape TBD. |
| GET | /api/config/{source} | ui/app/api.py:452 (reads at :456) | browser via ui | session | Shape TBD. |
| PUT | /api/config/{source} | ui/app/api.py:487-501 (call at :491) | browser via ui | session + CSRF | D3. Alternative: remove the route (review Decisions D3). Shape TBD. |
| POST | /api/config/{source}/run | ui/app/api.py:503-516 (call at :507) | browser via ui | session + CSRF | D3. Shape TBD. |
| GET | /api/secrets | ui/app/api.py:522-525 | browser via ui | session | File-based secrets status. Location is open question 8. |
| PUT | /api/secrets | ui/app/api.py:527-538 (410 at :536) | browser via ui | session + CSRF | Stays 410. Remove the row when the route is deleted. |
| GET | /internal/secrets/{name} | ui/app/internal_secrets.py:98-116 | llm-client, collector | service token: llm-client (llm_key_ names) or collector (upstox_analytics_token only) | Fastify decrypts (R4). Allowlist per role: internal_secrets.py:41 (collector) and docs/designs/home-events-t4f-design.md:262 (llm_key_). |
| GET | /internal/llm/providers/{provider_id} | ui/app/internal_secrets.py:119-137 (SELECT at :129) | llm-client | service token: llm-client | Shape TBD. Keep the fields llm-client reads (llm_client/registry.py:43-44) (unverified: lines 43-44 hold the get_provider definition and its GET call; the fields are not on these lines). |
| GET | /api/presets | server/src/app.ts:259 | browser via ui | session | Currently unauthenticated. |
| POST | /api/presets | server/src/app.ts:265 | browser via ui | session + CSRF | Currently unauthenticated. Gate it (R3). |
| DELETE | /api/presets/{presetId} | server/src/app.ts:275 (path at :276) | browser via ui | session + CSRF | Currently unauthenticated. Gate it (R3). |
| GET | /api/collector/index-eod/status | server/src/collectorRefresh.ts:80 | browser via ui | session | Existing route. Shape unchanged. |
| POST | /api/collector/index-eod/refresh | server/src/collectorRefresh.ts:95 (insert at :42) | browser via ui | session + CSRF | Existing route. The insert uses ON CONFLICT DO NOTHING with no conflict target (:42). |
| POST | /internal/collector/requests/claim | scanner/collect/scheduler.py:72-93, called from collect.py:146 | collector | service token: collector | Returns lease_token and lease_expires_at (R5). One row or one per source is open (Hazards 2). Shape TBD. |
| POST | /internal/collector/requests/{id}/heartbeat | new (R5) | collector | service token: collector | Extends lease_expires_at. Shape TBD. |
| POST | /internal/collector/runs | scheduler.start_run (scheduler.py:96-106); call site not verified in this pass | collector | service token: collector | Run start. Shape TBD. |
| POST | /internal/collector/runs/{run_id}/finish | scheduler.finish_run (scheduler.py:108-121); call site not verified in this pass | collector; watchdog for killed runs (R11) | service token: collector; watchdog (name TBD) | Status values ok, failed, skipped. A skip with not_before uses this route (R5). Shape TBD. |
| GET | /internal/collector/cooldown/{host} | new; source_cooldown table (requests file :18) | collector | service token: collector | Read before each run and each request. Shape TBD. |
| POST | /internal/collector/cooldown/{host} | new; source_cooldown table | collector | service token: collector | Sets cooldown_until on 403, 429 or block. Resets on success. Shape TBD. |
| GET | /internal/due | new per split spec 4.2 (C2 at collector-split-spec.md:61; Blocker 4 consequences at :62-63); endpoint contract in 4.5a (collector-split-spec.md:109-112) | watchdog (host script) | service token: watchdog (name TBD) | Contract is in split spec 4.5a, which this pass did not read. Shape TBD. |
| POST | /internal/events/batch | server/src/homeEventsRoute.ts:24 (mount per R8) | collector home_filings ingest | service token: role home_events_ingest (homeEventsAuth.ts:15) | Row limit 500 (review Hazards 11). Order per R8 (open question 10). |
| (group, path not chosen) | Postgres read of v_announcement_summary (graph_sync.py:86-89) and graph write via g.sync_announcement_summary(rows) (graph_sync.py:93) | graph | service token: graph (name TBD) | Shape TBD. Path not chosen. |
| (group, path not chosen) | scanner-job DB reads and writes (ath_scan.py, record_run.py, metrics.py, factors, history) | scanner jobs and host scripts | service token per job (open question 16) | Shape TBD. Path not chosen. |

Notes:

- Rows with "(group, path not chosen)" are placeholders for the review's unmapped groups. They are not final route names.
- Fastify GET routes that exist today and have no ui counterpart (for example /api/recent-closes at app.ts:246, /api/index-eod at :291, /api/live/ticks at :358) are not listed here. They stay as they are, with R3 applying to any write.
- Telegram poller: no compose service exists, so no route row is given. See open question 18.

---

## 7. Rollout steps

Acceptance for Python changes: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q` (from the Market-Scanner CLAUDE.md, Section 4).

Acceptance for server changes: server/package.json:11 defines `"test": "vitest run"`. Confirm the exact invocation from server/package.json scripts before step 1. It was not run in this pass.

Each step lists the goal, files, acceptance, and what must not change.

1. Settle the open questions in Section 8 with the user.
   - Goal: each question has an answer recorded in this file.
   - Files: this file only.
   - Acceptance: the Section 8 list shows an answer or an approved recommendation for each item.
   - Must not change: no code, no grants, no compose.

2. Fastify: session and CSRF gate (R3), service token load (R4), gate existing unauthenticated write routes.
   - Files: server/src (new session and token modules; app.ts:265 and :275; collectorRefresh.ts:95); server/src/index.ts (token files at startup).
   - Acceptance: server test command from server/package.json before step 1; a test that a POST without X-CSRF-Token is refused.
   - Must not change: the existing route shapes; the 413 ordering; the home events token check.

3. Fastify: move the ui read and write routes (Section 6); add the ui proxy for /api/*.
   - Files: server/src; ui/app/api.py (proxy only, after the move); ui/app/static/app.js (X-CSRF-Token on writes, at :845-847 and :863).
   - Acceptance: Python test command above (proxy tests); server test command.
   - Must not change: the response shapes the browser reads. Compare the path overlaps listed in R2 first.

4. ui: remove pg, master key and internal secrets routes; llm-client points at Fastify.
   - Files: ui/app/main.py (lines 10, 15-23, 43-44); ui/app/internal_secrets.py (remove); llm_client/registry.py (URL from compose); docker-compose.yml (lines 152-175, 180).
   - Acceptance: Python test command; tests/test_llm_client_registry.py and tests/test_llm_client_refusals.py pass unchanged.
   - Must not change: the llm-client refusal contract (Section 11).

5. Collector: claim with lease, heartbeat, run start and finish, cooldown and due routes; remove the collector DB login.
   - Files: scanner/collect/scheduler.py, settings.py, first_run.py, collect.py, sources.py; docker-compose.yml (collector :135-143); migration for lease columns (number per open question 14).
   - Acceptance: Python test command; a test that a lost claim response is recovered after lease expiry; a test that a skipped request returns to queued.
   - Must not change: migration 049 claim (slices:132) until the number is assigned.

6. Graph, scanner (ath_scan, record_run), and any transitive users: move to Fastify routes; remove their logins.
   - Files: graph_sync.py (:86-89); ath_scan.py (:59-60, :73-74, :85-86, :265, :354-355); record_run.py (:28, :92-93); docker-compose.yml (graph :104-105, scanner :34-40, enrich :59-60, enrich-timesfm :73-74, portfolio :94, conclude :122-123).
   - Acceptance: Python test command; server test command.
   - Must not change: the outputs of each job (CSV, XLSX, run rows) for the same input.

7. Ingest route mounted (R8).
   - Files: server/src/index.ts (checkToken and eventsTx wired); server/src/homeEventsRoute.ts (order per the decision in open question 10).
   - Acceptance: server test command; server/src/homeEventsRoute.test.ts adjusted to the decided order.
   - Must not change: the ingest body validation (homeEventsBatch.ts).

8. Migrations moved to the admin job (R7); migration 048 privilege fix as an owner step. (Stale: 048 is applied, verified 2026-11-13; no 048 owner step remains.)
   - Files: admin job definition (Fastify image); start.ps1 migrate stage (lines 283 and 288 per filings spec :410).
   - Acceptance: Python test command; the owner runs the 048 grant step and records the result in the slices ledger (slices:320). (Stale: 048 is applied, verified 2026-11-13; no 048 owner step remains.)
   - Must not change: migration files on disk and their numbers (Section 11).

9. Compose cleanup (Section 5) and a check that only Fastify holds DB login values.
   - Files: docker-compose.yml (Section 5 list).
   - Acceptance: `docker compose config` shows no POSTGRES_* login values in any service except Fastify; a container env check confirms the same.
   - Must not change: scanner-postgres, scanner-mongo and scanner-neo4j services (:196-245).

---

## 8. Open questions for the user

Each line gives the question and the planner recommendation.

1. Split spec line 14 keeps direct main-DB and Mongo access for the collector, which conflicts with D2. Recommendation: revise split spec line 14 to route through Fastify.
   Answer: recommendation approved.
2. t4f design puts the llm settings routes on a ui FastAPI router at /api/llm (home-events-t4f-design.md:45 M-22, :393 LC3, :417-422), so ui writes llm_provider and key rows. This conflicts with D2 and M-22. Recommendation: move the /api/llm writes to Fastify. Also move llm-client's call to ui (:262) to Fastify.
   Answer: recommendation approved.
3. Lease expiry: run timeout plus 5 minutes. Who reclaims a stale claim? Recommendation: any claim call reclaims rows with lease_expires_at in the past.
   Answer: recommendation approved.
4. Skip handling: re-queue with not_before now plus 15 minutes, or record only? Recommendation: re-queue (split spec :69).
   Answer: recommendation approved.
5. The lease replaces the advisory lock (slices:71). Approve? Recommendation: approve.
   Answer: recommendation approved.
6. Do Neo4j and Mongo go through Fastify (R6)? Recommendation: yes.
   Answer: recommendation approved.
7. Fastify bind address for containers (R1). The comment at server/src/index.ts:39 forbids 0.0.0.0. Recommendation: bind 0.0.0.0 inside the container only, and publish 127.0.0.1 on the host.
   Answer: recommendation approved.
8. Does GET /api/secrets (file-based, ui/app/api.py:522-525) stay in ui or move? Recommendation: move to Fastify, so ui mounts no secret files.
   Answer: recommendation approved.
9. Do browser GET routes under /api also need the session cookie? Today they are unauthenticated (server/src/app.ts:130-357). Recommendation: yes, session required on all /api routes.
   Answer: recommendation approved.
10. Order of checks on POST /internal/events/batch: 413 row limit before auth (homeEventsRoute.ts:7 and test :107-122), or auth first (R8)? Recommendation: auth first. This reverses a documented decision.
   Answer: recommendation approved.
11. Cooldown cap for class other: 1 hour (requests file :18) or 2 hours (split spec :84, which filings spec :7 says governs)? Recommendation: 1 hour, and revise split spec line 84 (labelled "to be tuned").
   Answer: recommendation approved.
12. Filings cron: */5 8-20 (filings spec :278 and :672) or 7,22,37,52 8-20 (split spec :135, :175, :200)? Recommendation: */5 8-20, and correct the split spec lines.
   Answer: recommendation approved.
13. Killed-run finalisation (R11): the watchdog calls the API finish route. The "section 9, Q6" reference in slices:284 has no matching entry. Recommendation: API writes the killed-run row.
   Answer: recommendation approved.
14. Migration numbers: correct split spec line 205 and filings spec line 44 to 049 (R12). Also, the lease columns and not_before need a migration number after 049. Recommendation: approve 049 for S2; assign the lease migration the next free number when S5a is scheduled.
   Answer: recommendation approved.
15. Claim semantics: one row across the whole table (current SQL, scheduler.py:88) or one open request per source (slices:106)? Recommendation: one per source, with a unique partial index, as slices:106 says.
   Answer: recommendation approved.
16. Scanner-jobs token: one shared token or one token per job? Recommendation: one token per job (review Accuracy 24).
   Answer: recommendation approved.
17. Host scripts (ath_scan.py, enrich.py, pull_upstox_5y.py, start.ps1 psql steps): how do they get tokens, and are they callers? Recommendation: host scripts call Fastify with a per-job token file on the host and hold no DB login.
   Answer: recommendation approved.
18. Telegram poller: no compose service exists (docker-compose.yml has none). Design in docs/designs/home-events-news-telegram.md. Where does it run, and does it touch the DB? Recommendation: confirm before approval.
   Answer (checked 2026-11-13): planned new service, not in compose. It runs once per cron as source telegram_links (home-events-news-telegram.md:66). It posts through Fastify and never touches the events database directly (:36). It needs its own service token, separate from telegram_intake_ingest (:37). Recommendation approved.
19. Does ui keep any DB role? Recommendation: none (review Hazards 6).
   Answer: recommendation approved.
20. Which key names does .env hold, and which keys does each service need once its DB logins are removed? Recommendation: owner lists names only; no values are read.
   Answer: recommendation approved.
21. Events database: route it through Fastify and revoke CONNECT from PUBLIC after cutover (home-events-filings-spec.md:412; owner is the app login at :409). Recommendation: route through Fastify, then revoke. Owner and date for the revoke.
   Answer: recommendation approved.
22. company_reference loader grants (MT5): an admin step is needed. The owner and date are unknown (home-events-t4f-design.md:384). Recommendation: owner runs the grant and records the date.
   Answer: recommendation approved.
23. Watchdog token: the watchdog runs on the host (split spec 4.4), not in compose. How does it get its token file? Recommendation: a host token file path outside the repo, named in the watchdog config.
   Answer: recommendation approved.
24. Verify transitive DB access before step 1: conclude.py, final_report.py, portfolio.py, crosscheck.py, and enrich.py (review Coverage 13 conflicts with the planning grep). Recommendation: read those files and record yes or no.
   Answer (checked 2026-11-13): conclude.py reaches the main DB transitively. It lazy-imports scanner/metrics.py at scanner/conclude.py:566 and :588, and scanner/metrics.py imports .pg db at module level (scanner/metrics.py:23). enrich.py reaches Mongo through scanner/docstore.py and Neo4j through scanner/graph.py (enrich.py:440). final_report.py, portfolio.py and crosscheck.py show no DB import in their direct imports (scanner/workbook.py and scanner/portfolio.py were checked; scanner/ath.py was not). Recommendation approved: enrich and conclude move to Fastify in step 6; the other three need no DB change.

Count: 24 open questions.

---

## 9. Carry-overs (separate items, not part of the routing work)

These stay separate from routing and are tracked on their own:

- 054 dev-ledger digest check. Source: planning brief; the migration file is db/migrations/054_llm_provider_store.sql (present on disk).
- LC0 gate. The t4f design lists LC1 at home-events-t4f-design.md:391 and LC3 at :393 as dependent on LC0.
- LC3 to LC7. LC4 is gated on a live Anthropic docs check (planning brief; t4f task list at home-events-t4f-design.md:391-393 is the source for LC1 and LC3).
- 048 privilege fix (InsufficientPrivilege, collector-split-slices.md:320). Owner step. (Stale: 048 is applied, verified 2026-11-13; no 048 owner step remains.)
- MT5 company_reference grant. Owner and date unknown (home-events-t4f-design.md:384).

---

## 10. Unverified (said plainly)

Not verified in this pass:

- Whether a unique index enforces one unclaimed request per source. The comment at server/src/collectorRefresh.ts:6-8 says at most one unclaimed row per source. The insert at :42 uses ON CONFLICT DO NOTHING with no conflict target. No unique index is visible in server/src.
- Fastify bodyLimit ordering versus the 413 check (R8). The default bodyLimit for Fastify 5.12.7 was not checked against the code path.
- Transitive DB access for conclude, final_report, portfolio, crosscheck and enrich was checked on 2026-11-13 (Section 8, item 24). Not checked: scanner/ath.py and any file outside the direct import chains listed there.
- Whether .env defines POSTGRES_DSN (.env was not read; compose line :141 uses POSTGRES_DSN_CONTAINER).
- Whether the Telegram poller exists as code (no compose service; design doc only).
- The split spec's 4.5a due contract (not read).
- Whether ath_scan.py:454 and sources.py:295 (filings) reach the DB (review Coverage 10).

Citation corrections found while writing this file (the brief's numbers that did not match):

- Fastify bind: server/src/index.ts:39-40, not 19-22.
- record_run.py:28 is the db import; :92-93 is the migrate import and apply. Both moves are needed (R7).
- registry.py has no SECRETS_API_URL string; the URL is set in compose (docker-compose.yml:142 and :180).
- first_run.py:63 is a lazy `from scanner.pg import db` import inside _run_in_progress() (lines 62-66). The top-level service_client import is at :25, and DB use is at :65-71.
- t4f design :262 says llm-client calls ui's internal endpoint. The ui-hosted /api/llm conflict is at :45 (M-22), :393 and :417-422.
- collector-split-slices.md:284 cites "section 9, Q6". No Q6 entry exists in that file.
- The brief said the scanner service has no token mount. It mounts the LLM chat token at docker-compose.yml:42 and :50 (review Hazards 4 notes the same).
- The brief gave the 413 check at homeEventsRoute.ts:26-32. The check is at :28-29, and the auth call is at :32.
- The review uses no global finding IDs. Citations here use section and number.

---

## 11. What must not change

- Migration files already on disk and their numbers. Present on disk: 040 to 048, 053 and 054. Numbers 047, 048, 053 and 054 are taken. 049 is claimed by S2 (collector-split-slices.md:132) but is not yet on disk. 050 to 052 are not on disk.
- db/events_migrations/ is not used for main-database work. Its series is separate (home-events-filings-spec.md:44).
- The llm-client refusal contract in tests/test_llm_client_registry.py and tests/test_llm_client_refusals.py (LC2). It stays as written. Other llm-client test files (tests/test_llm_client_auth.py, _freshness, _origin and _validation) also stay unchanged.
- Secrets files, .env, data/secrets.env, secrets/ folder, and any token file. This design names paths only. No file in those locations was read.
- PUT /secrets stays 410 (ui/app/api.py:536; home-events-t4f-design.md:393).
