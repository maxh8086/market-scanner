# Execution ledger

Created 2026-11-10 by the orchestrator run. Re-read at the start of every loop iteration.
Rollback rules: `docs/progress/rollback.md`. Test command: `.venv\Scripts\python.exe -m unittest discover -s tests -t . -q`.

## Baseline

- Date: 2026-11-10. Branch `docs/rollback-procedure` at `9fe618d`. `main` at `579e9c9`. Working tree clean before this file was added.
- Offline suite: **1151 tests, OK (skipped=12)**. Run on this checkout.
- Open PRs on `maxh8086/market-scanner`: none (`gh pr list --state open`).
- Existing `pre-task-*` tags: none.

## Status key

- `done`: evidence recorded (commit sha or PR).
- `gated: design approval`: the plan says the design must go through the EGM brainstorm and user approval before any task is dispatched. Not dispatched.
- `gated: user decision`: the plan asks for a yes/no or value from the user before build.
- `blocked: needs user`: needs data or a secret only the user can supply, or a third party's answer.
- `not started`: no approval needed, but no task dispatched yet.

## Items

| # | Item | Source | Status | Evidence / reason |
|---|---|---|---|---|
| 1 | S1: master key file and AES-256-GCM layer; UI fails closed without key | `secrets-and-roles.md` ("S1 built") | done | Commits `bfaa506`, `95ec8ea`; merged in PR #69 (merge `579e9c9`). Tests: `tests/test_secret_crypto.py`. Rollback point: none taken (pre-dates this run; no `pre-task` tag). |
| 2 | Mask saved secret values in `GET /api/secrets`; ignore saved Screener pages | git log | done | Commit `8080679`, merged in PR #68 (merge `6c79969`). |
| 3 | Upstox key-ratios fixture for TCS (no personal data) | git log | done | Commit `0d69697`. |
| 4 | Upstox ROA definition search and news terms record | git log | done (findings only) | Commit `a9e40a0`. Docs only; the open question is still open (see item 14). |
| 5 | S2: `app_secret` table (migration, encrypted rows, down-step, backup) | `secrets-and-roles.md` (data model, "Not in S1") | done | User approved the S2–S5 design on 2026-11-10 ("go ahead"). Branch `feat/secrets-s2-app-secret`, commit `a893450`, PR #70 merged as `e9f31bd`. Tag `pre-task-5` (origin/main `579e9c9`). Backup `data/backups/pre-task-5-market_scanner-20261110-034023.sql` (318 MB, taken before migration). Migration 045 applied to live `market_scanner`, table verified. Down-step: `db/migrations/down/045_app_secret.down.sql`. 13 offline tests. |
| 6 | S3: admin CLI (list, meta, set; test and rotate not built) | `secrets-and-roles.md` decision 9 | done | Branch `feat/secrets-s3-s4-cli-import`, commit in PR #71, merged as `314e655`. Tag `pre-task-6` (origin/main `e9f31bd`). No schema change. `set` reads the value from a hidden prompt and checks read-back before commit. `test` (decision 11, live Telegram/Upstox calls) and `rotate` are NOT built. |
| 7 | S4: import from `data/secrets.env` (plaintext NOT deleted) | `secrets-and-roles.md` ("Migration from today") | done (import); plaintext deletion pending user yes | Live import 2026-11-10 via `import-env`: `upstox_analytics_token` (created 2026-05-18, expires 2027-05-18), `kite_api_key`, `kite_api_secret`. Each decrypts back to the file value. Screener not imported (cut from v1). Rollback point: tag `pre-task-6` (code); backup `data/backups/pre-task-7-market_scanner-20261110-034407.sql` taken before the write. `kite_access_token` was empty in the file and was not imported. Deleting `data/secrets.env` needs the user's explicit yes. |
| 8 | S5: loaders (decrypt on demand in the API, service token for other services) | `secrets-and-roles.md` decision 10, decision 15 | done | PR #73 merged as `8b26503` (merge commit; branch `feat/secrets-s5-loaders` deleted). Tag `pre-task-9` (origin/main `8f8182e`). No migration, no DB write, no backup needed. Tests: `tests/test_service_secrets.py` (20, pass); full offline suite 1205 OK (skipped=12). Four legacy tests updated (approved). One deviation: `test_1535_is_not_skipped_by_market_gate` patches `fetch_secret` to raise `SecretUnavailable` so it still stops before any network call. Docker compose not verified (no Docker run here). Plaintext `.env` and `data/secrets.env` untouched. Reindex: 16 files indexed, 0 failed. |
| 9 | S6: `test` and `rotate` CLI commands | `secrets-and-roles.md` decisions 11 and 13 | done | PR #74 merged as `10b25cd` (branch deleted). Tag `pre-task-10` (origin/main `8b26503`). No migration, no DB write. `test` runs a live check on the stored value and never writes; `rotate` checks the candidate first and saves only on pass, then reads back. Checks: Telegram `getMe`; Upstox market-quote OHLC (used instead of a fundamentals call, which does not exist in code yet; item 11 blocked). Tests: `tests/test_secrets_cli_s6.py` (20, pass); full suite 1225 OK (skipped=12). |
| 10 | Admin web configuration screen | `secrets-and-roles.md` decision 4, decision 9 | not started (out of v1) | Decision 9 makes the web screen v2. Not part of v1 scope. |
| 11 | Fundamentals Upstox secondary: build | `fundamentals-upstox-secondary.md` | gated: user decision | Decisions are approved (2026-11-10). Build still needs the "Open before build" items: Screener fixture (save one page for the same stock as the Upstox fixture), rollback rules for Upstox rows, "not applicable" rule and ROE/ROCE definition marked "needs your OK". |
| 12 | Analytics token expiry alert | `fundamentals-upstox-secondary.md` (section "Analytics token expiry alert") | done (not live: no Telegram config yet) | User accepted defaults (30, 7, 1, expiry day; 401/403 auth alert). PR #72 merged as `8f8182e` (commit `a369a15`). Tag `pre-task-8` (origin/main `314e655`). Backup `data/backups/pre-task-8-market_scanner-20261110-091027.sql`. Migration 046 applied live, table verified. Down-step: `db/migrations/down/046_token_expiry_alert.down.sql`. 11 offline tests; suite 1185 OK. Alerts stay off until `telegram_bot_token` and `telegram_chat_id` are stored in the secret store (not via chat). |
| 13 | Home event sources (exchange filings, RSS, Upstox news, macro, calendar) | `home-event-sources.md` | gated: design approval | Doc status: "brainstorm in progress. Not approved. No code written." EGM review 2026-11-10: NOT READY (8 blocking items, `docs/progress/home-event-sources-review.md`). Recorded so far: open items (Upstox terms, MoSPI time, FRED IDs), retention (3 years, all rows), gates, NSE/BSE request policy (random 5-8 s gap, 429/403 backoff, 24 h kill switch), licence wording (personal use only). Blockers 5-8 answered 2026-11-10 (scope split into separate docs; build specs in each split doc; merge both keyword lists; mcap_cr; beat/miss/in line; RSS OFF with freshness while running). Factual fixes applied (basis label, factors_matched, "3.3"). Order-win reconciliation written (overview 6.1). 5-8 s gap confirmed. Split draft docs written: `home-events-filings.md`, `home-events-news-telegram.md`, `home-events-upstox-news.md` (blocked on Upstox terms), `home-events-macro-calendar.md`. All four are draft, not reviewed, not approved. Still open: each split doc's build specs and review, and the `factors.py` term changes (reviewed one by one). Status line unchanged. |
| 14 | Upstox ROA, Quick Ratio, EV/EBITDA definitions | `fundamentals-upstox-secondary.md` ("Open before build") | blocked: needs user | Needs written answer from Upstox support. These three fields must not be used until each passes. |
| 15 | Upstox News redistribution terms | `home-event-sources.md` 4.1 and 5.4 | blocked: needs user | Needs written confirmation from Upstox. |
| 16 | Screener password rotation | `secrets-and-roles.md` decision 13 | blocked: needs user | Needs the deadline date from the user. Rotation is a manual user action. |
| 17 | Fundamentals tables (stock-page tables) | `fundamentals-tables.md` | gated: design approval | Doc status: "draft, awaiting approval." |
| 18 | ROE and ROCE basis confirmation (Reliance check) | `fundamentals-upstox-secondary.md` | not started | Needs a second stock check. Not a build task. Upstox ROE and ROCE are not used as a cross-check until done. |

## Rollback points

No task has been merged by this run. No `pre-task-*` tag has been created. No database backup has been taken.

## Concerns and open points

1. **Design gate.** Items 5–8 and 13 and 17 are gated by an explicit approval step in `CLAUDE.md` (the user approves the design before any task is dispatched). The run has not dispatched any of them.
2. **S6 undefined** (item 9). The brief lists S2–S6; the plan defines S2–S5 only.
3. **Path mismatch.** The brief says to reindex synaptree with `root_path` `/workspace/Market-Scanner`. This checkout is on the Windows host at `C:\Users\vaibh\Downloads\Projects\Market-Scanner`. The reindex path must be the host path, not the container path. Not run yet.
4. **Haiku subagents and tokenfrugal.** The brief routes execution to Haiku subagents and the project `CLAUDE.md` routes routine work to `tokenfrugal.dispatch_task`. No tokenfrugal tool is loaded in this session. Not used.
5. **Ledger is uncommitted.** This file is in the working tree only. Commit it on its own docs branch when the user says so.

## Run summary (2026-11-10)

- Merged: PR #70 (S2, merge `e9f31bd`), PR #71 (S3 and S4, merge `314e655`). Both are merge commits. Both branches deleted.
- Offline suite on `origin/main` after PR #71 (checked before the merge): **1174 tests, OK (skipped=12)**.
- Reindexed synaptree (`Market-Scanner`, host path): 333 files, 0 failed. New symbols `put` and `cmd_import_env` are in the index.
- Live changes: migration 045 applied to `market_scanner`; three app secrets imported and checked. Two backups are in `data/backups/`.

## Corrections to this ledger

- The Postgres container is `market-scanner-postgres`, not `scanner-postgres`. The database is `market_scanner`. `POSTGRES_DB` inside the container is `postgres` (empty), so a backup without `-d market_scanner` captures nothing. The first attempt produced a 695-byte file, which was discarded.
- The UI container runs an older image without the new code, and the key folder is mounted there at `/run/app-keys`. The live import ran from the host venv through `scratchpad\run_secrets_cli.py`, which loads `.env` in-process and does not print its values.
- Work was done by the orchestrator directly, not through Haiku subagents. No tokenfrugal tool was available. The EGM six-lens review was not rerun: the S2–S5 design was approved by the user on 2026-11-10.

## Still open

- **S5 (loaders):** not started. Decision 10 needs a service-token internal endpoint in the API, plus changes to the collector and first-run code that read secrets from `secrets_store`. This needs a design decision on the token mechanism before it is built.
- **Item 9, S6:** still undefined.
- **Item 12, analytics-token alert:** the user accepted the defaults (30, 7 and 1 days before expiry, plus expiry day; failure alert on 401/403). Not built. The bot token and group chat ID still need to be entered through the secret store, not chat.
- **Item 11, fundamentals secondary build:** the user replied "ok" to the open items. Not built. The "Open before build" items are unresolved: the ROE/ROCE basis check, the Quick Ratio name, and the Upstox rollback rule.
- **Items 14–16 (blocked):** stay blocked until the above tasks are done, per the user's answer.
- **Plaintext `data/secrets.env`:** still present. Deleting it needs your explicit yes.
- **Ledger is uncommitted** on the main working tree. It should go on a docs branch when you say so.
- **`test` and `rotate` CLI commands** (decision 11) are not built.

## Run 2 (2026-11-10): orchestrator loop, status at stop

Stop reason: every remaining item needs a decision or input only the user can give. No new branch, tag or merge was made in this run.

| # | Status | Reason |
|---|---|---|
| 8 (S5 loaders) | blocked: needs user | Decision 10 requires a service token for the collector and Telegram sender, but does not say where the token is stored or how a service gets it at startup (the bootstrap problem). Needs a choice. |
| 9 (S6) | blocked: needs user | Not defined in any plan file. |
| 11 (Upstox fundamentals build) | blocked: needs user | Decision 1 names ROA, EV/EBITDA and Quick Ratio as the fields Upstox is used for. All three are blocked (items 14 and the Quick Ratio name). The fallback mechanism would have no verified field to fill. Still open: cache lifetime, rollback removal of bad Upstox rows (who runs it), and the "not applicable" and ROE/ROCE rules marked "needs your OK". |
| 13 (home event sources) | gated: design approval | Doc status "not approved". The loop may not dispatch without approval. |
| 17 (fundamentals tables) | gated: design approval | Doc status "draft, awaiting approval". |
| 14, 15, 16 | blocked: needs user | Unchanged (Upstox answers, news terms, Screener rotation date). |

Test count at stop: 1185 tests, OK (skipped=12), on `main` at `8f8182e`.
Open concerns: the `.env` parse warning at line 36 (from the migration run; values not printed). The brief's reindex path `/workspace/Market-Scanner` and backup container `scanner-postgres` are wrong on this host; use `C:\Users\vaibh\Downloads\Projects\Market-Scanner` and `market-scanner-postgres` with `-d market_scanner`. No tokenfrugal or Haiku subagent was used in this run, so there are no fallback entries to log.

## Run 2 answers (2026-11-10)
- S5 service token: approved, file mounted at `/run/app-keys`, collector requests values from the API (secrets-and-roles.md, decision 15). S5 build is next and not started.
- Item 11: wait for Upstox answers (stays blocked). Cache lifetime 24 hours. Bad Upstox rows removed by a manual SQL delete with a backup.
- Items 13 and 17: not approved yet. See the final message for what's needed.
- Item 17 (fundamentals tables): approved by the user on 2026-11-10 without the six-lens review (user's decision). Build not started.
- Item 13 (home event sources): still not approved.

## Home events filings build (2026-11-10)

Design `docs/designs/home-events-filings-spec.md` revision 4 **approved by the user on 2026-11-10**. Review reports: `docs/progress/home-events-filings-spec-review*.md` (review 3 synthesis compiled by the orchestrator, not `egm:egm-synthesizer`).

Routing note: the `tokenfrugal` MCP is not connected in this session, so `plan_add` and `dispatch_task` were unavailable. Execution is by Haiku subagents (global rule), each in its own git worktree and branch `feat/home-filings-<task>` cut from the committed `main` tip `10b25cd`. No commits are made by the agents (standing rule: commits only when the user asks). `pre-task-*` tags are created at merge time.

| Task | Branch | Status |
|---|---|---|
| T2a events DB migrate plumbing | feat/home-filings-t2a | built by Haiku, verified by orchestrator: full suite OK (skipped=12), diff read (db.dsn/connect dbname, migrate target/apply_on/--db, events SQL matches 4.1, no GRANT, pgschema class-cleanup fix). Caveats: DB test `apply_events_creates_table` skips in isolation (Postgres config only loaded in the full-suite process); down file not run; possible leaked empty `test_<hex>` schema from the agent's first crashed run, to be checked. Uncommitted. |
| T3a `scanner/home_events.py` start | feat/home-filings-t3a | built by Haiku, verified by orchestrator: 3/3 new tests, full suite OK (skipped=12); uncommitted, worktree `.claude/worktrees/agent-adf8f393e6aae44e8`; baseline had 3 flaky `tests.test_mongo` failures (not caused by T3a); awaiting your commit/merge go-ahead |
| T4a `_valid_param_keys` | feat/home-filings-t4a | built by Haiku, verified by orchestrator: diff read (+4 settings.py, +11 test), targeted 32 tests OK, full suite OK (skipped=12). Agent's run 1 had 6 failures + 1 error that did not recur (flaky under parallel suites; watch before T4d). Uncommitted. |
| T5a `homeEventsBatch.ts` | feat/home-filings-t5a | built by Haiku, verified by orchestrator: 7/7 tests, tsc clean (uncommitted, worktree `.claude/worktrees/agent-a78dd32abc729a5e4`); awaiting your commit/merge go-ahead |
| T0 NSE samples | none | blocked: needs a network path NSE accepts (user) |
| T1 registration migration | none | blocked: migration number from the split spec |
| T2b, T3b, T3c, T4b to T4e, T5b, T5c, T6, T7, T9 | none | waiting on their dependencies (spec section 9) |

### Wave 1 merged (2026-11-10)

User answered "you decide best" on committing and said wave 2 follows the spec's sequence. Committed, pushed, PR'd and merged by a Haiku agent with merge commits; no CI is configured on the repo. Each branch was cut from 10b25cd.

| Task | PR | Commit | Merge commit | Rollback tag (local, not pushed) |
|---|---|---|---|---|
| T2a | 75 | ebeefe2 | a69ff1f | pre-task-11 (10b25cd) |
| T3a | 76 | f8f0cef | bf4a95f | pre-task-12 (a69ff1f) |
| T4a | 77 | 7c48bec | ab0ae83 | pre-task-13 (bf4a95f) |
| T5a | 78 | b34938e | 83856a5 | pre-task-14 (ab0ae83) |

Verified by the orchestrator on origin/main 83856a5 in a fresh worktree (no `.env`, so the Postgres tests skip, skipped=62): offline suite OK; server vitest 16 files, 163 tests passed; `tsc --noEmit` exit 0. PR 75 was first created with a body that wrongly said the suite had run; the agent corrected it before merging. Open: the T5a local worktree could not be removed by `gh` (Invalid argument), cleaned up separately; possible leaked empty `test_<hex>` schema from T2a's first crashed run, not checked; synaptree re-index after merges not done (main checkout is stale and dirty).
