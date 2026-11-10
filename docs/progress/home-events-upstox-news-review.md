# Goldfish Review Report: home-events-upstox-news.md

**Target:** `docs/designs/home-events-upstox-news.md` (83 lines, draft stub)
**Date:** 2026-11-10
**Compiled by:** egm-synthesizer (Sonnet 5.5). No file other than this report was edited. No secret files were read.

## Lenses that ran

| Lens | Status |
| :--- | :--- |
| `egm-design` | Ran (fresh subagent) |
| `egm-codebase-details` | Ran (fresh subagent) |
| `egm-zoom-out` | DID NOT RUN. The harness refused the spawn: "Concurrent subagent limit reached", with an instruction not to retry. |
| `egm-comprehension` | DID NOT RUN (same refusal) |
| `egm-implementation-readiness` | DID NOT RUN (same refusal) |
| `egm-structural` | DID NOT RUN (same refusal) |

This is a two-lens review, not the default six. Two things partly offset the gap. The design and codebase lenses both covered cite checking and build-spec readiness. The synthesizer also grepped the overview for the cites in findings 4, 15 and 17. Gaps that remain: simplicity and scope (is a separate doc justified, is the daily batch the simplest design), a naive-reader pass, and a section-order comparison with the sibling docs. Rerun the four missing lenses if a full six-lens review is required.

Update 2026-11-10: the four remaining lenses have since run; see the section "Second pass" at the end of this file.

## Verdict

**Not ready to write a build spec from. Fix the doc, then take the user decisions listed below.**

The stub is accurate about what it cites. These cites were verified:
- Overview 4.1, 5.4, 7.3, 7.4, 7.7, and 8.2 items 8, 18 and 19.
- The daily-poll exception, which overview 7.3 names at `home-event-sources.md:149`.
- `ui/app/internal_secrets.py:33`, which reads `SERVICE_ALLOWED = {"collector": {"upstox_analytics_token"}}`.
- The `symbol_sector.isin` column.
- The 30-key batch and the 7-day window, which match overview 5.4 (`home-event-sources.md:83-84`).

The defects are of four kinds:
- One internal contradiction (finding 4).
- Missing integration points with the filings spec and the split spec.
- Endpoint facts nobody has recorded, one of which (the instrument key on each item) the installed SDK contradicts.
- A "Missing before any build" list (doc lines 67-77) too short to write a build spec from.

The external blocker is unchanged: written confirmation from Upstox (doc line 10, overview 8.2 item 18).

Counts: 2 Blockers, 15 Majors, 3 Nits (20 findings). Kind: "Fix" means a change to the doc. "Decision" means the user must decide first.

---

## Blockers

### 1. Where the rows go is undefined, and the filings-spec table cannot hold them - Blocker - Fix, after Decision
* **Lenses:** `design`, `codebase-details`
* **Scope:** doc lines 47 and 72; overview 6.3; `home-events-filings-spec.md` 4.1, 4.6, D8, D9; `collector-split-spec.md` 4.5
* **Discrepancy:** The doc defers to "overview 6.3" for event rows and says the table name is not chosen. It never says:
  - which database holds the rows,
  - how the collector writes them,
  - whether items pass through the news intake queue and the LLM relevance stage first.

  Overview 5.4 ("symbol known before the relevance check", section 6.1) implies they do. Overview 7.7 may build Upstox before or with the LLM stage, so no gate may exist yet.

  The filings-spec `home_events` table cannot hold news:
  - `exchange` is `CHECK IN ('NSE')`.
  - `isin` is `NOT NULL`.
  - There is no news `event_type`.
  - There is a `feed_tier` enum.
  - There is one `symbol` column.
  - There is no summary column (the split spec's section 3 lists the summary field as still open).

  Overview 6.3's event fields (event_id, classified_at, symbols, sectors, stance, model_id, prompt_version, status) match neither the filings table nor anything built. No events DDL exists in the repo (no `db/events_migrations/`, no `homeEvents*.ts`).

  Under D8, D9 and split 4.5, only Fastify touches the events database. The `upstox_analytics_token` is served only to the collector role. So the poller must run in a collector container and write through a Fastify ingest endpoint. It cannot run inside Fastify. The doc says none of this.
* **Recommendation:** Decide one of these routes:
  - (a) queue, then LLM, then event row
  - (b) a new events-DB table with its own migration
  - (c) widen `home_events` by migration

  Then state:
  - the feed tier and event type Upstox items take (overview 7.1),
  - the Fastify endpoint and its auth (a poller token distinct from `home_events_ingest`, or an explicit decision to share it),
  - the build dependencies (filings T2a, T2b, T5; split S1a, S2, S3, S4, S5a; news-telegram DDL if the queue is used),
  - that the poller runs in a collector container and posts through the API.

  Fix the overview 6.3 versus filings-spec schema drift first.

### 2. Endpoint facts are unrecorded, and the instrument key may not be on each item - Blocker - Fix (evidence), plus Decision on attribution
* **Lenses:** `codebase-details`, `design`
* **Scope:** doc lines 24-29, 38, 45; overview 5.4 (`home-event-sources.md:83`)
* **Discrepancy:** The only recorded live test is `positions` and `holdings` returning 0 records. No successful `instrument_keys` call and no response sample is recorded. The fundamentals doc, by contrast, keeps `tests/fixtures/upstox/key_ratios_tcs_INE467B01029.json`. Unrecorded:
  - field names and the format and timezone of `published_time`,
  - whether an article carries one key or several,
  - the source of the 30-key limit,
  - whether the endpoint paginates,
  - the source of "about the last 7 days".

  Three problems follow:
  - The installed SDK (`.venv/Lib/site-packages/upstox_client/models/news_item_data.py:31-35`) defines an item with only heading, summary, thumbnail, article_link and published_time. There is no instrument key field. The SDK types `data` as a generic object, so the live payload may differ, but nothing in the repo confirms the key is present. If it is absent, a 30-key batch cannot attribute an article to a symbol. The fallbacks are one request per key (about 751 a day, which the existing limiter can absorb) or symbol extraction in the LLM stage.
  - The SDK `news_api.py:45-48,108-111` shows `page_number` and `page_size`, and the response has `metadata.page` with `total_pages` and `total_records`. Thirty stocks over 7 days can exceed one page. Without a paging rule, the claim "a daily poll loses nothing" (overview 5.4 and 7.3) is unproven.
  - The `positions` and `holdings` calls returned empty with no error. The doc must define how "no news" differs from "broken". One option is that zero items across all keys for N polls counts as a failure. Otherwise the feed can go silently empty, a risk the fundamentals doc already names.
* **Recommendation:** Add a capture step like the filings spec's T0:
  - one live call, with the sample kept out of git while the licence is unconfirmed,
  - a field table written into the doc,
  - a page-size and paging rule (loop over `total_pages`, what a failed page does),
  - the empty-feed rule.

  Decide how the symbol is attributed if the key is absent. Decide whether a sample may be captured before the confirmation arrives.

---

## Majors

### 3. `article_link` dedupe conflicts with the retention and queue rules - Major - Decision
* **Lenses:** `codebase-details`, `design`
* **Scope:** doc lines 40, 45; overview 6.1 step 5, 6.2, 7.4, 8.2 item 3; `home-events-news-telegram.md:81`
* **Discrepancy:** A daily poll returns the same 7 days each time. Rejected items are kept only as counts, and queued items expire at 48 hours. Any rejected or expired article is therefore absent from every table. It re-enters the queue and goes to the LLM up to 7 times. Overview 8.2 item 3 (a 30-day hash of rejected rows) is only "proposed", and the news-telegram doc owns it. Also:
  - If one article tags several instruments, or appears in two batches, a dedupe on `article_link` alone drops the second symbol.
  - Link normalisation (tracking parameters) is undefined.
  - Cross-source dedupe with RSS and Telegram exists only if items go through the queue.
  - The first poll can bring up to 7 days of backlog, and items older than 48 hours would expire unprocessed. State whether expiry counts from insert or from publish.
* **Recommendation:** Decide:
  - the dedupe key: link only, or (link, instrument_key). Use the filings convention of a source prefix plus hash (filings spec 4.2).
  - a seen-links store, or adoption of item 3 for this source, with the doc stating the dependency on it.

### 4. Stale and inconsistent poll-cadence text - Major - Fix
* **Lens:** `design`
* **Scope:** doc lines 39 and 73; overview 5.4
* **Discrepancy:** Line 39 says the cadence is "once a day. Resolved 2026-11-10". Line 73 (build-spec item 3) still says "poll cadence (to be set)". The date "2026-11-10" is attributed to overview 5.4, which carries no date for it. The cadence is never expressed in buildable terms (cron, time of day).
* **Recommendation:** Reconcile line 73 with line 39. Specify the cron slot and time of day, and its interaction with the split spec's due rule.

### 5. "Loses nothing" is conditional on collector uptime - Major - Fix
* **Lenses:** `codebase-details`, `design`
* **Scope:** doc line 39; overview 5.4 (`:84`) and 7.3 (`:149`); `collector-split-spec.md` 4.2 and risk 5
* **Discrepancy:** The split spec runs only the latest missed slot. If the collector host is off for more than about 7 days, articles are lost. The doc and overview 7.3 say the daily poll "loses nothing" without this condition.
* **Recommendation:** State the limit in the doc. Consider whether the overview wording needs the same qualifier. The overview is owned elsewhere, so that is a note for its owner.

### 6. "OFF until confirmation" has no enforcement mechanism - Major - Decision
* **Lenses:** `codebase-details`, `design`
* **Scope:** doc lines 12 and 71; overview 5.4; `db/migrations/001_core.sql:84`; split spec 4.2
* **Discrepancy:** `collector_settings.mode` allows only `scheduled` or `manual`. A `manual` source can still be started by a UI "Run now" through `collector_requests`. So "OFF" cannot be expressed with the existing mechanism.
* **Recommendation:** Decide the guard. Options:
  - Do not register the source in `SOURCES` or `config/collector_services.json` until unblocked.
  - Add a default-disabled param that the run checks first (mirror the filings spec's `default_enabled`).

  Decide also whether build specs may be written now with the source disabled (cheap, leaves one switch to flip).

### 7. No integration with the collector-split spec - Major - Fix
* **Lens:** `codebase-details`
* **Scope:** doc lines 39, 67-77; split spec 4.3a, 4.5, M9, S2; `scanner/collect/settings.py:195`
* **Discrepancy:** A new events source needs the following, and the doc names none of it:
  - `events_source = True` and the API-health skip (`api_unavailable`), per split 4.5 and filings 5.1.
  - An `upstox` row in `exchange_cooldown` (split 4.3a, S2).
  - An `exchange` field in `config/collector_services.json`.
  - A `collector_sources` registration migration (pattern in migrations 039 and 041; the number is claimed in the split spec).
  - A cron.
  - An entry in `_valid_param_keys` (`scanner/collect/settings.py:195`), which rejects all params of an unknown source.

  Split M9 assigns home-events source schedules to the filings spec plan, and Upstox is not covered there.
* **Recommendation:** Add these items to the "Missing before any build" list.

### 8. Client and transport not chosen; reuse candidates not named; "gap and cap not set" is partly stale - Major - Decision, then Fix
* **Lenses:** `codebase-details`, `design`
* **Scope:** doc lines 24, 49-54; `fundamentals-upstox-secondary.md` (item 6 and "Reuse was missed"); `scanner/upstox.py`
* **Discrepancy:**
  - Line 24 says "the News endpoint of the official SDK" but gives a raw URL. The fundamentals doc requires the SDK (`upstox-python-sdk` 2.30.0). The same doc also says to extend `UpstoxClient`. The SDK is in `.venv` only: there is no `upstox` in `requirements*.txt`, so it is not in the collector image. The SDK's `news_api.get_news` exists locally.
  - A plain urllib call gets an HTTP 403 from Cloudflare (fundamentals doc item 6). A requests-based call must keep `UpstoxClient`'s headers.
  - `UpstoxClient._get(url, params)` is generic. It already has Bearer auth, a multi-window limiter (`RATE_LIMIT_WINDOWS` at 40/s, 400/min, 1600 per 30 min, which is 80% of the assumed "Other Standard APIs" class) and 429 handling with escalating cool-down. `quote_ohlc` is the batch-method pattern (ValueError above `QUOTE_BATCH_SIZE=500`). `instrument_key()` is at `upstox.py:110`. A News call is one new method plus a `NEWS_BATCH_SIZE = 30` constant. `_collect_each` (`sources.py:16`) is per-symbol, so it is not the batcher.
  - At 751 keys and 30 per call, the daily poll is about 26 calls plus pages, far below every window. The News-page class check (item 19) therefore matters little, and "per-host gap and cap not set" (line 54) overstates the gap.
* **Recommendation:**
  - Decide SDK versus `UpstoxClient`. For the SDK, add a dependency change to `requirements.txt`, `requirements.lock.txt` and the Dockerfile.
  - Name the reuse, and state the call volume.
  - Update overview 7.3's table row (`:158`) and 5.4 accordingly (note for the overview owner).

### 9. Token and expiry handling is one line; failure states missing - Major - Fix
* **Lenses:** `codebase-details`, `design`
* **Scope:** doc lines 31-34; `scanner/upstox.py:295`; `scanner/expiry_alerts.py:121`; `secrets_cli.py:40`; split 4.3
* **Discrepancy:** The doc does not say what happens on:
  - HTTP 401 or 403. `UpstoxClient._get` raises `UpstoxError("HTTP 401 ...")` with no structured status code.
  - `SecretUnavailable` from `service_client.fetch_secret` (404 or 503).
  - 429. Does it set the split spec's `upstox` cooldown row?

  `alert_auth_failure(conn, key, today, status_code)` and `check_expiry` exist, but no production code calls them (`grep` shows tests only). A poller cannot call them without parsing the message or adding a status attribute to `UpstoxError`. The token expires 2027-05-18 (`secrets_cli.py:40`). The token is a single point of failure for all Upstox sources. The Cloudflare 1010/403 from non-SDK clients must not map to an auth-failure alert or start the shared cooldown the way the split rule treats an NSE 403.
* **Recommendation:** Add a failure-state list (failed request, 401/403, no data, key without ISIN) mirroring the fundamentals doc. State that News relies on the shared expiry alert and does not build its own.

### 10. Retention is cited as policy but nothing enforces it; ownership wording is inconsistent - Major - Fix
* **Lenses:** `design`, `codebase-details`
* **Scope:** doc lines 6, 18, 47, 62-63; overview ownership table (`home-event-sources.md:26`); filings spec 5.5 (Z5); overview 8.2 item 4; `scanner/retention.py`
* **Discrepancy:**
  - `scanner/retention.py` purges only the Mongo docstore. The events-database purge is deferred (Z5, item 4), and the planned design is a purge inside the `home_filings` run, which does not cover another table or source. "3-year retention, same as other sources" is a policy, not behaviour.
  - The doc (line 6) says retention is owned by the overview. The overview's ownership table says `home-events-filings.md` owns retention and the overview holds the value.
  - 3 years is decided before the licence is known.
* **Recommendation:** State where Upstox rows are purged. Mark retention "subject to the terms Upstox confirms". Align the ownership wording.

### 11. 1-week age limit is likely a no-op - Major - Decision
* **Lenses:** `design`, `codebase-details`
* **Scope:** doc line 41; overview 8.2 item 8, 6.2
* **Discrepancy:** The endpoint returns about 7 days, so a 1-week limit filters almost nothing. It matters only for boundary jitter or a backfill. What it is measured against (`published_at` or fetch time) is undefined. It interacts with the 48-hour queue expiry (finding 3).
* **Recommendation:** Decide whether to keep it. If kept, state it is a near no-op and what it measures. Item 8 also bundles "OFF by default" (see finding 6).

### 12. Stored-fields list omits `published_time`; the cite for the instrument key is slightly off - Major - Fix
* **Lens:** `codebase-details` (also `design`)
* **Scope:** doc lines 43-47; overview 5.4 (`:83` and the stored-fields line near `:85`)
* **Discrepancy:** `published_time` is needed for the age limit, for retention, and for `published_at NOT NULL` in the filings events table. Its timezone and format are unknown (the filings spec handles this with T0 samples and `zoneinfo`). Doc line 45 lists the instrument key as a stored field and cites 5.4. Overview line 83 says each item carries its key, but the stored-fields list at about line 85 does not include it. Also state that no publisher page is fetched (unlike Telegram, overview 7.6).
* **Recommendation:** Add `published_at` and the publisher name if the response provides one. Fix the cite or add the key to the overview list.

### 13. Universe and capacity not defined - Major - Decision, then Fix
* **Lenses:** `codebase-details`, `design`
* **Scope:** doc lines 25-26; overview 6.1; `db/migrations/025_symbol_sector.sql:9`; `scanner/symbol_sector.py:75-76`; filings spec D3
* **Discrepancy:**
  - "Watchlist and scanner universe" is ambiguous. The watchlist exists only in the browser (`ui-v2/src/shell/watchlistStore.ts`), not in any server or collector table. The filings spec D3 uses the 751 `symbol_sector` rows with an ISIN. The shortlist is about 39 names, so 751 is an extension.
  - The prefilter passes any item carrying a universe symbol. The first poll can send up to 7 days of articles for 751 stocks to the local LLM. Volume and LLM time per item are not estimated.
  - `isin` is nullable and not unique. A stale ISIN gives an empty result with no error and no count. ISINs can change (`isin_history`, `symbol_alias`, migration 012).
* **Recommendation:** Define the universe as `symbol_sector` rows `WHERE isin IS NOT NULL` (reuse the filings spec's `load_universe()`, spec only so far). Estimate the volume. Define how an instrument key maps back to a symbol, and how missing or stale ISINs are surfaced.

### 14. The unblock criterion is vague - Major - Fix, then Decision
* **Lens:** `design`
* **Scope:** doc lines 8-13, 56-58; overview 4, 4.1, 8.2 items 15 and 18; `ui-redesign-spec.md` section 9 decision 1
* **Discrepancy:**
  - The doc does not define the question to ask Upstox. It should cover: store, show, retention length, passing summaries to a local LLM, and the overview 6.2 case where `LLM_URL` moves to OpenRouter.
  - It does not say who records the answer, or that it goes into overview 4.1 and 8.2 item 18.
  - The confirmation may not cover the underlying publishers' content, since Upstox News is likely syndicated.
  - The Upstox API terms and developer agreement are not in the "terms not read" list (overview 8.2 item 15).
  - It does not explain why Upstox is blocked while NSE, BSE and the RSS feeds are accepted at the user's risk (overview 4).
  - `ui-redesign-spec.md` section 9 decision 1 is a separate Upstox data-sharing licence check. One inquiry could cover both.
* **Recommendation:** Write the question list and recorder into the Blocked section. Add the Upstox API terms to the unread list.

### 15. Build-spec "Missing" list is incomplete - Major - Fix
* **Lenses:** `codebase-details`, `design`
* **Scope:** doc lines 67-77
* **Discrepancy:** Compared with the filings spec's contents, the list is missing:
  - the events path and its dependencies (finding 1),
  - the page-size and paging rule (finding 2),
  - the registration migration, `_valid_param_keys` and cron (finding 7),
  - config keys for the cron, `request_timeout_s`, the retry and backoff after 429 or 5xx, and the `enabled` switch,
  - fixtures (synthetic only while the licence is unresolved),
  - failure semantics (findings 2 and 9),
  - the OFF guard (finding 6),
  - a note whether a failed batch is retried at the next daily poll.

  Item 3 says poll cadence is "to be set" (see finding 4). Item 6 repeats line 28. A build spec also needs a Create/Modify/Delete marker per file.
* **Recommendation:** Extend the list. Add one note that the file targets are not yet chosen.

### 16. Where the stub sits relative to the overview: values owned in name only - Major - Fix
* **Lenses:** `design`, `codebase-details`
* **Scope:** doc lines 3, 20-58, 60-65; overview section 2 and 5.4
* **Discrepancy:** Everything under "Owned rules" is a restatement of overview 5.4 with a cite back to it, and drift has already occurred (finding 4). The status line says "sections 7 and 8", but the rules cited are 4, 5.4 and 6. Overview section 2 says the overview holds these values until the owning doc is updated.
* **Recommendation:** Add one line: "overview 5.4 governs until the values move here", or make the stub the single owner and have the overview point to it. Decide which.

### 17. Stale cite in another document - Major (low effort) - Fix (outside this doc)
* **Lens:** `design`
* **Scope:** `docs/progress/execution-ledger.md:39` (verified by the synthesizer)
* **Discrepancy:** The ledger row 15 cites `home-event-sources.md` 4.5 for Upstox News terms. The content is now at overview 4.1 and 5.4. This is outside the target doc, but the cite is to a section that no longer matches.
* **Recommendation:** Update the ledger cite. The document owner decides whether this review covers it.

---

## Nits

### 18. "751 rows, all with an ISIN" is a standing fact - Nit - Fix
* **Scope:** doc line 25; `025_symbol_sector.sql:9`
* The column is nullable. The count comes from the fundamentals doc (checked 2026-11-10) and cannot be confirmed from the repo. Rewrite as "as of 2026-11-10" and specify `WHERE isin IS NOT NULL`.

### 19. "Role" wording for the token - Nit - Fix
* **Scope:** doc lines 33-34; `secrets-and-roles.md`; `ui/app/internal_secrets.py:60`
* In `secrets-and-roles.md`, roles are admin and named user. The code checks a single service token mapped to "collector". A second service identity (for example a separate poller or the Fastify ingest token) is not supported by this endpoint. Say the poller runs under the collector token. Fastify also reads an Upstox token from env or `data/secrets.env` (`server/src/index.ts:30`, `secrets.ts`), so "only the collector" holds only for the secrets endpoint.

### 20. Open list omits items; duplicated batch-failure line - Nit - Fix
* **Scope:** doc lines 28, 76, 79-82; overview 8.2 items 9 and 18
* The "Open" list omits overview 8.2 item 9 (per-host gap and cap, which line 54 mentions) and does not list item 18 (the blocker). The batch-failure item appears at both line 28 and line 76. Also, the Scope line (17-18) repeats the overview.

---

## Items for the user to decide

1. Storage route and table (finding 1).
2. How the symbol is attributed if items carry no instrument key (finding 2), and whether a sample may be captured before confirmation.
3. Dedupe key, and whether to adopt a seen-links store or overview 8.2 item 3 (finding 3).
4. How "OFF" is enforced (finding 6), and whether build specs are written while blocked.
5. SDK versus `UpstoxClient` (finding 8).
6. Keep or drop the 1-week age limit (finding 11).
7. Universe definition (finding 13).
8. Who owns the values: this stub or the overview (finding 16).

## Everything else is a fix to the doc

Findings 4, 5, 7, 9, 10, 12, 14 (question list), 15, 17 (ledger), 18, 19, 20, and the evidence capture in finding 2.

## Second pass: the four missing lenses (2026-11-10)

Revision reviewed: `docs/designs/home-events-upstox-news.md` as rewritten on 2026-11-10 after the events-database storage decision (149 lines).

Method: `egm-zoom-out`, `egm-comprehension`, `egm-implementation-readiness` and `egm-structural` ran as fresh read-only subagents, two at a time because of the concurrent-subagent limit. The `egm-synthesizer` was not used; the orchestrator compiled this section from the four reports, so treat it as a single-author synthesis. With the earlier design and codebase-details lenses, all six lenses have now run.

None of the findings below has been applied to the doc yet. Findings that need a user decision are listed in `docs/progress/home-events-decisions-needed.md`.

### Zoom-out (simplicity and scope)

**Verdict:** the doc is too big for a source blocked on a licence answer and built last (overview 7.7). About 60 percent is "to be set" bullets, restated overview rules and a build-spec checklist that cannot be worked yet. Proposed size about 50 lines.

**Major**

1. Lines 36-43, 126, 133, 140: the doc proposed a second ingest route and token role for the same table as the news doc, a shared route, replaced by per-source routes under A1 (decided 2026-11-10). Fix: the Upstox doc now has its own route and token role (proposed), and the news doc, `secrets-and-roles.md` and overview 6.3 list it. Status: resolved by A1, pending the build spec.
2. Lines 96-105, 120-134, 136-148: pre-spec checklists that cannot be actioned. Failure states has 8 bullets, 6 "to be set"; the 11-item Build specs list mostly restates lines 28-105; Open duplicates the decisions file and the review (three homes for one list). Fix: keep three gates (terms confirmation, captured sample, user decisions); replace Failure states with one line plus the two Upstox-specific cases (stale ISIN, zero items); keep Open as a pointer. Decision: do build specs wait until the blocker clears (recommended: yes).
3. Lines 29-34 and 126: earlier finding 3 (dedupe) is mostly solved by the storage decision; terminal `event_intake` rows live 14 to 30 days, longer than the 7-day window. Fix: dedupe on the intake hash owned by the news doc, `article_link` as hash input, instrument key in the jsonb payload; drop the seen-links store and the (link, key) question unless the sample shows one article with several keys.
4. Lines 41, 76, 145: the 1-week age limit (earlier finding 11) does nothing because the endpoint returns about 7 days. Decision: drop it, or say it is a no-op.
5. Lines 56, 84-90, 100-102, 144: the client choice (earlier finding 8) drives about 15 lines of branching text. `UpstoxClient._get` (`scanner/upstox.py:269`) already has the multi-window limiter, 429 escalation and a batch-method pattern (`quote_ohlc`), with no new dependency; the SDK adds `upstox-python-sdk` to three files. About 26 calls a day does not need a per-host gap or a Cloudflare-403 mapping. Decision: pick `UpstoxClient._get`, with the sample capture as the check that a requests-based call is not 403'd; collapse Rate limit to 2 lines.
6. Lines 100, 102, 132 (item 9): the `upstox` row in `exchange_cooldown` and the `exchange` field are speculative for 26 calls a day. Cut unless the split spec requires it for every source; `UpstoxClient` 429 escalation is enough. Decision: confirm with the split-spec owner.
7. Lines 28-34 and 142: earlier finding 6 (OFF enforcement) has a zero-code answer: do not register the source in `SOURCES` or `config/collector_services.json` until unblocked. That removes the `enabled` key, the `default_enabled` mirror and the line 143 question. Decision: confirm.
8. Lines 57, 146: earlier finding 13 (universe). Full universe is 751 stocks, about 26 calls, and the first poll can push 7 days of backlog for 751 names to the local LLM; the shortlist is about 39 names, 2 calls. Decision: shortlist or full `symbol_sector` set; if full, cap or skip the first-poll backlog.
9. Whole doc (news doc finding M12): does a separate file earn its keep? The overview ownership table names this doc as owner, so keep the file but shrink it; alternative is a roughly 15-line "Upstox source" section in the news doc. Decision: keep a roughly 50-line stub, or fold it in.

**Nit**

10. Lines 45-50 and 113-118 repeat header cites; delete both sections. Retention (107-111) can be 3 lines.
11. Lines 61, 67, 99, 104, 142: "per the review" ties a design doc to a transient progress file; state facts or mark unverified. Lines 87-88 are review history; delete.
12. Lines 66-68, 87, 99, 132: code-level file:line cites will go stale; move to the build spec. Line 67 (Fastify env token) is out of scope; line 68 is filler.
13. Lines 8-20: the Blocked section is 13 lines. The Upstox question list (14-18) is the useful part; trim lines 10-13 to one line and line 20 to one sentence.

**Earlier findings still unresolved after the rewrite** (zoom-out's count): 2 (no captured sample: instrument key per item, paging, `published_time` format unknown; the only real engineering gate), 6, 8, 9 (401/403 alert wiring), 11, 13, 16, 17 (ledger cite, outside this doc, not checked). **Resolved by the rewrite:** 1, 4, 5, 12, 14, 15, 18.

### Comprehension (naive reader)

Overview section numbers cited in the doc (2, 4, 4.1, 5.4, 6.1 to 6.3, 7.1 to 7.4, 7.7, 8.2) all exist. Items 8, 9, 13, 15, 18 and 19 exist and match; item 3 does not match (see Blocker 1).

**Blocker**

1. Lines 49, 142: "dedupe rule (overview 8.2 items 3 and 13)" and "overview 8.2 item 3 for this source". Item 3 is rejected-row retention (30 days, hash and reason), not a dedupe rule. State what item 3 provides, or cite the right item, and say whether the dedupe hash is item 3 or something else.
2. Lines 6, 111 vs 48: the purge owner is cited as `home-events-filings.md` section 5.5 on line 6 and as `home-events-filings-spec.md` section 5.5 on lines 48 and 111. Two different files, same section number. Name one file; use full filenames on first citation; define "filings spec" once.
3. Lines 99, 100: both cover HTTP 403. Line 99 says 401 or 403 is an auth failure; line 100 says a Cloudflare 403 is not. No discriminator is given and `UpstoxError` carries only the status. State the discriminator (body, header or client type) or list it as unresolved in Open.

**Major**

4. Lines 27, 29-34: the heading says "decided 2026-11-10" but the route, token role, relevance stage and tables (`event_intake` 002, `news_events` 003) are proposed or open. Only the storage route is decided. Rename the heading and tag each bullet decided, proposed or open.
5. Lines 87, 88, 148: "the statement that the Upstox per-host gap and cap are not set is not accurate" refers to a statement not in this doc, and line 148 says overview item 9 is still open. Quote the statement and its location; say whether item 9 should close for Upstox.
6. Lines 22-25, 113-118 vs 52, 92-111: "Carried from the overview (not owned here)" lists licence and retention, yet "Owned rules" has a Licence section; retention mixes owned and carried rules; line 147 asks who owns "the values" without naming them. Put each rule under one heading and name the values.
7. Lines 41, 47, 74, 126, 128, 132: undefined tags S2, S3, S4, T2a, T2b, T5a to T5c, "risk 5", "section 5" vs "5", "4.1 to 4.6". Add a one-line gloss on first use or a short glossary.
8. Line 3: "Only 2 of 6 lenses have run": "lens" is undefined and the other 4 are not named.
9. Lines 40, 66: line 66 says the poller adds no new service identity; line 40 adds a token role. They are different credentials (secret-store read vs Fastify ingest); say there are two.
10. Lines 38, 80-82: the ingest body is "rows with the `event_intake` columns", but those columns, the dedupe-hash inputs and the `news_events` columns are all "to be specified". Give a minimal provisional column set marked proposed, or state the contract is blocked on `home-events-news-telegram.md`.
11. Lines 125, 143: circular status. The field table needs a captured sample, but whether a sample may be captured before the licence is confirmed is open; line 3 says specs are not written while line 143 asks whether they may be. Sequence these in one decision.
12. Lines 66, 67: the quoted phrase "Collector only" has no antecedent; the Fastify env read (`UPSTOX_ACCESS_TOKEN`) is raised without saying whether it matters.
13. Lines 73, 76: "the one exception to the schedule in 7.3" does not describe the schedule; the age-limit measurement is only defined in Open.
14. Line 98: "retried per the config keys": the retry keys are undefined (item 4 on line 127 lists them as unset).

**Nit**

15. Line 14: "project owner" vs line 4 "Owner" (same person?).
16. Line 18: bullet not parallel, inconsistent status tags; add a legend of decided / proposed / open / unverified.
17. Line 20: "forum replies conflict" has no source. "The fundamentals doc" (lines 57, 100) has no filename (`docs/designs/fundamentals-upstox-secondary.md`).
18. Line 57: "Category instrument_keys" is a request parameter, and the source of the 30-key limit is not given.
19. Lines 87, 99, 132: line numbers and symbols (`RATE_LIMIT_WINDOWS` lines 89-93, `settings.py:195`, `internal_secrets.py:33`, `index.ts:30`) will drift.
20. Lines 102, 132: Upstox is not an exchange but is described as an `exchange_cooldown` row.
21. Line 110: statuses `rejected`, `expired`, `prefiltered_out` are undefined here.
22. Line 111: "inside the `home_filings` run" is undefined.
23. Line 16: `LLM_URL` and OpenRouter are unexplained.
24. Line 138: "each one is also in ...-decisions.md" cannot be checked from the doc.

### Implementation readiness

**Verdict: No.** A builder could not write build specs and then code from this doc. It is honest that it is a stub and the storage decision is clear, but interfaces, files, config keys, acceptance command and test seams are unspecified.

**Blocker**

1. Lines 38, 40, 126 vs news doc lines 28-31: this doc proposed a route and role that the news doc did not list for Upstox, and the news doc used one shared route for all raw sources. Under A1 (decided 2026-11-10) each source now has its own route and token, so the per-source role question is settled. Status: resolved by A1; the news doc's route list still needs its own check.
2. Lines 29, 38, 81-82 vs news doc line 73: the `event_intake` insert fields (source, URL, published time, normalised title, content hash, og:title, og:description) do not map to Upstox items; no payload shape for the instrument key; Upstox does no page fetch. Add a field-mapping table, blocked on the 002 DDL, which does not exist; build-spec items 3 and 10 cannot close until the news doc writes 002 and the route.
3. Lines 56, 87, 98 vs `scanner/upstox.py` 269-297: the doc says failed requests are retried per config keys and lists `request_timeout_s`, but `_get` hard-codes `timeout=60` and `MAX_RETRIES=5` and retries only on 429; other non-200 raises `UpstoxError` at once; timeouts and connection errors raise `requests` exceptions. Config keys for timeout, 5xx retry and backoff have nothing to attach to. Decide: add a timeout argument and 5xx retry to `UpstoxClient`, or wrap `_get` in the poller; state which exceptions the poller catches.

**Major**

4. Lines 56, 61: the News method is undefined (name, signature, whether batching of 30 lives in the method or the poller, query parameter names). Add a signature block (for example `UpstoxClient.news(keys, page)`) and `NEWS_BATCH_SIZE = 30`.
5. Lines 120-134: no file list. Collector side is determined by existing code: `Source.run(self, params, now=None, dry_run=False)` and `plan()` are abstract (`scanner/collect/sources.py:37-69`), the return dict has `fetched`, `new`, `from`, `to`, `message`, and `SOURCES` at line 616 registers sources. Name the module, subclass, `SOURCES` key, the mapping to `fetched` and `new`, and Create or Modify per file.
6. Test seams: none given. Existing seams are now `Source.run` and `time_func` and `sleep_func` on `UpstoxClient` (`upstox.py:219-225`), but the HTTP session is private so there is no client injection. Specify injection points (fake `UpstoxClient`, fake `post_intake`, fake `fetch_secret`, `now`), the test file and cases, and the offline command.
7. Lines 132, 127: config keys have no names, defaults, units or home; they come from `collector_settings` params validated by `_valid_param_keys`. Give a table and the exact `_valid_param_keys("upstox_news")` set.
8. Lines 33, 38, 41, 132: the poller's secret read and API call are unspecified (`fetch_secret` call, env var for the service token, `EVENTS_API_BASE_URL`, ingest token location). Also batch size and per-request cap for the POST: filings caps a batch at 500 rows (`over_500_rows_rejected`); say whether 751 keys x 7 days can exceed it and how it is chunked.
9. Lines 98, 126-127: run status mapping incomplete: no result (failed, skipped, ok with message) per failure condition and no rule for partial success when some of 26 batches fail; posted batches stay inserted (idempotent). Add a condition / status / message / exit table, open items marked.
10. Lines 128-130: no acceptance command. At least the unit command, a migration check and a manual dry-run (look up the real CLI), plus an opt-in live check separate from the offline command.
11. Lines 45-50: no task ordering; dependencies are listed as documents. Missing: filings T2a and T2b, T5a to T5c, news 002 DDL and intake route task, split S2, S3, S4. T5c waits on `server/src/index.ts` being committed (filings spec line 428).

**Nit**

12. Lines 87-88 cites are correct, but `UpstoxClient` sets `Content-Type: application/json` on GET and the fundamentals doc says non-SDK clients get a Cloudflare 403; whether the News endpoint accepts requests headers is unverified. Add to the live-capture step as a go/no-go for the client choice.
13. Line 67: state that the poller passes `token=` explicitly so the env fallback (`UPSTOX_ANALYTICS_ACCESS_TOKEN`, `upstox.py:234-239`) never runs in the collector.
14. Lines 3, 138: mark which Open items block the build spec and which only block the build.
15. Line 73: cron slot not set, but the split spec's due rule needs a cron string. Give a default (for example one slot after the 20:55 filings close) or mark it a user decision.

### Structural

No blocker. Heading levels are clean. Cites to overview 4.1, 5.4, 6.2, 6.3, 7.3, 7.4, 7.7 and 8.2 items 3, 4, 8, 9, 13, 15, 18 and 19, split 4.1, 4.2, 4.5 and risk 5, and filings spec 4.1, 4.3, 4.5, 4.6 and T2a / T2b / T5a-c are correct.

**Major**

1. Line 6 and line 48: wrong purge owner file. `home-events-filings.md` has no section 5.5; the purge design is `home-events-filings-spec.md` 5.5 (cited correctly on line 111).
2. Lines 38-40 vs the news doc: two proposed ingest routes targeted one table. Under A1 (decided 2026-11-10), each source has its own route and token, so the Upstox route is kept and the shared-route option is dropped. Status: resolved by A1.
3. Line 34: says the keyword prefilter is owned by the news doc. News doc line 79 says the filings doc (overview 9.2), and its Open B7 leaves it open. Name the owner as the filings doc, say open, and keep the LLM stage with the news doc.
4. Lines 57, 127: the 30-key limit is labelled "decided" with no date; it is an API limit with no recorded source. Mark unverified and add to the sample capture.
5. Lines 41, 128, 133: the ingest token location and `EVENTS_API_BASE_URL` are called open but are in neither the Open section nor the decisions file, so line 138's "each one is also in the decisions file" is false.
6. Lines 138, 148: Open list is not item for item with the decisions file. The last bullet (overview 8.2 items 9, 18, 19) is in neither; item 18 is an external blocker. Move it to a "tracked in the overview" line.
7. Lines 52, 147 and decisions Finding 16: the "Owned rules" heading contradicts the Open item "overview 5.4 governs until decided"; line 3 does not carry that sentence as the decisions file says.

**Nit**

8. Lines 8-25 order: Blocked before Scope; Scope repeats line 6. Put Scope first.
9. Line 92: Licence restates lines 20 and 115.
10. Lines 107-111: Retention H2 sits beside Owned rules while Licence is inside; fold in.
11. Lines 75-76: dedupe and age limit sit under Poll and window.
12. Lines 36-41, 63-68 and items 3, 5, 10: the token is stated three times.
13. Lines 124, 126: item 1 duplicates Blocked; item 3 "Migrations: none" is not missing.
14. Lines 130-131: item 7 is a subset of item 8.
15. Line 100: the cooldown rule is split 4.3a, not 4.3.
16. Line 73: "Resolved" vs "decided"; status vocabulary is loose (resolved, assumed, to be set, to be specified, not chosen). Use decided, proposed, open, unverified, plus "to be set in the build spec".
17. Line 33: the poller-in-collector rule sits under a heading "decided 2026-11-10", but the decision covers storage only; cite split 4.1 / 4.5.
18. Line 88 has no antecedent; "per the review" on lines 61, 67, 99, 104 should be a cite or "unverified".
19. Lines 57, 86, 100: "the fundamentals doc" is never named (`fundamentals-upstox-secondary.md`).
20. Line 141 and heading tags mix status with notes.
21. Lines 47-50: Dependencies omits overview 6.1, 6.2, 7.7 and 8.2 items 3, 4, 13 that the body cites.
22. Line 3 carries progress-file pointers and "2 of 6 lenses" text that will go stale.

### Cross-lens overlaps

- (a) The duplicate ingest route is raised by zoom-out 1, readiness 1 and structural 2: one user decision.
- (b) The 401/403 vs Cloudflare discriminator (comprehension 3) and the News-endpoint header check (readiness 12) both wait on the captured sample.
- (c) The purge-owner file mismatch (comprehension 2, structural 1) and the dedupe-item cite (comprehension 1) are doc-only fixes.
- (d) The status vocabulary and Open-list sync (comprehension 4, 16, structural 5, 6, 7, 16, 20) are doc-only fixes.
- (e) The doc-size question (zoom-out 2, 9, 10, 13) conflicts with the readiness lens asking for more detail (items 4 to 11). The two pull in opposite directions, so that is a user decision: shrink to a stub and write detail only in the build spec after the licence clears, or detail now. This is the main tension of the second pass.
