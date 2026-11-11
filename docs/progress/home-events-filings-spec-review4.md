# Home events filings spec: fourth review (revision 4)

Date: 2026-11-11. Subject: `docs/designs/home-events-filings-spec.md` (revision 4).

**Method disclosure.** Six lens results (`egm-design`, `codebase-details`, `zoom-out`, `comprehension`, `implementation-readiness`, `structural`) were supplied as JSON to this compilation. This pass compiled them. It did not re-run any lens, did not read or edit the spec, and did not re-verify the codebase claims, which are reported as each lens found them. The `egm:egm-synthesizer` agent was not spawned and no subagent was used, so this is a single-author compilation, as in review 3. Merged findings take the highest severity among their sources. The `implementation-readiness` lens used "Minor" for nine findings; they are tagged Nit here. The target standard was not named; the `egm-design` and `structural` lenses both used the bundled feature-spec standard.

## Verdict

Not ready for `plan_add`: five Blockers and 28 Majors. Revision 4 is coherent as a build plan (`egm-design`), but four present-tense claims are contradicted by code that the `codebase-details` lens reports as landed (T2a, T4a, T5b, and a `rollback.md` citation), and `run_cycle`'s signature cannot honour its own step order. The highest-risk items are the cooldown and run-status paths (M1, M2, M4, M7), which can pause every NSE source or lose events without a signal. The header records approval on 2026-11-11; the Blockers and the stale status lines should be settled, and the approval confirmed against this review, before any task is written.

## Counts

| Lens | Raw findings | Blocker | Major | Nit (incl. "Minor") |
|---|---|---|---|---|
| `egm-design` | 12 | 0 | 9 | 3 |
| `codebase-details` | 11 | 4 | 3 | 4 |
| `zoom-out` | 11 | 0 | 2 | 9 |
| `comprehension` | 20 | 0 | 4 | 16 |
| `implementation-readiness` | 31 | 1 | 18 | 12 (9 were "Minor") |
| `structural` | 12 | 0 | 4 | 8 |
| **Total raw** | **97** | **5** | **40** | **52** |
| **After dedup** | **54 merged** | **5** | **28** | **21** |

Each merged finding lists every lens that raised it. Cross-references (for example, "see M27") point to the merged finding that holds the related text.

## Blockers

**B1. Section 3 says home_filings params are rejected until T4a.** [Blocker] Lenses: `codebase-details` (codebase-details-1).
Where: section 3, "Source registration" row.
Finding: `_valid_param_keys` in `scanner/collect/settings.py` (lines 195–206) already defines the home_filings key set, and `tests/test_collect_settings_sources.py:68` exercises it. The lens reports T4a as landed, so the present-tense statement is false.
Fix: rewrite the row as landed (T4a done, key set at settings.py:206); keep only the remaining work in future tense.

**B2. Sections 3 and 4.5 describe the pre-T2a migration runner.** [Blocker] Lenses: `codebase-details` (codebase-details-2).
Where: section 3, "Migration runner" row (line 57); 4.5 "What the repo does today".
Finding: the lens reports `scanner/pg/migrate.py` with MIGRATION_DIRS, target-aware files/status/apply, and `--db`; `scanner/pg/db.py` with `dsn(dbname)` and `connect(dbname, **kw)`; and `tests/pgschema.py` create taking a target. The spec describes the state before T2a.
Fix: restate both as the post-T2a runner; keep T2b (start.ps1 stages) as the remaining work.

**B3. Section 3 says `docs/progress/rollback.md` does not exist.** [Blocker] Lenses: `codebase-details` (codebase-details-3).
Where: section 3, "Down-step precedent" row (line 58).
Finding: the file exists in the worktree and in the primary checkout, so the citation resolves and the assertion is false.
Fix: delete the "which does not exist" clause.

**B4. Section 4.6 says no Fastify bearer-token pattern exists.** [Blocker] Lenses: `codebase-details` (codebase-details-4).
Where: 4.6 Auth (line 238); section 6 `AppDeps` description.
Finding: the lens reports `server/src/homeEventsAuth.ts` exporting `checkIngestToken` (ok, 401, 403), `server/src/app.ts` AppDeps carrying `checkToken` and `eventsTx` and wiring `registerHomeEventsRoutes` when both are present, and `server/src/live/upstoxFeed.ts:102` as the only outbound Bearer use. T5b is reported as landed, so "T5b adds one" is stale.
Fix: rewrite the 4.6 auth paragraph as the landed inbound check; keep only the token location and EVENTS_API_BASE_URL as open.

**B5. `run_cycle`'s signature cannot honour its required step order.** [Blocker] Lenses: `implementation-readiness` (implementation-readiness-1).
Where: 5.1 step 3 (line 263); 5.3 (line 299); section 6 `run_cycle` signature (lines 363–364); `load_universe` (line 357).
Finding: step 3 requires `deadline_at` to be set before `load_universe()`, so the universe query counts against the deadline. `run_cycle` takes `universe: dict` and no connection, while `load_universe(conn)` needs one, so the spec's own contract cannot run the load inside the run.
Fix: add `conn` to `run_cycle` and call `load_universe(conn)` after `deadline_at` is set, or move both steps into `HomeFilings` and pass the deadline in. State which one is built.

## Majors

**M1. A 403 can write the exchange-wide cooldown, and the single-feed 403 is recorded as both open and decided.** [Major] Lenses: `egm-design` (design-1), `comprehension` (comprehension-1).
Where: 5.2 table (line 278); 5.2 paragraph (line 293); 5.4 Session (line 306); section 10 (line 464).
Finding: a failed warm-up is logged and not fatal (line 306), and whether the archive host needs the cookie is still to verify. If it does, later feed requests can return 403, and line 278 writes that as an exchange-wide block. Line 293 calls the single-feed 403 "open", while line 464 records it as decided (stays `blocked`). Line 293 also says NSE "often answers a wrong path with 403" with no source.
Fix: classify a 403 that follows a failed warm-up as a run-level failure `warmup_failed`, with no cooldown write. Count a block only for a 403 after a successful warm-up. Replace the line 293 sentence with "Decided 2026-11-10: a 403 on one feed stays blocked (section 10)", and drop the unsourced claim.

**M2. The end-of-run cooldown reset is unconditional, and the cooldown and backoff are undefined.** [Major] Lenses: `egm-design` (design-2), `implementation-readiness` (implementation-readiness-5), `comprehension` (comprehension-3).
Where: 5.1 steps 4(b) and 5 (lines 264–265); Cooldown protocol (line 348); 5.2 (line 304); section 2 (line 39); section 10 (line 466).
Finding: the reset runs after the last mid-run cooldown check, so it can erase a block another container writes during this run, and `reset(exchange)` takes no timestamp or condition. The reset also restarts the backoff. Step 5 allows a reset after at least one feed "succeeded", but "succeeded" is undefined, and the test `post_failure_stops_loop_api_error_no_cooldown_change` forbids a reset after a post failure. The spec never says what a block sets, how long it lasts, how it escalates, or what `reset` clears. "Backoff" names both this escalation and the 30 s request-retry wait, and the cap is open (2 h in the split spec, 3 h in overview 7.3).
Fix: make the reset conditional on the cooldown having been set before this run started, or re-read it after the final feed and before the reset. Define "succeeded" as fetched and parsed with no post error. Add a 5.2 paragraph on what a block sets, how long it lasts, how it escalates, and what reset clears. Rename the 30 s wait so it does not share the word "backoff".

**M3. The warm-up and the universe load sit outside the run order, the deadline and the timeouts.** [Major] Lenses: `egm-design` (design-7), `implementation-readiness` (implementation-readiness-17).
Where: 5.1 run order (lines 261–266); 5.3 worst case (line 299); section 2 S4 row (line 41); 5.4 Session (line 306); section 3 (line 52).
Finding: the 285 s worst case (`run_deadline_s` plus about three `post_timeout_s`) and the 330 s watchdog both omit the warm-up. The universe load runs inside the deadline clock but has no timeout of its own. Step 3 has no warm-up step, the warm-up has no timeout, and its owner and timing (once per run, per container, or per feed) are unstated. Its User-Agent and header set are not given. Section 3 says existing code is reused, while T3a is told to add a header dict.
Fix: add the warm-up and the universe load to step 3 with explicit timeouts, and restate the worst case and watchdog margin including them. Name the warm-up owner and timing relative to `deadline_at`, the exact User-Agent and header set, and whether a new dict is needed.

**M4. Run status has gaps: an all-items-dropped feed reports ok forever, and several failures have no status row.** [Major] Lenses: `egm-design` (design-3), `implementation-readiness` (implementation-readiness-6, implementation-readiness-26).
Where: 5.2 table (line 281); run status (lines 284, 288–291, 295).
Finding: a non-empty body whose items are all dropped by parse returns 200 and is counted as ok with new=0 indefinitely. Line 284 forbids this silent outcome for invalid rows. A zero universe match is normal and must stay ok. There are no status rows for a `load_universe` failure, a cooldown read failure, an empty universe, or an unexpected exception; an empty universe would produce ok runs with new=0. The rule "invalid > 0 ends the run failed" does not say whether the feed loop stops at the first batch with invalid > 0 or keeps posting.
Fix: mark a feed failed when a non-empty body yields items and every item is dropped by parse. Fail the run before any request when the loaded universe is empty. Add a failed status row, with a named message, for each other case. State whether the loop stops at the first batch with invalid > 0.

**M5. The NSE request budget covers only home_filings and omits warm-ups, retries and other NSE containers.** [Major] Lenses: `egm-design` (design-5).
Where: 4.1 (line 122); 5.3 (line 299); 5.4 (line 307).
Finding: the "about 96 requests an hour" figure is for home_filings alone. The cooldown reacts only after a block. One request in flight per container gives no cap on aggregate NSE load when containers start on the same tick. T9 starts a new container each tick, so a session warm-up probably runs each tick (the lens flags this as inferred).
Fix: state the total NSE requests per hour across all containers, including warm-ups and retries. Add a per-exchange rate budget (for example a shared limit in the `exchange_cooldown` table) so containers on one tick cannot stack requests.

**M6. The two quarterly feeds take a quarter of each tick's NSE requests with the most block exposure, and have no per-feed cadence.** [Major] Lenses: `egm-design` (design-6).
Where: 4.0 (line 83); section 7 `enabled_feeds` (line 382); section 10 (line 464).
Finding: the only control is the all-or-nothing `enabled_feeds` list. Cadence is open, with every 5 minutes as the default. The user's 2026-11-10 answer records "no decision yet".
Fix: add a per-feed interval parameter (for example, every 12 ticks for the two quarterly feeds) to the registry and to section 7, and record a default.

**M7. Nothing checks that a fetch still reaches the newest stored item, and feed depth is stated as fact in 4.3 but listed as unverified in 4.1.** [Major] Lenses: `egm-design` (design-4), `comprehension` (comprehension-7).
Where: 4.1 (line 122); 4.3 (line 189); 5.2 post failure (line 286).
Finding: data is dropped until the next tick, which is safe only if feed depth holds. The overnight gap runs from 20:55 to 08:00 IST. Review 2 M4 proposed a depth-overflow check; revision 4 neither applies it nor lists it as deferred. Line 189 says "Each feed returns only its recent items" as fact, while 4.1 says depth is to verify.
Fix: after each successful post, store the newest `published_at` per feed. Fail the run as `gap:<feed_code>` when that stored item is older than the oldest item fetched. Reword line 189 as "Expected; T0 must confirm".

**M8. The events database is the only copy of older events, and its backup schedule is open and is not a T2b acceptance item.** [Major] Lenses: `egm-design` (design-8).
Where: 4.3 (line 190); 4.5 (line 224); 5.5 (line 312); section 10 (line 466).
Finding: earlier events are not recoverable from this table. Purge is deferred, so the table grows without bound. The backup schedule is still open.
Fix: decide the dump schedule and retention before T2b. Make a dump and restore check an acceptance step in T2b.

**M9. The spec lacks the problem, goals and non-goals, alternatives, consolidated risks and success metric that the feature-spec standard asks for.** [Major] Lenses: `egm-design` (design-9), `structural` (structural-1), `zoom-out` (zoom-out-4), `comprehension` (comprehension-11).
Where: H2 outline (no Problem, Goals, Alternatives or Risks heading); D1 (line 68); D8 (line 448); 5.4 risk note (line 307); T9 acceptance (line 432); section 1; header (lines 1–7).
Finding: there is no purpose paragraph. Section 1 gives scope but not the objective or the freshness target, which live only in the parent docs. Rejected options for D1, D8/D9 and cooldown scope appear only in the review files. Risks are scattered across notes with no table. The only acceptance for the cron is a run that returns ok. At eight feeds the row volume has no estimate.
Fix: add H2 sections for Problem and goals (with non-goals, the objective and one measurable freshness target, each linked to its parent doc), Alternatives considered (rejected options for D1, D8/D9, and cooldown scope), and Risks and mitigations (one table). Add a rows-per-day estimate. Put a three-sentence purpose after the status block: what is ingested, where it is stored, and which Home screen reads it.

**M10. The eight per-category NSE feeds are not weighed against the existing market-wide announcements fetch.** [Major] Lenses: `zoom-out` (zoom-out-1).
Where: 4.0 and D1 (lines 68–85); cadence (line 122).
Finding: `scanner/marketdata/factors_postgres.py` (lines 59–63, 355–364) already fetches `https://www.nseindia.com/api/corporate-announcements` through `_fetch_nse_feed`. `collector-split-spec.md` line 146 confirms it is market-wide, one request per calendar-month window. The new design costs about 96 NSE requests an hour, and about 1,248 on each holiday. The spec never records why the existing endpoint cannot serve the need.
Fix: add one line to D1 under alternatives: whether the existing endpoint covers these categories. If it does, reuse `_fetch_nse_feed` and its session and UA handling. If not, state the coverage gap that justifies the feeds.

**M11. The events-API caller identity is open and blocks T4d and T5b, the token path is listed as non-blocking, and the production token check has no owner.** [Major] Lenses: `zoom-out` (zoom-out-3), `implementation-readiness` (implementation-readiness-10, implementation-readiness-22).
Where: 4.6 Auth (line 238); section 6 `homeEventsAuth.ts` row (line 325); section 9 T4d, T5b, T5c (lines 425, 428–429); section 10 (line 466).
Finding: `docs/designs/secrets-and-roles.md` Decision 15 (one token file per service) and the ingest role table (ingest sources run under the collector token, with no new identity) already exist. `ui/app/internal_secrets.py` has a constant-time check and a per-service allowlist. `homeEventsAuth.ts` is specific to home events, while six ingest routes (`home-event-sources.md` lines 142–147) need the same gate. The wrong-role 403 test needs a second identity that the spec does not reconcile. The spec does not say where the expected token comes from, how a token maps to a role, or how values are compared. `checkIngestToken` is injected in tests, and T5c covers only the pool, health and index wiring. Section 10 lists the token file path as not blocking, but 4.6 and T4d depend on it.
Fix: decide the identity in 4.6 before T4d starts. Either map the collector token to the ingest roles (and state what the 403 test then checks), or add one token file per service under Decision 15. Put the check in one shared ingest-auth module. Specify the token source, the token-to-role map and the comparison method. Add the production `checkToken` wiring to T5c. Move the token path to a line that blocks T4d and T9.

**M12. The events-table privileges contradict each other, and four database login names are undefined.** [Major] Lenses: `comprehension` (comprehension-2), `implementation-readiness` (implementation-readiness-13), `zoom-out` (zoom-out-11, Nit merged).
Where: section 0 Terms; 4.0 (line 83); 4.1 (line 128); 4.5 T2a and T2b (lines 220, 223); section 8 manual check (line 405).
Finding: line 83 says the API login has `SELECT, INSERT` only. Line 128 grants nothing because the app login owns the database. Line 223 says the collector login can still connect. The spec never names the login the events pool uses. `REVOKE CONNECT FROM PUBLIC` is open (line 223), so the isolation claim behind D8 is not enforced.
Fix: add a table of the four logins (name, environment variable, privileges, consumer) and state whether the API and app logins are the same role. Name the events pool's login and make it the owner the DDL assumes, or add the matching GRANT. Make the REVOKE and a separate events role an acceptance step in T2a or T2b, or drop the isolation claim.

**M13. Row validation is undefined in Python and hand-written in TypeScript, so the two can drift, and an over-length row fails every run.** [Major] Lenses: `implementation-readiness` (implementation-readiness-7), `zoom-out` (zoom-out-7, Nit merged).
Where: 5.2 invalid rows (line 284); 4.6 validation (line 239); section 6 `validateBatch`; T5a (line 427).
Finding: the spec says Python validates rows before posting, but section 6 lists no Python validator. The API rejects rows such as a headline over 500 characters, which would fail every run while the row stays in the feed. `server/src/app.ts` line 146 already compiles route schemas with ajv, yet T5a hand-writes `validateBatch`, which adds a second place for the enum to drift.
Fix: add a Python `validate_row(row)` that returns a reason or None and mirrors the T5a rules. State whether a Python-rejected item is counted as dropped and never posted. Express the row as a JSON schema (date-time with offset, http or https URI, enum, maxLength 500), validated through the compiled route schema, and keep the enum in one place.

**M14. The batch route's responses are unspecified for a malformed body, a database failure, an empty array and the inserted count.** [Major] Lenses: `implementation-readiness` (implementation-readiness-11).
Where: 4.6 endpoint table (lines 233–234); section 8 `homeEventsRoute` tests (line 404).
Finding: only 401, 403 and 413 are named. The tests cover `missing_token_401`, `wrong_role_403`, `valid_batch_returns_counts` and `oversize_413` only. The spec does not say how `inserted` and `duplicates` are derived from `ON CONFLICT DO NOTHING`.
Fix: add 400 for a malformed body and 500 for a failed transaction. State that an empty array returns zeros, and that `inserted` is counted by RETURNING. Add a test for each.

**M15. The events-pool config and health contract are underspecified, and the events transaction dependency has two names.** [Major] Lenses: `implementation-readiness` (implementation-readiness-12), `comprehension` (comprehension-10).
Where: 4.6 server substrate (line 240) and health (line 242); section 6 (line 325); T5b and T5c (lines 428–429).
Finding: `eventsPoolConfig` does not say how `POSTGRES_EVENTS_DB` applies to the DSN form (the Python side needed an explicit dbname). T5c's acceptance, "reports the events pool", names no field, status or value. The dependency is `withTransaction` in 4.6 and `eventsTx` in section 6 and T5b.
Fix: name the mechanism (for example, parse the DSN URL and replace its database path). State the health response field and status code that the acceptance checks. Use one name for the events transaction dependency.

**M16. The `pgschema` optional argument has no defined mechanism for a throwaway schema.** [Major] Lenses: `implementation-readiness` (implementation-readiness-9).
Where: 4.5 T2a (lines 213–217).
Finding: `apply(target)` takes only a target name, and `connect(dbname)` changes only the database name. The spec does not say how the events files reach a throwaway schema, or where `schema_migrations` lives inside it.
Fix: name the argument and its type. State how it reaches `apply()` (a schema or `search_path` parameter), and where `schema_migrations` lives.

**M17. T2b cannot be executed from the spec.** [Major] Lenses: `implementation-readiness` (implementation-readiness-14), `comprehension` (comprehension-4), `codebase-details` (codebase-details-8).
Where: 4.5 image rebuild (line 208) and migrate stage (line 221); T2b (lines 219–220); section 9 T2b (line 418).
Finding: line 208 says the image must be rebuilt before the migrate stage can see `db/events_migrations/`, but T2b's "image rebuild note" is ambiguous. A missing events directory in a stale image may yield zero files and a success report. Line 219 says to mind the PowerShell 5.1 quote-dropping and to follow "the existing `Invoke-Docker` usage" without naming the file or the behaviour. Line 220 uses `\gexec` without explanation. The spec cites the migrate stage at "currently line 238", but the migrate calls sit at about lines 283 and 288 of start.ps1 (the create-events-DB stage is at 248–270).
Fix: make start.ps1 build the scanner image before the migrate stage, or fail when the events directory is missing, and state which behaviour T2b implements. Name the file and line of the existing `Invoke-Docker` usage, and state what the quote-dropping does and what `\gexec` runs. Replace the line number with the stage name, or use 283 and 288.

**M18. Build order and dependencies disagree: sections 2 and 9 give different serial lists, and T4d's Depends omits T4e and T7.** [Major] Lenses: `implementation-readiness` (implementation-readiness-2, implementation-readiness-21), `comprehension` (comprehension-6), `structural` (structural-3).
Where: section 2 build order (line 46); section 9 serial order (line 411); T4d Depends (line 425); line 434.
Finding: section 2 lists T2b, T3b, T3c, T4b, T4c and T6 one at a time, with no T3a, T4e or T7. Section 9 lists T3a, T3b, T3c, T4b, T4c, T4e, T6 and T7. T2b edits start.ps1 and env.template, not `home_events.py`. `HomeFilings` passes `FEEDS` and the real parse, so T4d needs T4e. Its count of enabled feeds in `plan()` also needs T7, unless the enabled list is restricted until T7 lands. Line 434 ("T4d does not wait on samples") is therefore false.
Fix: derive one serial order from section 9's Depends column, and cite it in section 2. Move T2b out of the group. Add T4e to T4d's Depends, and add T7 or restrict `enabled_feeds` until T7 lands. Correct line 434.

**M19. Build status is stated in several places and disagrees, and per-task status is missing.** [Major] Lenses: `codebase-details` (codebase-details-5), `zoom-out` (zoom-out-8, Nit merged), `implementation-readiness` (implementation-readiness-21, T6 part).
Where: section 2 (line 46); section 6 "Built: T6" (line 366); section 9 T6 row (line 430); `docs/progress/execution-ledger.md` (line 117).
Finding: section 6 says "Built: T6" at commit 089a975. Section 9 lists T6 as pending, with a T4c dependency. The ledger lists it as waiting. The `codebase-details` lens reports as landed: T2a, T2b, T3a to T3c, T4a, T4b and T4c, T5a and T5b, and T6. It reports as not built: T1, T4d, T4e and T7, T5c, and T9.
Fix: keep build status only in `execution-ledger.md`, and have the spec link to it. If status stays in the spec, give done, partial or not started per task, with the commit.

**M20. The section 6 file list is not the full scope, and the config JSON files are cited as existing though neither exists.** [Major] Lenses: `codebase-details` (codebase-details-6), `implementation-readiness` (implementation-readiness-15), `structural` (structural-4).
Where: section 2 rows (lines 40–41); section 6 table (lines 316–326); T2a (lines 217, 417); T9 (line 432); sample and fixture directories (lines 100–101); section 8 test files (lines 392–405).
Finding: `config/collector_services.json` and `config/collector_runtime.json` are in neither checkout (`config/` holds only `glossary.json` and `retention.json`), and neither is marked new. `tests/pgschema.py` changes under T2a with no row. The T9 compose file and settings entries have no row. `tests/fixtures/home_events/`, `data/home_samples/` and the new test modules appear only in section 8.
Fix: add a row, marked new or modify, for each file, including the test modules and fixture directories. Mark both config files as new, and gate T9 on their creation.

**M21. The section 2 status value "exists" is ambiguous for the run-once container, the `--source` option and `exchange_cooldown`.** [Major] Lenses: `codebase-details` (codebase-details-7).
Where: section 2 rows (lines 38–39).
Finding: no migration under `db/migrations` creates `exchange_cooldown`. `collect.py` defines `cmd_run` and `cmd_serve` with no `--source` argument. "Exists" may mean "defined in the split spec", which cannot be verified against code and could let T4d be scheduled wrongly.
Fix: use explicit wording, for example "defined in split spec S2, not in code". Name the code artefact each dependency needs before T4d starts.

**M22. The parser contract is undefined: no dispatch from `feed_code` to a parser, no per-feed signature, and no rule for an unknown `feed_code`; T7 is one row covering seven parsers.** [Major] Lenses: `implementation-readiness` (implementation-readiness-19, implementation-readiness-24).
Where: section 6 `parse` (line 350); 4.0 parsed item (lines 87–102); section 9 T4e and T7 (lines 426, 431).
Finding: `parse(feed_code, body)` is the only interface. T7 is one row for T7a to T7g, with no Depends, acceptance or tool-call limit per parser.
Fix: specify a registry from `feed_code` to a parser callable, with its signature. State that an unknown `feed_code` raises a named error that `run_cycle` maps to a failed run. List seven rows, T7a to T7g, each with its feed, Depends, acceptance command and tool-call limit.

**M23. The owner of the first-request gap sleep is unresolved.** [Major] Lenses: `implementation-readiness` (implementation-readiness-3).
Where: 5.1 step 4(c) (line 264); section 6 `fetch_feed` (line 358); section 8 (line 396); section 9 T4b (line 423).
Finding: step 4(c) puts the random gap in the run loop. T4b's `gap_within_bounds` test runs against `fetch_feed`. Both functions receive `sleep` and `rng`.
Fix: give the first-request gap to `fetch_feed`, which also owns the retry wait. Leave `run_cycle` with the deadline and cooldown checks. Align step 4(c) with the T4b and T4c acceptance.

**M24. An empty `enabled_feeds` list passes validation, and the start-feed formula then divides by zero.** [Major] Lenses: `implementation-readiness` (implementation-readiness-4).
Where: section 7 validation (line 384); 5.1 step 3 (line 263).
Finding: "every `enabled_feeds` entry is a `feed_code` in FEEDS" is vacuously true for an empty list. The start-feed formula `int(now.timestamp() // 300) % n` then divides by zero.
Fix: state that an empty `enabled_feeds` fails the run in step 1 with message `config:enabled_feeds`, and makes no request.

**M25. T0's acceptance requires a fixture that T0 does not write, and "successful fetch" is undefined.** [Major] Lenses: `implementation-readiness` (implementation-readiness-16, implementation-readiness-28).
Where: 4.0 sample and fixture policy (line 101); section 9 T0 acceptance (line 415).
Finding: the acceptance says "one fixture hand-checked against its sample", but T0 writes no fixture, and line 101 says fixtures wait on the tag-to-key table that T0 produces. "Each URL answered with a successful fetch" is not defined for T0.
Fix: replace the clause with "the tag-to-key table in 4.0 is checked against one saved sample". Define "successful" as `classify_response` returning ok for that URL.

**M26. Named tests lack expected results, and some required behaviours have no test.** [Major] Lenses: `implementation-readiness` (implementation-readiness-18, implementation-readiness-27).
Where: section 8 (lines 394–396); 5.2 retry (line 276); 5.2 mid-run cooldown (line 291); 4.2 (line 180).
Finding: `retry_skipped_when_deadline_too_close` does not say what the feed outcome is. `strips_token_like` has no defined pattern (see M27). The mid-run cooldown outcomes (skipped before any fetch; ok with `exchange_cooldown` after a fetch), the 401 and 408 classification rows, and the in-batch duplicate drop have no named test.
Fix: give each named test an input and an asserted output (for example, a skipped retry yields `transient` and the loop continues). Add named tests for each missing behaviour.

**M27. The run message has no template, and redaction is undefined.** [Major] Lenses: `implementation-readiness` (implementation-readiness-8), `zoom-out` (zoom-out-5, Nit merged), `comprehension` (comprehension-15, Nit merged).
Where: 5.1 step 6 (line 266); 5.2 (lines 290–291, 295); 5.4 `redact_error` (line 308); section 6 `FetchResult.detail` (lines 342–343) and `redact_error` (line 356); section 8 tests (lines 394, 419).
Finding: the run message combines several conditions with no order, separator or template. It is unclear whether `failed:<feed_code>` names the HTTP status or the redacted detail. `redact_error` strips "token-like substrings" with no pattern. `scanner/home_events.py` line 27 already has a parallel scrubber. The `zoom-out` lens judges scrubbing a weak control.
Fix: add a message template with separator and order, and one example per status. Build run messages from a fixed vocabulary (feed code, outcome, HTTP status class, exception type), and drop `redact_error`, `FetchResult.detail` and their tests, keeping one assertion that a message holds only vocabulary fields. If the scrubber is kept, give the token-like regex with two literal examples.

**M28. Next steps and stale passages contradict the approval and the decisions.** [Major] Lenses: `structural` (structural-2), `comprehension` (comprehension-8), `implementation-readiness` (implementation-readiness-29).
Where: section 11 (lines 468–473); header status (line 3); line 188; line 364; line 293.
Finding: section 11 asks the user to decide open points, refers to a reply the document does not contain, and asks for approval. The header records approval on 2026-11-11 and says no task is dispatched before approval. Line 188 says an item that fails both tests is counted once, although only the universe test is active. Line 364 cites the deferred 4.3 date tests. Line 293 calls the 403 policy open, although section 10 decides it.
Fix: replace section 11 with the post-approval steps (T0 samples, split-spec requests, parent-doc updates, the fundamentals-trigger spec, then `plan_add`). Remove the two-test sentence and the date-test reference. Change line 293 to "decided (blocked)".

## Nits

**N1. The XML parser and response-size cap are unnamed.** [Nit] Lenses: `egm-design` (design-10).
Where: D1 (line 68); 5.2 and section 6 fetch and parse (lines 102, 359).
Finding: the chosen XML transport names no safe parser and no size cap. The parser reads untrusted bytes in a container that holds database credentials. `session.get` returns `.content` as bytes with no limit.
Fix: name the parser (defusedxml, or the standard library with entity limits) and a maximum body size in `fetch_feed`, each with one test.

**N2. `/internal/*` and `/api/*` share a listener, and whether `/api/*` needs authentication is unstated.** [Nit] Lenses: `egm-design` (design-12).
Where: section 2 S3 row (line 43); 4.6 (line 241).
Finding: once the server runs in a container, both route sets are reachable from every container on the compose network.
Fix: serve `/internal/*` on a second listener bound to the compose network only, or state the authentication `/api/*` requires.

**N3. Holiday polling costs about 1,248 NSE requests, and D6b is labelled moot.** [Nit] Lenses: `egm-design` (design-11), `zoom-out` (zoom-out-9).
Where: 4.1 cron consequences (line 122); D6b (line 446).
Finding: holidays still start a run that finds nothing (8 feeds x 156 ticks). `run_cycle` does not check the exchange calendar. The repo already holds a holiday list in `ui-v2/src/lib/marketSession.ts` (line 32, `EXCHANGE_HOLIDAYS_2026`).
Fix: relabel D6b as open for the holiday skip. Check whether scanner already has a holiday calendar and use it. If not, skip weekends and holidays using one shared list read by both Python and the UI, and record the skip in the run row.

**N4. The API-down behaviour should name the watchdog gate.** [Nit] Lenses: `zoom-out` (zoom-out-2).
Where: 4.6 (line 242); section 2 dependency table.
Finding: the main path is the watchdog gate in the split spec (line 67, option a). The skipped `api_unavailable` record is only a race guard. This feature adds no gate of its own.
Fix: add one sentence at line 242 saying so. Do not reopen D9 or option a.

**N5. Some fields and defaults add nothing, or have no owner.** [Nit] Lenses: `zoom-out` (zoom-out-6), `implementation-readiness` (implementation-readiness-30).
Where: 4.0 (lines 70, 80–81, 335, 382); 4.1 (line 132); section 6 `to_event_row` (line 354), `HomeFilings` (lines 336, 425); 5.1 (line 258).
Finding: `default_enabled` duplicates `enabled_feeds`. `flagged` has no reader in any section. `exchange` is derivable from the `nse:` prefix. The cooldown adapter's owner is split: S2 supplies the real one, while T4d builds the adapter. `to_event_row` does not set `dedupe_key`, which `run_cycle` reads. The defaults for `run`'s `now=None` and `dry_run=True` are unstated.
Fix: remove `default_enabled` and `flagged`, or record what reads `flagged`. Remove the `exchange` column, or record its reader before the BSE phase. Name the cooldown adapter's owner. Add `dedupe_key` to `to_event_row`'s output. State the default for `now` and what `dry_run=True` returns.

**N6. Helper signatures and per-test names duplicate the task briefs and will go stale.** [Nit] Lenses: `zoom-out` (zoom-out-10).
Where: section 6 helper signatures; section 8 (about 110 test names, lines 388–405).
Finding: review 2 M16 and minor 9 asked for per-method test names, so the spec has to resolve that tension.
Fix: keep the public entry points, the 5.2 table and the per-file test counts in the spec. Move per-test names and helper signatures to the task briefs in section 9.

**N7. Classify and fetch mapping edge cases are not described.** [Nit] Lenses: `codebase-details` (codebase-details-10), `implementation-readiness` (implementation-readiness-20).
Where: 5.2 classify table (lines 274–282); section 6 `fetch_feed` (line 359); section 6 `to_event_row`.
Finding: `classify_response` maps any 2xx other than 200 to fail. `to_event_row` raises `ValueError` on a non-nse prefix and on a naive datetime. The 3xx row is unreachable as written, because a requests-style session follows redirects by default. No outcome is given for other request exceptions.
Fix: add one line each to 5.2 and to the row-conversion notes. Disable redirects for feed GETs so 3xx reaches `classify_response`. Map other request exceptions to `fail`, with a stated outcome.

**N8. `refetch_only_on_new_result` is also seeded in the migration.** [Nit] Lenses: `codebase-details` (codebase-details-9).
Where: 4.7 (line 250).
Finding: the spec says the key is only whitelisted in `settings.py`. `db/migrations/001_core.sql:95` also seeds it in the fundamentals row.
Fix: add "and seeded in `db/migrations/001_core.sql:95`".

**N9. The T5c gate refers to the wrong checkout, and several phrases are ambiguous.** [Nit] Lenses: `codebase-details` (codebase-details-11), `comprehension` (comprehension-20).
Where: section 9 T5c (line 429); 5.1 step 3 (line 263); 5.4 (line 306); section 6 (line 353); section 8 (line 395).
Finding: the T5c gate describes the primary checkout's working tree. The spec lives in the `egm-filings-rev4` worktree, where `kiteToken.ts` is absent and `index.ts` is unmodified. The "300" in the start-feed formula is the 5-minute tick and is unexplained. "Counts keys: universe" lists no full key set. "(1, enabled at the last T7 step)" does not say which test is switched on. "The archive host" is unnamed.
Fix: name the checkout in the T5c gate, or restate it as a commit requirement. Explain 300 as the 5-minute tick. List the full count keys. Say which test is switched on at the last T7 step. Name the archive host.

**N10. The universe query has no rule for a symbol with two ISINs, or for a feed ISIN that differs from the universe ISIN.** [Nit] Lenses: `implementation-readiness` (implementation-readiness-23).
Where: 4.3 (line 184); 4.0 parsed item (line 93); section 6 `filter_items` (line 353).
Fix: state the uniqueness assumption for `symbol`, the rule when the feed ISIN and the universe ISIN differ, and whether a conflict is counted.

**N11. T9's compose service, settings update and acceptance are unspecified.** [Nit] Lenses: `implementation-readiness` (implementation-readiness-25).
Where: section 9 T9 (line 432).
Finding: the compose file and command are unnamed, the update mechanism is unstated, and the acceptance needs a live NSE response and a live token.
Fix: name the compose file and service fields, or cite the split S3 section that defines them. Name the exact update command. State the environment the acceptance needs.

**N12. Acceptance details are loose.** [Nit] Lenses: `implementation-readiness` (implementation-readiness-31).
Where: section 9 T4 and T5 (lines 323, 407, 415); 5.3 (line 299).
Finding: the `test_collect_sources` docstring fix names no target text. The 330 s watchdog assumes at most 1,500 items per feed, which T0 does not check. Enum consistency is said to be checked by hand at review, but no acceptance includes it.
Fix: state the docstring text. Add a T0 check that each feed's item count is at most 1,500. Add an enum-consistency check to T4e and T5a acceptance.

**N13. Several terms and acronyms are used without definition.** [Nit] Lenses: `comprehension` (comprehension-5, comprehension-12, comprehension-13, comprehension-17).
Where: section 0 Terms (lines 15–22); lines 18, 26, 28, 40, 76, 120, 122, 172, 196, 204, 235, 238, 247, 258, 263, 299, 353, 411, 415, 473.
Finding: run-model terms (due, run-once container, watchdog, the serve loop, dry run, split risk 3 and 8) are not glossed. "Order win", "3-per-stock cap", "attachment text" and "category" are unexplained. `plan_add`, the tool-call limit and "local-model task" are undefined. NSE, BSE, ISIN, IST, SAST, LLM, Fastify, Mongo, Upstox and "cr" are not expanded. "The API", "the Fastify server" and "the Fastify API" are used interchangeably, without saying whether they are one service.
Fix: add one-line definitions to section 0, with each run-model term linked to the split spec. Define the order-win and cap terms and the attachment text at first use. Expand each acronym once. State that "the API" and "the Fastify server" are one service.

**N14. The migration-number gating set is ambiguous.** [Nit] Lenses: `comprehension` (comprehension-14), `structural` (structural-7).
Where: section 2 migration row (line 44).
Finding: "those three" excludes S8, which the same sentence calls a fourth claimant.
Fix: name the four claimants (S2, S2a, S5a, S8) and state that NNN waits for all four.

**N15. Review references are mislabelled.** [Nit] Lenses: `comprehension` (comprehension-16), `structural` (structural-6).
Where: section 0 legend (line 13); 4.1 (line 120).
Finding: line 13 gives "M1 to M14" as review 2's numbers, but review 2 numbers M1 to M19. Line 120 labels M14 as "third review".
Fix: change line 13 to "M1 to M19 of review 2", and line 120 to "review 2, M14".

**N16. Decision rows give a status without a reason, and the ID column mixes labels with decision IDs.** [Nit] Lenses: `comprehension` (comprehension-19), `structural` (structural-8).
Where: section 10 (lines 446–456).
Finding: D1 says "for long-term support" with no rejected option. D6b says "Moot here (Z3 deferred)" with no link. "Add a floor (earlier)" and "Filed results with catch-up" lack reasons. Rows labelled "Cooldown scope", "Fixtures", "Ingest floor", "Cuts", "Q1 to Q4" and "Fundamentals trigger" sit in the ID column beside D1 to D10.
Fix: give each row a one-clause reason and a plain current status. Rename the column to "Item", or move the labelled rows into a second table.

**N17. First-person voice appears in normative text.** [Nit] Lenses: `comprehension` (comprehension-18).
Where: section 0 Legend (line 11); 4.1 (line 122); section 10 (line 464).
Finding: "my default", "which I read into" and "explained to you" leave a later reader unable to tell who "I" is.
Fix: replace with "the author", and name the author once in the header.

**N18. Review history and superseded claims sit in normative text.** [Nit] Lenses: `comprehension` (comprehension-9).
Where: line 43 (superseded "internal routes are compose-only" claim); line 122 ("Revision 2 used 8-15"); line 299 ("the earlier shared-lock idea"); line 366 ("Built: T6").
Fix: move the revision and superseded-claim narrative into a changelog, and keep the normative text in present tense.

**N19. The module layout table mixes what the Contents column means, and row 325 packs six files into one cell.** [Nit] Lenses: `structural` (structural-5).
Where: section 6 (lines 322–326).
Fix: use one file per row, with a description in the Contents column. Move section pointers to a separate column.

**N20. The header and cross-document references do not match the sibling docs.** [Nit] Lenses: `structural` (structural-9, structural-12).
Where: header (lines 1–7); 4.6 (line 238); body references to the overview and split spec (lines 40, 307).
Finding: the H1 embeds the status, and the header is a bullet list, unlike the sibling design docs, which use plain Status and Date lines. Body references to `secrets-and-roles.md`, the overview and the split spec are bare names, while the header links them.
Fix: use an unqualified H1 with plain Status and Date lines. Link the first body reference to each cross-document file.

**N21. T2a and T2b are bold paragraphs, and feed codes are not in code spans.** [Nit] Lenses: `structural` (structural-10, structural-11).
Where: 4.5 (lines 212, 219); 4.0 registry table (lines 72–81).
Fix: make T2a and T2b H4 headings under 4.5. Wrap each `feed_code` value in a code span.

## For you to decide (not applied)

1. Per-feed cadence for the two quarterly feeds (M6). The user's 2026-11-10 answer was "no decision yet"; the default is every 5 minutes.
2. Whether the existing market-wide announcements endpoint covers these categories (M10). This is the D1 alternatives question.
3. Events-API caller identity (M11): map the collector token to the ingest roles, or add one token file per service under Decision 15.
4. Backup schedule and retention for the events database (M8).
5. Alternatives, risks and the success metric to record (M9), including the rejected options for D1, D8/D9 and cooldown scope.
6. Cooldown cap, 2 h versus 3 h (M2), owned by S2.
7. Holiday skip for D6b (N3).

## Not verified by the compiler

The codebase claims in B1 to B4, M19, M20, M21 and N8 to N9 come from the `codebase-details` lens. They were not re-checked in this compilation. The spec file was not read or changed, and no other file was written.
