# Review: home-events-filings-spec.md (six-lens synthesis)

Target: `docs/designs/home-events-filings-spec.md` (draft of 2026-11-10, 299 lines). Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness, structural. Findings are deduplicated and ranked here. (V) means I read the file myself while compiling. All other citations come from the lens reports. Nothing in the spec or any other file was changed.

## 1. Verdict

**NOT READY.** Four blockers, sixteen majors, six nit groups.

Reason: the run model cannot work as written. The collector runner (`collect.py:185-207`) records every run that does not raise as `ok`, and it cannot write `skipped` or a rejected count. So the spec's cooldown can never start, and window skips and cooldown skips reset the failure streak. The spec also defines failure as "every feed failed", which means a blocked exchange (the 403 case the policy exists for) never pauses anything. Runs are sequential, so freshness fails behind long `announcements` runs and the spec sets no run deadline. Finally the spec is not buildable yet: no samples, no field mapping, no function signatures, no per-task acceptance. The DDL applies cleanly and the file:line citations are accurate, so the bones are sound. Fix the run model and the Modify list first. Parsers wait on samples.

## 2. Blockers

### B1. Runner cannot record `skipped` or `rejected` (spec 5.1, 5.3, 4.1 item 2, 5.2)

Merged from: codebase B1+B2, design, comprehension, implementation-readiness B1.

- Evidence: `collect.py:185-196` (V, repo root, not `scanner/collect/`) sets `status = "ok"` unless `run()` raises. `"skipped"` is never written. A returned skip message is stored as an `ok` run. `scanner/collect/scheduler.py:108-120` (V) `finish_run` writes only `rows_fetched`, `rows_new`, dates and message. `collect.py:200-207` (V) reads `fetched`, `new`, `from`, `to`, `message` only. `settings.list_runs` (`settings.py:173`) does not select `rows_rejected`.
- Effect: spec 5.3 says skipped runs are ignored and `ok` ends the streak. Today every window skip and cooldown skip is `ok`, so the streak resets and cooldown can never begin. The new `rows_rejected` column stays 0, and overview 7.4 says stored counts are the only trace of rejected items.
- Fix: add a runner contract to the spec. The run result may carry `status` (`ok`, `failed`, `skipped`; default `ok`) and `rejected` (default 0). `collect.py` passes both to `scheduler.finish_run(..., rows_rejected=0)`. `list_runs` selects the column. List `collect.py`, `scheduler.finish_run` and `settings.list_runs` as Modify, and name the existing tests that must still pass.

### B2. "Failed only when every feed failed" defeats the 403 policy (spec 5.3)

Merged from: design, comprehension, implementation-readiness B5.

- Evidence: spec 5.3 says a partial failure is `ok`. NSE and BSE block independently, so an NSE block alone never counts as a failure and never reaches cooldown. Overview 7.3 wants backoff when blocked.
- Fix: make it an explicit spec choice, stated as a choice. Either per-exchange failure accounting (streak per exchange, so one exchange can pause while the other runs), or a global rule with the acceptance of the gap written down. Say how the streak is read (new column, or parse `message`). The dashboard must not parse free text.

### B3. No run deadline, and head-of-line blocking (spec 5.1, 5.4, D2)

Merged from: design, codebase M4, comprehension, implementation-readiness. The codebase lens rated this a major. I rank it a blocker because a 5-minute freshness is the stated goal (overview 8.2 item 10).

- Evidence: sources run one after another in one process, so there is no overlap to lock against. The real problem is blocking. `Announcements` walks all symbols with a 3 s gap (`factors_postgres.py:28`), and `candles_eod` is similar, so `home_filings` cannot meet 5 minutes while they run. In the other direction, a `home_filings` run can block everything. The worst case is large: 14 feeds, a 20 s timeout and 30 s plus 60 s backoffs per feed is many minutes. The spec's "70 to 112 seconds" only counts the happy path.
- Fix: reframe D2 as "run isolation", not "lock". Set a run deadline of about 240 s that stops the feed loop and returns what was done. Decide thread, process or separate service. State whether retries get the random gap. Drop the shared-lock recommendation, because it solves a problem that does not exist.

### B4. Spec is not buildable yet (spec 3.1, 6, 8, 10)

Merged from: implementation-readiness B2+B3, design.

- No samples: the 14 parsers, URLs, tag mapping, ids, date formats and `value_cr` / `pct_shares` extraction are unwritten. The spec says so itself. `data/` is git-ignored.
- No signatures for any module. Suggested set: `Feed` dataclass (`feed_code`, `exchange`, `url`, `event_type`, `feed_tier`, `match`, `flagged`); `FEEDS` tuple; `parse(feed_code, body) -> list[dict]`; `match_row(feed, item) -> (keep, match_basis)`; `dedupe_key(...)`; `in_window(now)`; `cooldown_minutes(n, first, cap)`; `next_allowed(runs, now, ...)`; `insert_events(conn, rows) -> int`; `purge(conn, now, days) -> int`; `load_universe`; `load_bse_map`; `refresh_bse_map`.
- No per-task acceptance command, task order, or "must not change" list.
- Fix: add the signatures and a per-feed mapping table skeleton. Suggested task order: 047 SQL, `feeds.py`, pure modules, `store.py`, runner change, parsers, `HomeFilings` plus `SOURCES` plus settings keys. Parsers are the only part that waits on samples (see section 6).

## 3. Majors

**M1. Window gating on minute 00 is fragile (spec 5.2).** The loop sleeps 60 s and runs sources in sequence (`collect.py:119,173,223`), and `due_sources` fires once per slot (`scheduler.py:63`), so a busy loop can skip the :00 tick for the whole hour. The cron runs in Asia/Kolkata (`scheduler.py:31`). Fix: gate on "newest non-skipped run is at least 55 minutes old", and define hourly as the first tick at or after :00. Also settle: 08:00 and 15:30 inclusivity, results that land after 15:30 IST, and about 288 mostly-skipped `collector_runs` rows a day (decide whether to accept the table churn).

**M2. Cooldown mechanics unspecified (spec 5.3).** Give the formula `next_allowed = newest_failed.finished_at + min(first * 2^(n-1), cap)`, a worked example, and the SQL. Say what happens to stale `running` rows (a crash leaves one). Say what "end of pause" means for the dashboard.

**M3. Grants and roles (spec 4.1 last block).** The spec grants DELETE, INSERT and UPDATE to `market_scanner_app`, the Fastify read role. Migration 043 (V) says the app role "never inserts or updates" `collector_runs`. The only DELETE grant in the recent migrations is `040_scan_presets.sql:14` (V), a table the app itself writes. 042, 045 and 046 give the app role INSERT, again on app-written tables. The collector role is never named (`POSTGRES_DSN_CONTAINER`, `docker-compose.yml:127`). Fix: name the collector role and grant it the writes. Give the app role SELECT only on `home_events` and `bse_scrip_map`. Remove the duplicate `GRANT SELECT ON collector_runs` line (see nits).

**M4. Down step is incomplete (spec 6, last row).** FKs run `collector_runs.source` and `collector_requests.source` to `collector_settings` (`001:100,115`), and `collector_settings.source` to `collector_sources` (`039:16-18`). The down script must delete runs and requests rows first, then the settings and sources rows. It must also run `DELETE FROM schema_migrations WHERE filename='047_home_events.sql'`, as 045 and 046 do. Write the full SQL in FK order.

**M5. Modify list is incomplete (spec 2, 6, 7).** Missing files: `collect.py` and `scheduler.finish_run` (B1); `settings._valid_param_keys` (`settings.py:195-207`, V), which has no `home_filings` entry, so `update_setting` rejects every config key (`settings.py:91-95`, V); `settings.list_runs`; and `tests/test_collect_sources.py:172-175` (V), which asserts the exact `SOURCES` key set and will fail once `home_filings` is added. Add `load_config` with fallback rules for missing keys.

**M6. `mcap_cr` has no source (spec 4.1 note).** `scanner/fundamentals.py:38` is a Screener field map feeding a Mongo-backed docstore. Postgres `fund_snapshot` (027) has only `key_ratios jsonb` and `fetched_at` and is marked NOT APPLIED. No `mcap_cr` column exists anywhere, and the query is unspecified. Fix: name the source and query, or defer `mcap_cr` and `mcap_as_of` (see Z3).

**M7. Dedupe key is weak (spec 4.2).** Generic links, amended filings (same link, new date) and the same filing in two feeds give wrong merges or splits. Spec says cross-feed merging is out of scope, but amended filings need a rule. Fix: define the hash inputs per feed type once samples exist, and define behavior for amendments.

**M8. Ingest completeness (spec 4.2, 5.5).** No ingest floor, so a bogus old date is inserted, then purged, then re-ingested every run. Unparseable or future dates have no rule. Feed depth is unknown: if a feed returns only the latest N items, a 180-minute cooldown or an hourly off-hours schedule can drop items silently. Purge cadence and transaction are unspecified, and purge must run only when at least one feed succeeded. Fix: add a date floor (reject older than the retention limit), a future-date rule, a per-feed depth check against samples, and purge-after-success.

**M9. Request policy and session reuse (spec 2, 5.4).** `_nse_session` (`factors_postgres.py:88`) is private, returns a bare `Session` with no headers, and its UA at `factors_postgres.py:21-25` has a JSON-only Accept. `Announcements` uses its own bare `requests.Session` (`sources.py:214`). The spec says "reuse" without saying how. Missing: cookie warm-up, BSE session, 429 versus 403 handling (a 429 is a rate limit, a 403 may be a block), retry rules for 404, other 4xx, 5xx and timeouts, a wall-clock cap, and testability (injectable sleep, rng, now, fetch). The design lens also flags that reusing a browser-spoofing session and retrying on 403 needs a short terms-of-use risk note. Fix: add a request-policy table, make the session a public helper, and add the risk note.

**M10. Universe filtering at ingest is irreversible (spec 1, 4.3, D3).** Events for non-universe scrips are dropped for good. The universe definitions differ (`symbol_sector` with 751 ISIN rows versus index constituents). `isin_resolver` handles NSE only. Renames need `symbol_alias` / `isin_history` (`isin_resolver.py:154-160`). Fix: give the universe SQL (`symbol_sector WHERE isin IS NOT NULL`, strip and upper), state the company-name source, and note the loss on a universe change. D3 stays a user call.

**M11. `bse_scrip_map` is unbuildable (spec 4.3).** URL unverified, field mapping and filters unnamed, no rule for an empty download, and no DELETE grant so delisted scrips never leave. Fix: disable BSE feeds until the map is non-empty, specify fields and filters, add an empty-download rule and a removal rule. Or defer BSE (Z2).

**M12. Match semantics and feed flags (spec 3, 4.1, D4).** `matches_orderbook` returns `(matched, by_category)`, where `by_category` is a boolean, but the DDL uses `'category'` and `'attachment'`. State the mapping: `by_category` true gives `'category'`, else `'attachment'`. XML feeds without attachment text may have near-zero recall, and `desc` can be empty. `bse:notices` is `direct`, so it would store the board-meeting notices that must be excluded. Fix: add a `flagged` field to `Feed`, and default `enabled_feeds` to exclude `bse:notices` and the three shareholding feeds until their tiers are confirmed. The line "store only High-Priority and Catalyst" (spec 1) is a tautology, since all 14 feeds are already in those tiers. Drop it or state the real filter.

**M13. Trading-day calendar (spec 5.2, D6).** Python has weekday-only checks (`sources.py:90-92`, `512-514`). The UI has `EXCHANGE_HOLIDAYS_2026` in `ui-v2/src/lib/marketSession.ts:25-51`, unchecked by its own comment. Overview 8.2 item 7 assigns the calendar to the macro doc, so the spec's interim weekends-only rule deviates from the overview. Fix: cite overview 8.2 item 7, say the interim rule is a stopgap, and say which module owns the calendar once it exists.

**M14. Event-type enum and tier language (spec 3, 4.1).** Overview 7.1 lists rating changes and joint ventures, which the CHECK enum lacks, and the spec splits governance from regulatory. The tier claim is imprecise: overview 7.1 already lists event types in tiers 1 and 2, and what is missing is the tier 1 / tier 2 split. "Feed tier" versus "event tier" is not defined inline. Adding enum values later costs a migration. Fix: reconcile with overview 7.1 now, and define the two tiers in one sentence.

**M15. Proposals read as facts; parent docs stale.** Sections 1, 2, 4.3 and 5.5 state proposals as facts while section 9 says "none is decided". Several proposals have no D-number: the 20 s timeout, 30/60 s backoff, `bse_map_refresh_days`, the weekend-only fallback, the default tiers, and the precision and recall targets. D2 and D6 each bundle two decisions. D1 could add a JSON feed with no `feed_code`, changing the "14" count. Parent docs are stale against this spec: `home-events-filings.md` lines 105-113 ("Items still missing") and overview 8.1 item 4 and 8.2 item 11. Fix: add a legend (decided, proposed, open), number every proposal, split D2 and D6, and update the parent docs in the same change.

**M16. Test plan does not match the module plan (spec 6, 8).** There is a `test_home_events_window.py` but no window module in section 6. Counts do not add up. No tests exist for 429/403 backoff, the timeout, `dry_run` or `rows_rejected`. Parser tests skip when the git-ignored sample is absent (green with zero coverage). The store fixture is `tests/pgschema.py` (V by lens: `pgschema.create(cls)`, `SkipTest` without Postgres, runs `migrate.apply()`), which the spec leaves as "confirm". The 30-row labelled set cannot prove precision 0.85 or recall 0.90, its negatives are undefined, and the targets are borrowed from overview 6.4 (which belongs to the LLM filter, not the order-win rule). Test cases have no literal inputs and outputs. Fix: commit trimmed fixtures under `tests/fixtures/home_events/` (needs the user's licence call), make a missing fixture fail not skip, add a window module or drop the file, and align counts.

## 4. Nits

1. **Dedupe and DDL syntax.** `sha256` needs `.hexdigest()`. The `<exchange>` prefix is redundant with `nse:` / `bse:` in `feed_code`. Use UTC `isoformat`. Delete the duplicate `GRANT SELECT ON collector_runs` (043 already grants it, and GRANT is idempotent, so the "remove if the runner rejects it" note is wrong; 040 line 13 says the same, V). The purge test at exactly 1095 days is non-deterministic: pass a fixed `now`. "1095 days" versus "3 years" ignores leap days, and overview 7.1 ("kept long term") sits uneasily with 7.4 (purge).
2. **Code facts to correct.** `_skip` is `IndexEOD._skip`, a staticmethod (`sources.py:526-528`), not on `Source`. `_redact` (`mongo.py:135-137`) masks only mongo URI passwords, so the spec's `_redact` sentence is unclear for HTTP errors. Spec 5.1 step 1 (`dry_run` returns `plan()`) is dead: `collect.py:186-189` (V) calls `plan()` itself and calls `run(params, now)` without `dry_run`. Dry run still writes a `collector_runs` row (`collect.py:182`, V; start_run before the dry-run branch). `plan()` should be pure (no network, DB or sleep), and its return shape is unstated. `announcements` PK is `(isin, an_dt, desc)` with date only (`010:43`), so the D2 note on overlap is loose.
3. **Migration ordering and acceptance.** If the collector image starts before 047 runs, `ensure_sources` inserts a manual `'0 0 1 1 *'` placeholder and `DO NOTHING` keeps it (`settings.py:35`); `start.ps1:238,361` migrates first, so say that. The runner exists: `python -m scanner.pg.migrate` and `--status` (each file in one transaction, `migrate.py:48-50`). Give these as acceptance steps. Check that 047 does not collide with the fundamentals-tables migration number (047 is free in the repo today).
4. **Header and cross-references.** The header does not match the sibling docs (Status, Owner, Screen, Overview lines). The feed-URL cross-reference is wrong: the URLs are in overview 5.1, not the filings doc. "Overview 6.4" is the LLM filter's test, not the order-win rule's. Stale cross refs elsewhere. Undefined terms: "six-lens pass", `plan_add`, "builder", "opt-in sample", "from here". The "confirm from sample" label is overloaded (URL, mapping, tier, cookie): use distinct tags.
5. **Field naming.** `symbol_or_scrip` (section 3.1) versus `symbol` (DDL). `company`, `exchange`, `feed_code` and `isin` have no stated source in the parser dict. State the `Asia/Kolkata` conversion mechanism for `published_at`.
6. **Input validation edge cases.** Empty feed, HTTP 200 with an HTML page, malformed XML, missing required fields, symbol normalization. Per-batch duplicates (same key twice in one insert). Transaction boundary per feed, `rows_new` via cursor `rowcount`, `fetched` as parsed items before matching.

## 5. Zoom-out cuts and build order: decisions for the user (not applied)

These are scope choices, not correctness findings. None is needed to fix B1 to B4, but several would dissolve findings.

**Build order proposal (add to spec section 10 if accepted):**
1. Runner contract change (B1) with tests.
2. Slim migration 047 and its down step.
3. Pure modules (window, cooldown, dedupe, throttle) with tests.
4. One-feed NSE vertical slice, end to end, on a feed whose tier is decided and whose sample is captured.
5. Remaining NSE feeds, one at a time, as samples arrive.
6. BSE feeds and `bse_scrip_map`.
7. Purge and any grants beyond SELECT.

**Cut proposals (each is yours to accept or reject):**

| ID | Proposal | What it would dissolve | Tension to know about |
|---|---|---|---|
| Z1 | Decide D1 with one real request first | D1 transport risk, the "14 feeds" uncertainty | Needs a network path NSE accepts |
| Z2 | Defer BSE and `bse_scrip_map` | M11, much of M12, BSE order-win recall | Halves feed coverage at launch |
| Z3 | Drop `value_cr`, `pct_shares`, `mcap_cr`, `mcap_as_of` columns | M6 | Spec stores raw values so thresholds can change without re-ingest (overview 8.2 item 6); dropping them means a later migration plus backfill |
| Z4 | Drop `rows_rejected` | Half of B1 (the status part stays) | Overview 7.4 says stored counts are the only trace of rejected items; this needs an overview change |
| Z5 | Defer purge, the DELETE grant and D5 | Part of M3, M8 purge items | Table grows until purge exists; 3-year retention is far off |
| Z6 | One module instead of six | Mapping mismatch in M16 | Pure functions get harder to test in isolation |
| Z7 | Weekday-hours cron such as `*/5 8-15 * * 1-5` | M1, 288 skip rows a day | Loses hourly off-hours ingest and results after 15:30 IST (M1) |
| Z8 | Abort on first 403 or 429, let cooldown handle it | Backoff and retry complexity in M9 | Interacts with B2: only safe with per-exchange accounting |
| Z9 | Drop most of the 9 config keys | M5 key validation work | Fewer knobs to tune live |
| Z10 | Ingest only feeds whose tier is decided (about 10 of 14) | Flag handling in M12 | Shareholding and `Related_Party_Trans` wait |
| Z11 | Drop `exchange`, `feed_tier` and the second index | Redundancy (exchange is derivable from `feed_code`) | `feed_tier` filter at read time needs a join or constant |
| Z12 | Reuse the existing `announcements` store for the order-win feed | D2, parts of M7 | Reverses the D2 recommendation; `announcements` PK is date-only |
| Z13 | Commit fixtures instead of skipping tests when samples are absent | M16 zero-coverage skip | Third-party content in the repo: your licence call |

## 6. What is blocked on whom

**Your decisions (D1 to D6):**

| ID | Blocks | Note |
|---|---|---|
| D1 | Only the `nse:Online_announcements` parser and URL, and the "14 feeds" count | Run one real request first (Z1) |
| D2 | Run-isolation design (B3) | Reframe from "lock" to run deadline plus thread/process; split the bundled second question |
| D3 | `store.py` universe filter | Recommended default is usable; irreversibility noted in M10 |
| D4 | `match.py` for XML feeds | Recommended default is usable; accept the recall loss or limit order-win |
| D5 | Nothing at build start | Purge can follow (Z5) |
| D6 | Tier list blocks only the event-to-tier constant (not the build). Calendar blocks the window module | An interim weekday-only rule is possible but deviates from overview 8.2 item 7 |

New decisions this review adds: per-exchange or global cooldown (B2); run deadline and process model (B3); licence for committed fixtures (M16, Z13); ingest date floor (M8); the Z1 to Z13 choices in section 5.

**Captured samples block:** all 14 parsers, feed URLs and BSE casing, whether RSS hosts need the NSE cookie, which feeds supply an id (dedupe), `bse:notices` mapping, `value_cr` / `pct_shares` extraction, the BSE instrument master URL, feed depth.

**Labelled set blocks:** acceptance of the order-win precision and recall only.

**Not blocked on either once the spec is fixed:** runner change, slim 047, window, cooldown, dedupe and throttle pure modules, and DB store tests.

## 7. Path to READY (ordered)

1. Decide the failure policy (per-exchange or global) and the run deadline and process model. Write both into spec 5.3 and 5.4 (B2, B3).
2. Add the runner contract and the full Modify list: `collect.py`, `scheduler.finish_run`, `settings.list_runs`, `settings._valid_param_keys`, `tests/test_collect_sources.py` (B1, M5).
3. Rewrite window and cooldown: elapsed-time gating, formula, worked example, SQL, stale `running` rows, boundaries, calendar stopgap (M1, M2, M13).
4. Fix the DDL and down step: grants and collector role, FK-order down SQL, `mcap_cr`, enum, dedupe, ingest floor, purge rules, duplicate grant (M3, M4, M6, M7, M8, nit 1).
5. Add module signatures, task order, per-task acceptance and a must-not-change list. Align the test plan and module list (B4, M16).
6. Add the decided/proposed/open legend, number all proposals, split D2 and D6, fix cross references and header, update the stale parent docs (M15, M14, nit 4).
7. You answer D1 (after one real request), D2, D6 calendar, and the fixture licence call. Capture samples, commit trimmed fixtures, and fill the per-feed mapping in section 3.1 (B4, M11, M12).
8. Re-run the review on the changed sections. The pure and DB-only tasks can start as soon as steps 1 to 6 are done and approved; parsers start as samples land.
9. You approve the design, then write the `plan_add` tasks.
