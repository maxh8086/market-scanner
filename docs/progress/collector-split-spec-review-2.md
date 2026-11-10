# Re-review: collector-split-spec.md (EGM default, six lenses + synthesis)

Target: `docs/designs/collector-split-spec.md`. Prior review: `collector-split-spec-review.md` (NOT READY, B1-B5). Six fresh Goldfish subagents (design, codebase-details, zoom-out, comprehension, implementation-readiness, structural), deduplicated. User decisions not re-argued. Known-not-done items (glossary, Unverified subsection, freshness spec, S0 measurements, M11) excluded. Codebase claims below were verified by the codebase lens against the repo; others are as cited from the spec.

## 1. Verdict

NOT READY. The five old blockers are resolved in substance (B1 only partly). The edits introduced 4 new blockers: no retry rule (re-start storm), Fastify is not a compose service so the watchdog cannot restart it and containers cannot reach its loopback bind, the S5 endpoint contracts are unspecified, and the CSV consumer list is wrong. Only S0 is dispatchable today.

## 2. Status of previous blockers

- B1 (skipped hides missed slot): PARTLY. Ok-only last run (4.2) fixes the masking. The retry rule the first review asked for was dropped, which creates NB1.
- B2 (execute_source): RESOLVED (4.1, S1). `collect.py:173-207` range confirmed. S1 acceptance does not test the lock.
- B3 (cron in watchdog, never-run, fundamentals): RESOLVED (C2, 4.2). Gap: fundamentals queue/staleness data is not built by any task (see NM6).
- B4 (what "the API" is, gating): RESOLVED in text (Fastify, watchdog starts nothing when down, events sources defined). Residual: NB2, NM1.
- B5 (no-CSV): RESOLVED structurally (S2a, one branch). Consumer list is wrong (NB4).

## 3. New blockers

NB1. No retry rule for failed or skipped runs (4.2, line 160 poll 60 s). Due = latest slot newer than last ok run, so after any failure, `already_running` skip, or `exchange_cooldown` skip the source stays due and the watchdog restarts it every poll for the rest of the slot. A blocked NSE source gets hit each minute, which extends the block and defeats the cooldown; a failing fundamentals with a pending queue loops. Fix: `/internal/due` considers last attempt (no retry until a minimum delay or next slot), does not return sources whose exchange is cooling down, and adds shared vectors for these cases.

NB2. Fastify is not a compose service (4.4, 4.5). `docker-compose.yml` has only `collector`, `ui` and the databases; `server/src/index.ts:41` listens on 127.0.0.1:`SERVER_PORT` (8081) as a host Node process. So (a) "docker compose up -d ... then the API" cannot start Fastify; (b) a run-once container cannot reach a loopback bind, so events sources' health check and endpoint writes have no transport. Fix: state how Fastify is hosted and restarted and which address containers use (for example `host.docker.internal` with a non-loopback bind). Health is `GET /api/health` (`server/src/app.ts:126`). No compose healthcheck exists for `ui`.

NB3. S5 endpoint contracts are unspecified (4.2, 4.5, section 8 M4/M8). Missing: `/internal/due` request and response JSON (per source: due, reason, `pending_request`, `request_id`, order, who sorts), HTTP codes (401, 503), handling of stale `running` rows; `POST /internal/heartbeat` body, storage (Fastify has no write grant on any `collector_*` table), staleness threshold; the status response path, what sets `paused`, `since` format, and whether the 3-failure rule runs in UI or server. S4's fake API cannot be written without them. Fix: add an "Endpoint contracts" subsection with JSON examples.

NB4. CSV consumer list is wrong and incomplete (section 3, S2a). `conclude.py` does not read `ath_scan_*.csv` (it reads `ath_enriched_*.csv`). `fundamentals` reader is `sources.py:376-418`, not `scanner/fundamentals.py`. Missing readers: `record_run.py:111`, `portfolio.py:67`, `crosscheck.py:67`, `start.ps1:207,228`, `enrich.py:78,1008`, `sources.py:301,342`; writer `scanner/report.py:83-98` (CSV and xlsx); tests `tests/test_collect_ath_scan.py`, `tests/test_empty_scan.py`. S2a "grep empty" is unachievable unless the report CSV/xlsx fate is decided, and `portfolio.py`/`crosscheck.py` run outside the collector: applying "no CSV anywhere" literally breaks them. Needs the user to confirm scope (a gap in the decision, not a re-argument), and S2a must carry the list.

## 4. New majors

NM1. Fastify-down is incomplete. Behaviour when health passes but `/internal/due` returns 401/500/timeout is undefined (watchdog silently starts nothing; banner keys off status, not the watchdog). `ui` (secrets, Upstox tokens) is not health-checked or restarted. If the dashboard is served via Fastify the banner cannot render. Decision 4 text still says skipped ticks are recorded; with nothing started there are none, so label the `api_unavailable` skip a race guard only.
NM2. Section 2 decision 4 is a stale rule with an inline "Superseded" note; rewrite as the current rule. Decision 6 (15 min `announcements`) contradicts 4.6/4.7 (30 min until freshness spec); the 4.6 migration sentence and S8 "with the new cron" still include `announcements`. M9 assigns the cron migration to S7, but it belongs to S8 (`filings`) and the freshness spec.
NM3. Catch-up wording (4.2 C5) describes cron evaluation in the watchdog ("latest slot newer than last run") contradicting C2; "respecting pacing (4.3)" refers to nothing (pacing is per source, only the cooldown is shared); undefined what a scheduled start during catch-up does; "waits until API healthy" is redundant. Rewrite once: watchdog takes the due list; first pass after start is serialized in priority order; later passes parallel.
NM4. Cutover state has no owner. Nothing says how `/internal/due` avoids returning a source with no compose service yet. Needs a moved-source list (file named, updated by each of S6-S8) and an S1 test that a `COLLECTOR_LOOP_SKIP` source is not run by `serve` and an unmoved source is not returned by due.
NM5. `link_request_to_run` is never called today (only defined at `scheduler.py:123`); M4 "kept" is wrong, it must be added. `execute_source` must honour `args.dry_run` (`collect.py:186`). `claim_requests` fix: state `DISTINCT ON (source)` or claim filtered by source (unique partial index `collector_requests_one_open`).
NM6. S5 is overloaded and cannot be fully accepted: the fundamentals queue and staleness data does not exist (S7 says "after queue exists"; no task builds it); stub it in S5 and finish in S7. Split S5 into due endpoint + grants + vectors, and heartbeat + status field + banner. Heartbeat is scope beyond decision 4 (zoom-out suggests cutting; the 3-failure UI rule covers API-down alone).
NM7. Fastify spec claim is false in part (4.2): `server/src/collectorRefresh.ts:59` already queries `collector_runs` with `status='ok'` and `:42` inserts `collector_requests`; migrations 042 and 043 already grant these to `market_scanner_app`. Only `collector_settings` needs a new grant; M4's "gets SELECT on collector_requests in S5" is moot; the ok-only query is reusable for the vectors.
NM8. S1 is a grab bag (nine items). Split: S1a (execute_source, run-once, skipped write, ok-only) and S1b (init, COLLECTOR_LOOP_SKIP, claim_requests). Also: `collector_runs.status` already allows `skipped` (`001_core.sql:104`), so no migration; `trigger` allows only `schedule`/`manual`; latest migration is 046, so next is 047. S1 acceptance "`run` still writes the same rows" is wrong (`run` writes none today). "skipped on API down for an events source" is untestable (no events source registered); use a fake.
NM9. Run lock has no mechanism (table, advisory lock, file), release after kill, or test; "ignore stale running rows" is a third overlapping guard. Fixed container name can collide with a leftover after a hard kill (watchdog should `docker rm -f` first; confirm in S3).
NM10. Dependency order is not a DAG. S4 depends on S5 but is listed first; S3 needs S1; S6 needs S3, S4, S5, S1, S2 (not only S2a); S7/S8 likewise; S6 acceptance "on schedule" cannot apply to manual `ath_scan`. Add a Depends column and reorder (S0, S1, S2a, S2, S5, S3, S4, S6-S9).
NM11. S2a needs written DDL, unique key, run-id type, retention, rollback, staleness rule (which scan date readers use when table is stale or empty), and a hard stop if S0 finds consumers outside Python. Fixtures: converted CSV samples. S2a moving all readers at once means S6-S8 depend on it only for the `./output` mount removal.
NM12. Section 8 "Proposed" rows (stale-running ignore, `docker stop` at max runtime, 60 s poll, pending_request flow, init command) are relied on by tasks but unconfirmed; the user should confirm or they go to the open list. Per-source max runtime config file and watchdog bearer-token read path (host file, since `ui` may be down) are unnamed.
NM13. Two due implementations live until S9; budget it: Python `due_sources` frozen after the ok-only fix, vectors file deleted in S9.
NM14. Document hygiene: review labels (B2, C2, M13) and first-person history in the design body; Mongo options A/B still listed after decision; 4.3a precedes 4.3 and "supersedes" a section that holds nothing to supersede; `## 4.7` should be `###`; "filings spec 4.6" vs "4.7" for the fundamentals trigger conflict; section 7 stale (asks questions already answered, asks for a review now done; add: confirm Proposed rows, write freshness spec); `test_collect_sources.py` update placed in S1 (line 146) and elsewhere (line 182); risk 8 and risk 2 stale ("watchdog cron evaluation", "CSV and Mongo decisions depend on S0"); S2 cooldown acceptance covers NSE only though four exchanges are named, and the symbol-update job name comes from S0.

## 5. Minors

- Blank line needed after the 4.6 table before the migration sentence.
- `filings` evidence row (line 34) still mixes three claims; services table in 4.5 is a bullet labelled "to confirm".
- 4.4 "Stop" omits max-runtime `docker stop`; pick Task Scheduler now rather than deferring to S4.
- Never-run: a source with only failed/skipped rows counts as never-run; state it is intended.
- Banner described in 4.5 and again in M8; fold together; `App.tsx:52` vs `sessionBanner` same thing, say so.
- Weekly sweep for fundamentals appears only in 4.6; "slot" and the two databases (main vs events) undefined before use.
- S0 acceptance should name its note file and required contents; S9 acceptance should include removal of `serve`, Python `due_sources`, compose comment fix.
- M1 max-runtime stop is arguably unrequested; `start.ps1` restart is not continuous (reword risk 4 to rely on Task Scheduler).

## 6. What is blocked on what

- S0: dispatchable now.
- S1a/S1b: need S0 (migration number, trigger values); split first.
- S2: S0 (existing pacing, symbol-update job name); acceptance edits.
- S2a: S0 consumer list, user scope call on `portfolio.py`/`crosscheck.py`/report CSV (NB4), written DDL.
- S5: NB1, NB2, NB3, NM6, NM7; queue stub.
- S3: S1; fixed-name collision check; NB2 for network reach.
- S4: S5, S3, S1, NB1, NB2, NM12.
- S6: S2a, S2, S3, S4, S5, NM4; `ath_scan` acceptance rewritten for manual mode.
- S7: S2a, filings-spec fundamentals queue (external).
- S8: S2a, freshness spec for announcements cron; NM2.
- S9: S6-S8; acceptance to write.
