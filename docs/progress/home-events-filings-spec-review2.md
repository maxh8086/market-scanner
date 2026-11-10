# Goldfish re-review: home-events-filings-spec.md (revision 2)

Target: `docs/designs/home-events-filings-spec.md` (revision 2, 2026-11-10)
Governing sibling: `docs/designs/collector-split-spec.md` (sections 4.5a, 4.6, 4.7, S1a, S2, S5a)
Earlier review: `docs/progress/home-events-filings-spec-review.md` (NOT READY)
Lenses run, each as a fresh subagent: design, codebase-details, zoom-out, comprehension, implementation-readiness, structural. Read-only; no `.env` or `data/secrets.env` read; spec not edited.

## Verdict: NOT READY (to dispatch)

The direction is sound and B1 to B3 are closed in intent. The spec is still not dispatchable. The task graph has circular or missing dependencies, T2 cites a `start.ps1` location that does not exist, the central function interfaces are named but not defined, and the samples are still absent. Almost all fixes are edits to the document, not redesign. A third pass should be cheap once the Blockers below are fixed.

## 1. Are the earlier blockers and majors closed?

| Earlier item | Status | Residual |
|---|---|---|
| B1 runner cannot record skipped/rejected | Closed on paper | Rests on split S1a, whose text and tests cover `skipped` but not a `run()` result carrying `status` (M1 below). Rejected counts moved into `message` (Z4). |
| B2 "failed only when every feed fails" | Mostly closed | Shared `exchange_cooldown` replaces it. Hole: success reset on the first feed defeats escalating backoff (M2). Per-feed silent failure stays `ok` (M10). |
| B3 no run deadline | Closed in intent | The "bounded by the deadline" claim is not true as written (M7). |
| B4 not buildable | Partly closed | Signatures, per-task acceptance and must-not-change now exist. Interfaces are still undefined (B3 below) and samples are still absent (B4 below). |
| M3, M4, M5, M6, M8, M9, M10, M11, M13, M15 | Closed | Grants, full FK-ordered down step, modify list, `mcap_cr` deferred, floor added, session helper, universe SQL, BSE deferred, calendar dissolved, legend. |
| M12 (default-enable flagged feeds) | Partial | Replaced by "enable all nine, provisional tier". Two unconfirmed feeds ship enabled (Nit 8). |
| M16 test plan | Partial | Synthetic fixtures decided. Counts do not match the listed cases (Minor 9). No throwaway-database fixture exists for server tests (M12). |

## 2. Blockers

**B1. The task graph is broken (section 9, 4.6, 4.7, section 2).** (design, comprehension, readiness, structural, zoom-out)
- T3 owns `to_event_row(feed: Feed, ...)` and its test, but `Feed` and `FEEDS` are created in T4. T3 says "Depends on: none".
- T4's acceptance runs `test_home_events_run`, which includes "events target goes to `post_events`". `post_events` is T6, and T6 depends on T4.
- 4.6 says the batch route enqueues result ISINs into `fundamentals_queue` in the same transaction, and T5's vitest list includes "a results row enqueues once". The table is events migration 002, built in T10, and T10 depends on T5.
- The closing line of section 9 ("T1 to T3, T5 and T6 are not [sample-blocked]") is false: T6 depends on T4, which needs a captured sample.
- T9 lists T4 to T8 only, yet needs split S1a, S1b, S3, S4 and S5a. Section 2's build-order sentence (S5a "first") does not match the Depends column (S5a only on T5).
- Split S7 depends on this spec's queue (T10), and T10 depends on T9. Read with T9's "split S6 to S8 pattern", this is a possible cycle that nobody has resolved.
- Fix: move `Feed`/`FEEDS` into T3 (or `to_event_row` into T4); move `post_events` into T3 and keep only client tests in T6, or have T4 take an injected stub; move migration 002 and the enqueue out of T5 (or build 002 in T5); make T10 depend on T5 only; correct the section 9 sentence; rewrite section 2's build order as one sentence derived from the Depends column.

**B2. T2 is not buildable as written (4.5, section 6, T2).** (codebase, structural, readiness)
- `start.ps1:238` is the only migrate call (`compose run --rm --entrypoint python scanner -m scanner.pg.migrate`). `start.ps1:361` is `compose up -d ui collector`. There is no second migrate location. The Postgres service is `scanner-postgres` (`docker-compose.yml:169`), so that "to verify" can close.
- `--db events` cannot work by editing `migrate.py` alone. `db.connect()` takes no dsn or dbname argument, and `db._check_dsn_agrees` refuses a DSN that disagrees with `POSTGRES_DB`. `scanner/pg/db.py` is missing from section 6 and T2.
- `tests/test_pg_migrate.py` does not exist (only `tests/test_pg_dsn.py`). "Temp directory, no server" is not feasible with the module-level `MIGRATIONS` constant and a `connect()` inside `apply()`. 4.5 and section 8 disagree on where the test lives. `pgschema.create` calls `migrate.apply()` with no arguments, so the default must not change.
- `CREATE DATABASE ... OWNER <role>` never names the role. The app login is `POSTGRES_USER` (`env.template:9`, `scanner`); the stage runs as the admin inside the container. On PG 15 or later the app login cannot create tables in `public` of a database it does not own.
- T2 acceptance "`start.ps1` run twice changes nothing" is not a runnable command. The exec/`\gexec` quoting through Windows PowerShell 5.1 has the quote-dropping problem `start.ps1:350` already works around; the exact `Invoke-Docker` argument list is not given.
- Fix: correct the location to 238 only, add the events migrate call after the create stage, add `db.py` with the override and the DSN agree-check bypass, give the refactored `migrate.py` signatures (`files(db)`, `apply(db="main")`), name the owner role, replace the acceptance with a targeted command, split T2 into T2a (python, SQL, tests) and T2b (`start.ps1`, `env.template`).

**B3. Central interfaces are named but not defined (6, 5.1, 5.2, 5.4).** (readiness, comprehension, codebase)
- `FetchResult`, `ParseError` and the `cfg` dict are used and never defined. The `cooldown` parameter has no methods; it should be written as a protocol (`active`, `block`, `reset`) so `run_cycle` can be tested without S2.
- `classify_response(status, content_type, body)` cannot express a timeout or connection error, yet section 8 tests a "timeout marker". HTML-200 detection has no predicate. 3xx, 401, 408, empty 200 and non-XML text are unmapped. "200 XML that does not parse" is a table row, but the function returns `ok` for it. Add the return value to each row of the 5.2 table, with a literal example per row.
- Retry timing is ambiguous: "backoff 30 s" plus "a random gap before every request including a retry" (does the wait equal 30 s, or 30 s plus the gap?). "If the deadline allows" is undefined; it should be `now + backoff + gap_max + timeout <= deadline_at`.
- `filter_items`: no precedence when an item fails several tests; the floor boundary at "exactly 1095 days" and the future boundary have no stated outcome; the counts keys are not named. The reason vocabulary is inconsistent (`rejected_parse` in 4.0, `parse` in 4.3 and 5.2; `date_parse` and `date_future` are missing from the 5.2 message format). `parse()` "raises ParseError" per feed but also "drops the item and counts it" per item, and has no way to return the drop count. An unparseable date cannot reach `filter_items`, because it takes a `datetime`.
- `run_cycle` has no `base_url`, `token` or universe loader (`load_universe` is not in the signatures). The result keys `fetched`, `new`, `from`, `to` are undefined. `new` is unknowable for the announcements target because `_save_announcements` returns `None`.
- `plan()` returns only `{"message": ...}`. `collect.py:87-88` indexes `result['fetched']` and `result['new']`, so a dry run raises `KeyError`. Return the full shape as the other sources do. The message hard-codes "9 feeds" while `enabled_feeds` is configurable.
- `to_announcement_row` must emit `an_dt` and `sort_date` strings that `_parse_date_str` accepts (ISO, `%d-%b-%Y %H:%M:%S`, `%d-%b-%Y`). A row whose `an_dt` does not parse is skipped silently and uncounted. `isin` must fill `sm_isin`. `to_event_row` serialisation of `published_at` (ISO 8601 with offset) and the `exchange` derivation from the `nse:` prefix are not stated.

**B4. No samples and no per-feed mapping (4.0, T4 slice, T7, T8).** (readiness)
- Acknowledged in the spec, but a 4B model cannot write synthetic fixtures that "reproduce the structure of the real sample" when no sample exists. Feed URLs are unverified. Add an explicit T0 (capture one sample, write the tag-to-key table, URL, date format and id presence into 4.0, hand-check one fixture) and mark T4's parser part, T7 and T8 blocked on it.

**B5. The fundamentals staleness check cannot be built where the spec puts it (4.7 item 2, T10; split 4.2, S5a).** (zoom-out, design)
- The check runs "inside `/internal/due`", which is Fastify. `server/src` has no Mongo access, `fundamentals_age_days` is Mongo-backed (`mongo.py:275`), and `fund_snapshot` is NOT APPLIED. The check would also write the queue from a GET route that has SELECT-only grants (S5a). This is a "To verify" that blocks T10, so it is in scope. Fix both specs together; see M11.

## 3. Majors

**M1. Split S1a does not contain what this spec depends on (section 2, 5.1 step 5).** S1a lists the `execute_source` extraction and a `skipped` write path. Its acceptance tests cover the lock skip, API-down skip and ok-only rule, but none covers a `run()` result carrying `status` in {ok, failed, skipped} that is persisted with counts and message. Without it a block records `ok`. Add the contract and a test to S1a, and state run-once's exit code on `failed` and what the watchdog does with it.

**M2. Success reset on the first feed defeats escalating backoff (5.2, row 1).** Feed 1 succeeds and resets; feed 3 returns 403 and writes a fresh 15-minute cooldown; repeat. The doubling in the split spec never escalates, and the blocking endpoint is probed every cooldown period. Reset only at the end of a run that completed with no block, and add a test: success then block on the 3rd feed, twice in a row, backoff doubles.

**M3. `/internal/due` has no source-to-exchange mapping (split 4.2, S5a, T9).** The split spec says due omits a source whose exchange has an active cooldown, but no field records `home_filings -> nse`. At a 5-minute cadence due would start a container every tick, each writing a `skipped` row. Add an `exchange` field per entry in `collector_services.json` as an S5a requirement and have T9 populate it. Also state what status a mid-run cooldown seen at 5.1 step 4(b) gets.

**M4. Cron `*/5 8-15 * * 1-5` and feed depth (4.1 paragraph, Z7).** The text frames the risk as feed depth. The larger issue is latency: results are filed mostly after 15:30, and the cron stops at 15:55. The highest-value event class (and the fundamentals trigger) lands up to 16 hours late; Friday evening to Monday 08:00 is 64 hours. The split spec runs `filings` and `announcements` until 20:52, so the two specs disagree. It is also about 108 NSE requests per hour all day, far above any current NSE caller, and a block pauses `announcements`, `corporate_actions` and `filings` through the shared cooldown. Holidays cost 96 runs x 9 requests. At 08:00 a burst of results will queue many ISINs at once. Decide the window (for example `8-20`) or add an evening mode, and add a depth-overflow check (a first fetch after a gap that returns all-new items). Confirming feed depth should be a precondition before the T4 slice runs in production. Also consider default-disabling the low-urgency flagged feeds (quarterly feeds polled every 5 minutes add block risk for no benefit).

**M5. Reusing `announcements` for order wins undercuts D4 and has key risks (4.3a).**
- First writer wins. The conflict rule backfills only `seq_id`, `attchmnt_file` and `att_file_size` (`factors.py:513-517`, `factors_postgres.py:213-216`), never `attchmnt_text`. The 5-minute XML feed will usually write first with empty `attchmntText`, and the 30-minute per-symbol collector can never fill it in. D4's "lower recall" becomes permanent per row, not just "lower on those rows". Either allow the upsert to backfill empty text (forbidden today by the must-not-change on `scanner/factors.py`, so decide), or let the XML feed skip when the other collector owns the row.
- Key mismatch. The key is `(isin, an_dt, desc)`. The XML category text must equal the API `desc` exactly, and `an_dt` must follow the same date convention. If not, one announcement becomes two rows and consumes the 3-per-stock cap. Mark this "To verify" and make it a T8 acceptance test.
- Same-day, same-category collapse (010:43, `an_dt` is a `date`) is the headline case for order wins, not an edge case. Say so.
- The new feed writes without recording `feed_coverage` (`factors_postgres.py:335-354`). Harmless, one line.
- If the API is down the whole run is skipped, so the direct-DB feed stops too.
- Zoom-out recommends dropping this feed from the spec (the freshness gain belongs in the split spec's freshness work); that is a scope call for the user.

**M6. Home read path is not workable as stated (1, 3, 4.3a, 4.6).** `matches_orderbook` is Python only; the Home read path is Fastify `GET /api/events`, which cannot call it, and a TypeScript port is a copy. Order wins are in the main database and other events in the events database, so the "3-per-stock cap applied in the server query" cannot be one query; it must be an application-level merge across two pools. The cached-row loader spells the key `attchmntText` while the column is `attchmnt_text` (010:38), and there is no `matched` column. The second pool must be read-capable, not only "read-write, used by 4.6 only" (4.5 item 4), and also serves 4.7 and `/internal/due`. Name who runs the rule and where the merge and cap happen, even if the read path is out of scope. Also, "primary rows" in 4.6 is undefined while `is_primary` is deferred: say "all rows now".

**M7. "Bounded by the deadline" is not true as written (5.1 step 4a, 5.3).** The deadline is checked only before each feed. A feed started at 239 s still gets a gap (up to 8 s), a 20 s timeout and a retry. `post_events` and `save_announcements` have no timeout. The 300 s watchdog value omits the gap. Nothing finalises a `running` row when the watchdog kills the container. State the worst case as deadline + gap_max + timeout + post timeout, give `post_events` a timeout, and say who finalises a killed row.

**M8. Mid-run API or events-database failure is unspecified (5.2 table).** If `POST /internal/events/batch` times out or returns 5xx, the loop keeps fetching and discards the data until the next run, which is only safe if feed depth holds. `GET /api/health` probably does not check the events pool. Add a row: stop the loop, status `failed`, message `api_error`, no cooldown change; make the health check or first post cover the events pool.

**M9. Run status gaps and starvation (5.2, 5.1 step 4).** A deadline hit with zero feeds attempted or succeeded has no status. "Unfetched feeds are picked up by the next tick" is false: every run starts at the first feed, so a persistently slow run never reaches the last feeds, and `nse:Online_announcements` is last. Under slow NSE, 9 x (8 + 20) = 252 s exceeds 240 s. A block on feed 3 also stops all later feeds. Rotate the start feed per run, or make N consecutive deadline cuts a `failed` condition. The 15-minute retry rule is moot at a `*/5` cadence; say so or drop the reference.

**M10. Persistent per-feed failure is invisible (5.2 run status).** A 404, a schema change or a non-block 4xx on one feed leaves the run `ok` with only a `message` that the dashboard does not parse. A withdrawn URL kills a feed for weeks, and parsers are tested only against hand-written fixtures. Mark the run `failed` on a non-transient single-feed failure, or record per-feed last-success.

**M11. Section 4.7 (fundamentals queue, T10) is scope creep and has correctness holes.**
- Overlap. The existing `fundamentals` source already skips fresh symbols via `max_age_days` (`sources.py:388-400`); a daily run is the catch-up. `refetch_only_on_new_result` is only whitelisted in `settings.py:205`; nothing reads it, so the weekly sweep depends on behaviour that does not exist. "Build slot" and the T10 Depends column contradict (4.7 item 4 versus T9).
- Lost update. `ON CONFLICT (isin) DO NOTHING` plus `done` deleting by `isin` loses a second trigger that lands while a refresh is in flight (two result feeds for one ISIN can land at different times). Compare `queued_at` on delete.
- Source lag. A refresh on filing can fetch pre-result data, succeed and clear the row; the next trigger is the staleness check about 100 days away.
- Vocabulary. Queue reason is `result` or `stale`; `/internal/due` reason is `queue` or `stale` (split 4.5a). A "fundamentals token" is used but only `home_events_ingest` is named. The DDL is prose, not a SQL block, with no down file.
- Missing from section 6 and 8: migration 002 and its down file, the `fundamentals` source change to drain the queue (API client, token), Python tests, queue tests.
- Zoom-out's smaller alternative: keep the daily `fundamentals` run, add one read-only `GET /internal/events/results-since`, treat a symbol as stale if a results event is newer than its stored fundamentals time. No queue table, no done endpoint, no enqueue in the batch transaction, no weekly sweep. Recommended: move 4.7 out to its own spec or a split-spec task, which also dissolves B1's T5/T10 contradiction.

**M12. T5 has no test substrate or interface (4.6, 8, T5).** Server tests inject a single-query `QueryFn` into `buildApp(deps)`; there is no throwaway-database fixture in `server/src`, and a transaction cannot go through a single-query function. `AppDeps` must gain an events dependency and a token-check dependency. Body field names, status codes (400, 401, 403, 413), and where the token is read are unstated; there is no Fastify bearer-token pattern in `server/src` (the only `Bearer` hits are outbound Upstox calls). `server/src/index.ts` is modified in the working tree and `kiteToken.ts` is untracked; T5 touches `index.ts`. Split T5 into validation plus SQL builder (in the style of `collectorRefresh.ts`) and route plus auth plus pool.

**M13. "Internal routes are not published" is wrong today (4.6, 4.5 item 4).** `docker-compose.yml` has no Fastify `server` service. Fastify runs on the host, binds `127.0.0.1:8081` and refuses `0.0.0.0` (`server/src/index.ts:20,40-41`), so a collector container cannot reach it. The only existing `/internal/*` route is `GET /internal/secrets/{name}` in the Python `ui`, published on loopback. The split spec 4.5 publishes `server` on `127.0.0.1` with `/api/*` and `/internal/*` on one port, so internal routes are loopback-published and token-gated, not compose-only. T5, T6 and T9 depend on split S3 containerising `server`. State that, remove the "to verify", and consider a second listener port.

**M14. Rollout hazard between T1/T4 and T9 (4.1, section 9).** T1 registers `home_filings` as `scheduled` with a 5-minute cron. After T4 adds `SOURCES["home_filings"]`, the existing `collect.py serve` loop (`collect.py:173-211`) runs it sequentially in-process for up to 240 s, with no API health guard and no `skipped` support, blocking the other sources and recording `ok`. Insert as `mode='manual'` in T1 and flip to `scheduled` in T9, or forbid merging T4 before the S1b/S3 cutover.

**M15. Migration number and T1 (section 2, T1, 4.1).** `NNN` is "next free when its task is written", and T1 depends on nothing. Latest is 046; 047 is free but the split spec's S2 claims it (and S5a's grant migration needs a number). A 4B model cannot arbitrate, and T1 could take 047, violating its own must-not-change. Reserve a number or make T1 depend on the split spec resolving it. T1's acceptance runs against the real database; give a `pgschema` test instead and state that a skip is not a pass.

**M16. T3, T4 sizing for a 4B model (section 9).** T3 bundles `nse_session()`, headers, an unnamed redaction helper, `dedupe_key`, `filter_items`, `classify_response`, two mappers and about 18 tests. T4 bundles `Feed`/`FEEDS`, `fetch_feed`, `run_cycle`, `HomeFilings`, `SOURCES`, `_valid_param_keys`, the SOURCES test, a parser slice and about 11 run tests, and its acceptance never reaches the API or database. Suggested split: T3a (`nse_session`, header dict, `redact_error(text) -> str`), T3b (`dedupe_key`, mappers, `Feed`/`FEEDS`), T3c (`filter_items`, `classify_response`); T4a (`_valid_param_keys`, SOURCES test, buildable now), T4b (`fetch_feed` and `FetchResult`), T4c (`run_cycle` against a fake cooldown), T4d (`HomeFilings` wiring, waits on S1a and S2), T4e (one-feed parser slice, waits on T0). State a tool-call limit per task. T6 only needs a stubbed `http`; specify its interface (`http.post(url, json=, headers=, timeout=)` with `.status_code`, `.json()`), path, 500-row batches, summed counts, and a `RuntimeError` that does not echo the token.

**M17. T9 acceptance cannot run yet (T9, split S3).** No service has `profiles: [collectors]` today (only `laya` has a profile); S3 creates it. "One run-once start" needs S1a. The token mount path is Open and blocks T6 and T9 as well. Add S1a, S1b, S3, S4, S5a to T9's Depends and put `config/collector_runtime.json` (300) into a task. How run-once learns `home_filings` is an events source (API-health check) is undefined in both specs; add a class attribute to T4.

**M18. Role and ownership in the events database (4.1, 4.5).** `market_scanner_app` exists in the live cluster (migrations 023 to 046 grant to it) but no repo file creates it and `env.template:9` names the app login `scanner`. Word the comment as "the app login, `market_scanner_app` in the live cluster" and add a precondition check to T2. `OWNER <role>` makes the `GRANT` redundant if the owner is the app login. D9 "API only" is a convention: `CONNECT` defaults to PUBLIC, so the collector role can connect; consider `REVOKE CONNECT ... FROM PUBLIC`. Also state `--db events` runs the same `_BOOT` (`migrate.py:20-21`) so `schema_migrations` exists before 001, and that `db/events_migrations/` is globbed non-recursively so `down/` never runs. The `scanner` image does `COPY db/ ./db/` (`docker/scanner/Dockerfile:18`), so the image must be rebuilt for the migrate stage to see the new directory.

**M19. Document structure and terms a cold reader trips on (comprehension, structural).**
- Two H2 headings numbered 4 ("Feed registry", "Data model"), with 4.0 under the first and 4.1 to 4.7 under the second. "Section 4" is ambiguous ("the nine rows of section 4"). Lines 15 and 57 cite the feed list as "section 3", which is "Existing code reused". 4.x cannot be renumbered because the split spec cites 4.6 and 4.7, so merge into one "4. Feed registry and data model" or rename the first to "3a".
- "Feed tier" versus "event tier": the text says Home filters by the stored `feed_tier`; D6a says tier 1/2 is a code constant. `high_priority` and `catalyst` are never defined. State which tier Home uses.
- Z-numbers (only Z2 to Z7, Z12 appear) and review ids (B1, B2, M1) are decoded only in the "Cuts" row; "tick", "slot", "first slice" versus "one-feed slice", "events source", S2a and S5b are not glossed.
- Three meanings of "retry" (per-request retry, block stop, split-spec run retry): name them.
- Cooldown ownership: 5.2 says "only reads it, and writes it on a block" but also calls the success reset. Section 2 still says "window and cooldown skips" though no window logic exists. Say: `run_cycle` returns a status dict; `execute_source` writes the run row; `run_cycle` writes only block and success-reset through the injected cooldown.

## 4. Minors

1. `CHECK (exchange IN ('NSE','BSE'))` conflicts with the BSE deferral and the rule at line 73. Use `'NSE'` only or drop the column (derivable from `feed_code`). `source_id` and the `home_events_pub_idx` index are similarly redundant for a table this small.
2. Three enum lists (Python `FEEDS`, SQL CHECKs, the TypeScript validator) have no test tying them together. Today they match by hand check.
3. Completeness test "fails, not skips" will fail at T4 and at every intermediate T7 step, yet T7's acceptance runs it. Enable the assertion at the last T7 step, and add the slice parser test to T4's acceptance.
4. `data/home_samples/<feed_code>.xml` and `tests/fixtures/home_events/<feed_code>.xml` expand to names with a colon, illegal on Windows and an alternate-stream separator on NTFS. Define a mapping (`nse_Financial_Results.xml`).
5. Line 290: `--db main|events` has an unescaped pipe inside a table cell and splits the row. Write `--db {main,events}`.
6. Status block (lines 3 to 7) has no blank lines or list markers and renders as one paragraph.
7. The main down file deletes run history. The 046 precedent carries a "NOT run by the runner. Take a pg_dump first" header; add it. Also state that the code revert must precede the down file, or `ensure_sources` re-inserts the rows. The 045 down file cites `docs/progress/rollback.md`, which does not exist (the "same layout" precedent is otherwise valid).
8. Line 104 says "One table" for the events file while 4.7 adds a second via 002. Say "001 holds one table". `Related_Party_Trans` and `Shareholding_Pattern` ship enabled with an unconfirmed tier.
9. Test counts do not match the enumerations. `test_home_events_pure`: stated 16, listed 18 (4 + 5 + 7 + 2). `test_home_events_run`: stated 10, listed 11. `test_pg_migrate`: stated 3, listed 2 (`--status` unlisted). `homeEvents.test.ts`: stated 6, listed 5. 4.0 requires a parser to handle five cases; section 8 tests three. Section 8 has no row for 4.7 tests. List one name per method.
10. Collapse the reconciler (4.4, D7, T11) to one paragraph; section 9 should hold buildable tasks only.
11. "751 rows with an ISIN" is a snapshot count and not verifiable from the doc; line-number citations (`start.ps1:238`) drift, so prefer function or step names.
12. 4.2: say `dedupe_key` is called only for the `events` target, and that `run_cycle` drops repeated keys before `post_events`. Note that a run that crosses 500 rows commits in separate transactions (fine, idempotent).
13. 5.1: `plan()` message and the `plan()`/`run()` signatures `(params, now=None)` / `(params, now=None, dry_run=False)` should be stated.
14. 5.4: `requests`-side detail: `_redact` in `mongo.py:135-137` masks only a Mongo URI password, so the new helper is correct (confirmed).
15. 4.5 item 5 (backup schedule), "feed depth", and the cooldown cap (2 h versus 3 h) are intentionally open; the cap does not block a task.
16. Migration header in the spec for the filename `schema_migrations.filename` is correct (confirmed).

## 5. Factual claims, verified against the repo

Confirmed:
- `factors.py:468` `_save_announcements` (Postgres path `_save_announcements_pg`, `factors_postgres.py:179-220`); conflict rule backfills only `seq_id`, `attchmnt_file`, `att_file_size` on `(isin, an_dt, "desc")`; `_trim_announcement` at `:433` with exactly the nine key spellings; `matches_orderbook` at `:828-847` reads `desc` and `attchmntText`, returns `(matched, by_category)`.
- `factors_postgres.py:88` `_nse_session` private, returns a bare `Session`, warm-up failure not fatal; `UA` at `:21-25`.
- `sources.py:44` `Source.run`, `:64` `plan()`, `:616` `SOURCES` (7 entries). `settings.py:35` `ensure_sources`; `_valid_param_keys` at `:195-207` returns `valid.get(source, set())`, so any non-empty `home_filings` params are rejected until a key set is added (the `{}` in the registration row is accepted).
- `tests/test_collect_sources.py:171-175` pins the exact set of 7 names; its docstring says "5 feed sources" and needs updating too.
- `collector_settings.source` has no CHECK (013 added, 014 dropped, 041 drops with IF EXISTS); FK to `collector_sources` at `039:16-18`. `collector_runs.source` (`001:100`), `collector_requests.source` (`001:115`), `collector_requests.collector_run` (`001:118`). No other table in `db/` references these four, so the four-DELETE down file in FK order is complete and correct.
- `announcements` PK `(isin, an_dt, "desc")` at `010:43`, `an_dt` is a `date`. 4.1 registration SQL matches `collector_settings` columns (`mode` CHECK allows `scheduled`, `collector_runs.status` allows `skipped`) and the 041 pattern; `ON CONFLICT (source)` is valid on both PKs. Latest migration is 046.
- `tests/pgschema.py` raises `SkipTest` without Postgres and calls `migrate.apply()`. `migrate.py`: single directory, single `schema_migrations` (column `filename`), per-file transaction, `--status`. `collect.py:200-207` reads `fetched, new, from, to, message`; `status` is a local variable.
- `docker-compose.yml:173` `POSTGRES_USER: ${POSTGRES_ADMIN_USER:?...}`; Postgres service is `scanner-postgres` (`:169`); `env.template:9` app login `scanner`, `:11` admin.

Wrong or incomplete:
- `start.ps1:361` is not a migrate location (it is `compose up -d ui collector`); only `:238` migrates.
- "Internal routes listen on the compose network only": wrong today (M13).
- `UA` "JSON-only `Accept`": the real value is `application/json, text/plain, */*`, which already permits XML. The T3 change can still be justified; fix the wording.
- Section 3: `symbol_sector.isin` "not null": the DDL is `isin text` with no NOT NULL (`025:9`); the spec's own query correctly filters `IS NOT NULL`.
- "Home applies `matches_orderbook` when it reads": no reader can call it (M6).
- "Existing `announcements` collector, per symbol, every 30 min": the loop is per symbol with cron `*/30 8-20 * * 1-5` (`001:92`), but the NSE fetch is market-wide month windows tracked in `feed_coverage`.
- Split spec claim "S2, S2a and S5a all claim 047": only S2 claims it; S2a says "taken when written"; S5a needs a migration but names no number (restate; the split spec governs).

## 6. Per-task readiness (4B local model)

| Task | Verdict |
|---|---|
| T1 registration migration and down | Buildable with fixes (name the number, `manual` mode, real acceptance) |
| T2 `--db events`, events SQL, env, `start.ps1` | Blocked (B2); split into T2a and T2b |
| T3 `nse_session`, redaction, pure functions | Buildable with fixes (B1, B3); split into T3a, T3b, T3c |
| T4 registry, `fetch_feed`, `run_cycle`, `HomeFilings` | Blocked (B3, B4, S1a and S2 unbuilt); T4a is buildable now |
| T5 server batch route, auth, pool | Buildable with fixes (M12, B1 enqueue); split in two |
| T6 `post_events` client | Buildable now once the `http` interface is specified; drop the T4 dependency |
| T7 remaining parsers | Blocked on samples (B4) |
| T8 order-win feed to `announcements` | Blocked (B4, M5, B3 `an_dt` format) |
| T9 compose service and services file | Blocked (M17, S1a, S3, S4 unbuilt) |
| T10 fundamentals queue | Blocked (B5, M11) |
| T11 reconciler | Placeholder, its own spec |

## 7. Must change before the user approves

1. Fix the task graph (B1): `Feed`/`FEEDS` into T3, `post_events` into T3 or stubbed in T4, remove the enqueue and migration 002 from T5, correct T9 and T10 Depends, correct the section 9 closing sentence and section 2 build order.
2. Fix T2 (B2): drop `start.ps1:361`, add `scanner/pg/db.py` and refactored `migrate.py` signatures, name the owner role, replace the acceptance, move the migrate test location to one place, split T2.
3. Define the interfaces (B3): `FetchResult`, `ParseError`, a cooldown protocol, the `classify_response` table with literals and a timeout marker, `filter_items` precedence and boundaries, one rejection vocabulary, `run_cycle` wiring and result shape, `plan()` full shape, `an_dt` format for `to_announcement_row`.
4. Add T0, the sample capture and mapping table (B4), and mark T4's parser, T7 and T8 blocked on it.
5. Take 4.7 and T10 out of this spec, or redesign the staleness check so it does not live in Fastify, and fix the enqueue race (B5, M11). Fix the corresponding items in the split spec together.
6. Close the cross-spec gaps: S1a `status` contract (M1), `exchange` per entry in `collector_services.json` (M3), S3 containerising `server` and the "not published" claim (M13).
7. Fix the 403 path: reset the cooldown only at the end of a block-free run (M2), define post-failure and zero-success statuses, rotate the start feed, define the retry formula, state the true worst case (M7 to M10).
8. Decide the cron window and the announcements trade-offs with the user (M4, M5), and name who runs `matches_orderbook` and merges the two stores on the read path (M6).
9. Make T1 `manual` until T9, reserve its migration number (M14, M15).
10. Clean up structure and counts: one "section 4", define the two tiers, define Z and review ids at the legend, fix the section 8 counts, the Windows filename, the table pipe, and the `exchange` CHECK.
