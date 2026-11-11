# Goldfish Review Report

**Target:** `docs/designs/home-events-news-telegram.md` (lines 1-131, referred to as NT)
**Date:** 2026-11-10
**Mode:** REVIEW, default six-lens Elephant-Goldfish review, one fresh subagent per lens, read-only (no file other than this report was edited).

Abbreviations. All design docs are under `docs/designs/`.
- OV = `home-event-sources.md` (overview, amended 2026-11-10).
- FS = `home-events-filings-spec.md` (revision 4).
- CS = `collector-split-spec.md` (read-only, owned by another session).
- SR = `secrets-and-roles.md`.
- Line numbers are tied to the file named next to them.
- "Fix" means an edit to NT (or the named doc). "Decision" means the user must choose first. Where a recommended default is given, it is a proposal, not a decision.

## Lenses that ran

All six ran as fresh parallel subagents, one instance each (no A/B pairs): `egm-design`, `egm-codebase-details`, `egm-zoom-out`, `egm-comprehension`, `egm-implementation-readiness`, `egm-structural`. All returned reports. None read `.env` or `data/secrets.env`; no secret values appear below.

Not verified in this review: the Telegram Bot API fact that unconfirmed `getUpdates` updates are kept at most 24 hours. Four lenses recalled it from memory and none could fetch the page. Treat it as a strong lead to confirm at core.telegram.org/bots/api#getupdates, not as established.

## Verdict

**NOT READY for a build spec.** The stub is honest about its seven missing items (NT 112-122) and is accurate as a gap list. But it has internal contradictions that need a user decision, it never engages FS, CS or SR (which govern the build), and its own missing list is incomplete. Most overview section cites resolve correctly. The wrong ones are listed under findings M1, N1 and N2.

Counts: 8 Blockers, 17 Majors, 9 Nits (34 findings). Of these, 22 need a user decision (some also need a doc fix afterwards), and 12 are pure doc fixes.

## Prioritized findings (Blockers, then Major, then Nits)

### B1. The "RSS keyword-only" phase is undefined and contradicts the LLM-only rule - Blocker (Decision)
- Lenses: all six.
- NT 13 and 58 (built next: "RSS keyword-only"); OV 184 (7.7). NT 60 and OV 98 (section 6): raw RSS items never reach the dashboard, the events table or the API; only LLM-relevant items do.
- With no LLM in that phase a keyword-matched item either shows (breaks the rule) or goes nowhere (the phase delivers nothing, and items then expire at 48 hours, NT 72). Event row fields (NT 79) are mostly LLM output, and the doc says nothing about where symbols come from without the LLM.
- Recommendation: decide one of (a) merge keyword-only RSS into the LLM phase, so RSS stays OFF until the LLM worker exists (implementation-readiness lens recommends this), or (b) let keyword-only items become event rows only on a deterministic rule (beat/miss word, rating term), with `model_id` null and an explicit `status`. Then amend OV 98 and OV 184 and define the phase in NT.

### B2. "Reuse the filings events table" does not fit `home_events` - Blocker (Decision, then Fix)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness, structural.
- NT 82 and 116; FS 130-148 (4.1), FS 204 (4.4), FS 228-241 (D9, 4.6).
- `home_events` has `isin` and `symbol` NOT NULL (single value), `exchange` CHECK `('NSE')`, a six-value `event_type` CHECK, `feed_tier` NOT NULL, primary key `dedupe_key`, and none of `event_id`, `category`, `symbols`, `sectors`, `stance`, `reason`, `classified_at`, `model_id`, `prompt_version`, `status` (the OV 119 list, NT 79). The only endpoint is `POST /internal/events/batch` with a filings validator and one token role. The grant is INSERT-only, which also conflicts with OV 119's "re-run can be compared with the first result".
- "If the events table is approved in the filings doc" (NT 82, 116) is stale: the DDL exists in FS rev 4.
- Recommendation: replace "reuse" with an explicit choice. Option A: widen `home_events` by migration (relax NOT NULL and CHECKs, add columns and an array for symbols). Option B (recommended by the readiness and zoom-out lenses): a separate `home_news_events` table in `db/events_migrations/` (after FS 001) with its own ingest route and token role. Name the table, the route and the token role, and cite FS 4.1, 4.5 and 4.6. Do not claim a migration number (see M3). Multi-symbol rows against the 3-per-stock Home cap (OV 135) are a read-path question for ui-redesign.

### B3. The intake queue has no home, and the events-database rule is never mentioned - Blocker (Decision, then Fix)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness.
- NT 45-50 and 116 ("Queue DDL: not written", "table names not chosen"). FS 230 (D9) and CS decision 3 (CS 14): only Fastify touches the events database; the collector keeps direct access to the main database.
- If the queue is in the events database, every enqueue, claim, mark and expire needs a new Fastify endpoint. If it is in the main database, the RSS fetcher, Telegram reader and LLM worker use it directly and only relevant rows go through the API.
- Recommendation: put the queue and the Telegram offset in the main database, post relevant rows to the API with a deterministic dedupe key such as `news:<sha256(canonical_url)>` (idempotent replay after a crash), and state in NT that `home_events`-family tables are reached only through the Fastify API and that Home reads of the marker and empty-day line also go through the API. Choose table names. A DDL sketch from the readiness lens: `news_intake_queue` with `origin`, `url_hash`, `content_hash`, og fields, `queued_at`, `status` (`queued`, `prefiltered_out`, `relevant`, `rejected`, `expired`, `error`), `attempts`, `terminal_at`.

### B4. "Rejected, prefiltered and expired kept only as counts" contradicts dedupe at queue insert - Blocker (Decision)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness.
- NT 48, 54, 72, 81, 91; OV 102-106 (6.1 steps 2 and 5), OV 150, OV 163 (7.4), OV 207 (8.2 item 3).
- Dedupe runs at insert by URL and content hash, and items are "marked" `rejected` (a stored row). RSS items stay live about a week (NT 23, OV 150). If terminal items are not remembered, the next poll re-queues and re-classifies them every cycle (repeated LLM spend, and a later answer can flip a rejection). So some trace must persist, which effectively settles the OV 8.2 item 3 proposal.
- Recommendation: keep a minimal terminal row (URL hash, content hash, status, `terminal_at`, source) for at least the 7-day RSS window plus margin; the 30-day proposal covers this. Null the title and og fields at the terminal state. Note that a hash alone cannot support a human recall audit, only counts. Decide the retention for queue rows separately from the 3-year rule for event rows (see M5). Fix NT 81 and 91 and amend OV 106 and OV 163 together. Define that the expiry clock runs from `queued_at`, not `published_at` (see M6).

### B5. LLM stage contract and prompt-injection defence are absent, and the premise about `LLM_URL` and the model is not true of the code - Blocker (Decision, then Fix)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness.
- NT 59-65 and 117; OV 217 (8.2 item 13).
- Untrusted input is wider than "headlines": RSS title and description, og:title and og:description from arbitrary pages, URL slugs and Telegram message text.
- Code facts: `scanner/llm.py` already has `LLMConfig` (default timeout 900 s, line 67; `model="qwen3:8b"`, line 65), `parse_json_response` (321), `health()` (401), a JSON-mode payload (351-376) and one global `PROMPT_VERSION = 2` (57). No Python reads `LLM_URL` from the environment (start.ps1:64 reads it and passes `--llm-url`). The compose collector services (`docker-compose.yml`) pass no `LLM_URL`, model or API flavour, and `env.template:45` (`127.0.0.1:11434`) would point at the container itself. The Ollama path sends only `format: "json"`, so enums are not enforced at decode time.
- Recommendation: reuse `scanner/llm.py`, add a news-relevance kind with its own prompt-version constant, and say where `model_id` comes from (a config key, since NT 59 says no name is hardcoded). Name the new config (`LLM_API`, `LLM_MODEL` proposed) and how containers receive it. Specify as required content: batch size (zoom-out suggests 1 item per call, readiness suggests 10 with ids, choose one), timeout (not 900 s), one retry on connection error or 5xx, malformed JSON handling (split to single-item once, then `error` and stay queued until expiry, never counted as `rejected`), and a status when the LLM is down (`skipped`, as `api_unavailable` in CS 95).
- Injection defence to require, all of it structural: untrusted text only in a delimited data block (never the system prompt) with per-field length caps and control-character stripping; the model has no tools, no network and no secrets; code validates every output (`relevant` boolean, `category` in the enum, `symbols` intersected with `symbol_sector`, `sectors` from known values, `reason` plain text capped at 25 words and 200 characters, URLs and markup stripped, unsent `id` ignored, extra keys rejected); `source_url` comes from the queue row, never from model output; the UI must render `reason` escaped (belongs in ui-redesign). Add a fixed hostile-headline test set (about 10) that must not widen `category` or smuggle a symbol.

### B6. Telegram retention, offset durability and chat allowlist are unresolved - Blocker (Decision, plus Fix)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness.
- NT 34-38, 49, 91, 118; OV 177 and 206 (8.2 item 2).
- Recalled (unverified) Bot API behaviour: unconfirmed updates are kept at most 24 hours; an update is confirmed by `getUpdates` with `offset` greater than its `update_id`; `getUpdates` fails (409) while a webhook is set and allows one consumer per token; `update_id` may jump after about a week of silence. If the 24-hour figure is right, it, not the 48-hour delete window (NT 35), is the binding limit: a laptop off for more than a day silently loses links, and the laptop-only hosting premise (NT 34, which is stated as fact while NT 37 says it must not be accepted before the check) is weaker than the doc implies. Verify first and cite it.
- NT never says where the offset is stored, the commit order (recommended: commit queue rows, then advance the offset; at-least-once with dedupe), or the dedupe key. Recommended key: `(chat_id, message_id, url_hash)`; `update_id` is not stable. A precise "gap detector" (NT 49) is not possible from `update_id` continuity; record `last_ok_at` and warn when `now - last_ok_at` exceeds a configured threshold (readiness lens proposes 20 h), without claiming exact loss.
- No sender or chat allowlist: anyone who adds the bot to another group injects URLs that the collector then fetches (see B8) and feeds to the LLM. The reader must accept only the configured link-group chat id.
- Decision: accept the retention limit as a stated known limit, or move to an always-on host. Close OV 8.2 item 2 on this.

### B7. Prefilter ownership, symbol source and Telegram treatment are unresolved - Blocker (Decision, then Fix)
- Lenses: all six touched it.
- NT 54 ("Owned by the filings doc") and 64; OV 28, OV 104, OV 109, OV 226-254 (section 9), OV 244 and 254.
- Ownership points the wrong way: FS has no prefilter and the filings stub (`home-events-filings.md`) holds no keyword rules; the 9.2 macro and geopolitical list exists only to feed this news prefilter.
- "Watchlist symbol" has no server-side source: the watchlist is browser localStorage only (`ui-v2/src/shell/watchlistStore.ts:90,110`; `ui-redesign-spec.md:262` leaves persistence open). Only the scanner universe (`symbol_sector`, `db/migrations/025_symbol_sector.sql`) exists server-side, and it has no company-name column, so there is no name-to-symbol matcher at all ("Reliance Q2 profit rises" and ticker collisions such as IT, BEL, ITC fail). NT 64 says "watchlist or scanner universe", NT 54 says watchlist only.
- The prefilter lists (order-win 9.1, macro 9.2) do not cover the stated RSS uses (beat/miss, broker upgrades and downgrades, NT 21). On the user's own 21-link batch, 0 of 21 match the order-win list and 2 of 21 the macro list (OV 244, 254), so a prefilter would silently drop about 19 of 21 deliberately shared Telegram links. Also decide whether a Telegram link that duplicates an already-terminal RSS row is dropped by dedupe.
- Recommendation: this doc owns `prefilter()` and OV 9.2 (record it; keep 9.1 with filings); define "watchlist" as the scanner universe; add an alias source (`company_name` column or a small alias config); the prefilter applies to RSS only and Telegram links always go to the LLM; state which text is scanned (title only or title plus description) and which lists apply to which source; Telegram origin bypasses dedupe against terminal RSS rows but still dedupes against its own earlier rows. Reconcile the "sanctions, tariff" terms in 9.2, which are wider than the 6.1 criteria (OV 252).

### B8. Page fetch has no safety contract (SSRF, scraping scope, failure behaviour) - Blocker (Decision, then Fix)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness.
- NT 42-43; OV 102 (6.1 step 1), OV 7.6.
- The collector fetches whatever URL a group member posts. A collector container can reach `ui:8080` (secrets endpoint, no login), `server`, Postgres, Mongo and the host LLM (`host.docker.internal`). Required before build: http and https only; block loopback, private (RFC1918) and link-local addresses and container names after DNS resolution and after each redirect; redirect cap (3); timeout (10 s); response size cap (256 KB, parse `<head>` only); `Content-Type` html; no cookies or credentials; identifying User-Agent; one in-flight request per host with a gap. Shorteners (`t.co`, `lnkd.in`, share links; 4 of 21 sample entries were share-link IDs, OV 254) slip past an X or LinkedIn hostname filter unless resolved, and resolving them means fetching X.
- Failure behaviour is undefined: on 403, 404, 429, paywall or timeout, save the link with null og fields, retry at most twice, and do not fail the run, so the 48-hour window is not lost.
- Scope decision: for RSS items the feed already carries title and description. Fetching article pages from Investing.com and CNBC TV18 is the scraping their terms prohibit (OV 4.1, NT 25-26). Recommend page fetch only for Telegram links. Also the doc puts fetch before dedupe and prefilter (OV 102-104), so every irrelevant RSS item triggers a page request; state the order or justify it.

### M1. Stale cite: "overview section 8.1 item 13" - Major (Fix)
- Lenses: all six.
- NT 65. OV 8.1 has items 1-9 only; the LLM-stage open item is OV 8.2 item 13 (OV 217). Cite it from one place (it also overlaps NT 117).

### M2. Telegram token listed as an env var, and secret handling is stale - Major (Fix, plus Decision)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness, structural.
- NT 119; SR 11, 64-67, 95-99 (decisions 4, 10, 15).
- The token and chat id are app secrets, named `telegram_bot_token` and `telegram_chat_id` (`scanner/expiry_alerts.py:24-25`, `scanner/secret_checks.py:69`), delivered to services through the internal secrets endpoint with a per-service token (`scanner/service_client.py:34`). `SERVICE_ALLOWED = {"collector": {"upstox_analytics_token"}}` (`ui/app/internal_secrets.py:33`) means the collector cannot fetch `telegram_bot_token` today; adding it needs an allowlist change and a test (SR decision 15). Replace NT 119 with the secret names, the role and the loader path; keep plain env names only for non-secret settings.
- Decisions: the existing `telegram_chat_id` is the alert destination, so the link group needs its own secret (for example `telegram_links_chat_id`); one bot or two (one `getUpdates` poller per token). Requirements to add: the bot token is in the request URL path, so errors and logs must be redacted as `send_telegram` does; the link reader gets its own service token, separate from the Fastify ingest token role (FS 4.6).
- Related (not this doc): `ui-redesign-brief.md:53` (resolved 2026-11-11) now describes the token as in the secrets store, matching SR. The earlier Docker-secret wording is gone.

### M3. NT never cites CS or FS; collector-split fit is missing (schedule, cooldown, registration, migration numbers) - Major (Fix, plus Decisions)
- Lenses: all six.
- NT 24, 93-96, 112-122; FS 7 ("Governing spec"), FS 44, FS 465; CS 4.1-4.5, CS 55-60, 76-77, 84, 95, 167-170.
- Add a header "Governing spec" line and a dependency list modelled on FS section 2. Missing build items: how the RSS fetcher, Telegram reader and LLM worker register as sources (`collector_settings` row and cron, `config/collector_services.json`, compose service, max-runtime value, the events-source flag and health check CS 4.5); owner modules (NT 121 "not chosen"); the config keys.
- Poll schedule cannot be "taken from OV 7.3" (NT 96): OV 149's "every 5 minutes in market hours, hourly otherwise" cannot be one cron string, and CS and FS use one cron per source (FS 4.1 `*/5 8-20 * * 1-5`, no in-run window). Choose one cron per source, or an in-run gate, or amend OV 149.
- Cooldown: CS 4.3 `exchange_cooldown` has rows only for `nse`, `bse`, `upstox`, `screener`. Investing.com, CNBC TV18, `api.telegram.org` and arbitrary publisher hosts have none (NT 24 and 130 say "not set"). Either request rows from CS S2 (an amendment to a doc owned by another session) or use a per-host in-run rule. The cap also disagrees: CS 84 doubles to 2 hours, OV 152 says 3 hours (FS 465 flags this as S2's). Telegram needs its own 429 `retry_after` handling.
- Migration numbers: the latest is 046 (`db/migrations/046_token_expiry_alert.sql`); CS 56 and 170 give S2 047 and FS 44 lists four more unassigned claimants. This doc would add a queue, a poll-state table and three registrations. Do not claim a number; take "the next number after FS's registration migration" and ask CS for a single registry. The events-database migration follows FS 001.
- Collector containers do not receive `LLM_URL` or a model name today, so an LLM worker in a run-once container needs that wired (see B5).

### M4. "Telegram reader: a new service" contradicts the run-once collector model - Major (Decision)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness, structural.
- NT 30, 34, 38; CS 4.1-4.2, CS 55-68 (every source is a run-once container started by the watchdog from `/internal/due`; no long-running slot).
- "Saves each link as it arrives" (NT 30) implies a push that `getUpdates` does not provide. A drain with a stored offset fits the run-once model: poll with `timeout=0`, save, advance the offset, exit, and the watchdog catch-up rule covers a laptop that was off. Recommendation: replace "new service, own plan" with a source such as `telegram_links` under CS, cron about every 5 minutes, offset in a one-row main-database table. The alternative (long-running service) needs an explicit CS exception. Note CS decision 4: the watchdog starts nothing while Fastify is down, which is a second way links can be lost. Say the same for the RSS fetcher and the LLM worker.

### M5. Retention ownership is stated three ways, and "Telegram updates" and queue retention are undefined - Major (Fix, plus Decision)
- Lenses: structural, comprehension, zoom-out, implementation-readiness, design.
- NT 6, 89-91, 107-109; OV 26 (section 2 table assigns retention and purge to `home-events-filings.md`), OV 162, OV 208; FS 5.5 (purge deferred).
- NT 6 says retention is owned by the overview; OV 26 says the filings doc; NT then lists Retention under Owned rules (89-91) and again under Carried (109). Freshness is double-listed too (93-96 and 107-108). Keep both in Carried only, and correct NT 6 (the same wording is wrong in the sibling stubs).
- "3 years for all rows, including news titles, links and Telegram updates" (NT 91) is ambiguous: the reader stores title, link, headline, summary and message date, not raw updates. Recommend storing no raw update JSON (it carries user names and ids) and saying so. The 3-year rule applies to event rows; queue rows, terminal-state rows and the offset table need their own rule (see B4). The purge has no owner for the queue, and FS 5.5 defers even the events purge; say explicitly if this doc inherits "purge deferred". "Telegram retention" in OV 8.1 item 9 mixes Telegram's server-side holding with our row retention; separate them.

### M6. Failure wording contradicts itself; the expiry clock is undefined and can expire user-curated links - Major (Fix, plus Decision)
- Lenses: design, comprehension, zoom-out, implementation-readiness, codebase-details.
- NT 23, 71-72; OV 113 (6.2).
- "Nothing is dropped" is followed by "expires after 48 hours ... never shown". Reword to "no item is dropped before the 48-hour expiry; expired items are counted". The clock start is not stated (insert time, published time or message date); recommend `queued_at`, and define whether the clock runs while the collector is off (a Friday-evening link is over 60 hours old by Monday, so a laptop-off weekend expires queued items before any worker could run). Decision: should a user-curated Telegram link expire or be rejected at all, or should only RSS items expire (links wait or are tagged without the filter)? Also state what happens to an expired item still in the feed (it must stay in the dedupe memory, B4) and whether a link that arrives from both RSS and Telegram keeps the user-curated flag.

### M7. The verification set tests the wrong population and cannot support its thresholds - Major (Decision, then Fix)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness.
- NT 67, 122; OV 122 (6.4), OV 114, OV 244, OV 254.
- "30 real filings from the opt-in sample": filings do not go through the LLM (OV 114); this stage classifies news and Telegram items. "Opt-in sample" is undefined in the repo. With 30 items and recall at least 0.90, one miss moves recall by roughly 3 to 8 points depending on the number of positives. The only labelled news material is the user's 21-headline batch, which is all positives, and 16 of 21 are URL slugs. The test must also cover prefilter plus LLM end to end, since prefiltered items never reach the model.
- Recommendation: a labelled set of real RSS and Telegram items with negatives drawn from the excluded classes, with a size justified by the target; follow FS 100 (real samples git-ignored, synthetic fixtures committed), so the precision and recall run is an opt-in script outside the offline command; state who labels. Fix NT 67 and OV 122 together.

### M8. `stance`, `category` and `sectors` in the contract are undecided and `stance` has no consumer - Major (Decision)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness.
- NT 61-63, 79, 126-127; OV 105, OV 185 (C4 dropped macro stance extraction), OV 205 (8.2 item 1), OV 262-263 (10.1).
- `stance` has no consumer, and OV 10.1 also wants a separate "action" field the contract lacks. `category` is "<tier or macro>" (OV 105), but event tier is not a category, and the tier 1 and 2 list is still open as a code constant (FS D6a, FS 444); NT 64 relies on it. `sectors` would be free text unless constrained.
- Recommendation: drop `stance` (and probably `sectors`) from the first contract and add later (`prompt_version` is stored); if `stance` stays, allow it only for macro categories. Use the FS 85 `event_type` values plus news values (`order_win`, `broker_rating`, `credit_rating`, `regulatory`, `macro_*`, a plain symbol-mention value). Also settle criteria precedence: an opinion piece naming a universe symbol is both "relevant" (names a symbol) and "not relevant" (opinion) in NT 64. Enforce `reason` length in code, not the prompt. The broker rating and target-price use (OV 132) has no field in the contract.

### M9. Beat/miss tag has no data path - Major (Decision)
- Lenses: design, zoom-out, comprehension, implementation-readiness, codebase-details.
- NT 21, 84-87; OV 167 (7.5); FS 204 (4.4 reconciler pass 2).
- The tag shows next to a results event, which needs matching a news item to the filings `results` row by symbol and date, and that is reconciler pass 2, which waits on this source and the LLM stage. No field in the event row (NT 79) holds the tag, no detector is named (the vocabulary rule is lexical, so it does not need the LLM, but it does need a symbol resolver, B7), and the JSON contract has no field. Word-boundary rule is missing ("beat" and "miss" appear in unrelated headlines), and only headline and summary are stored. Recommendation: derive it in code from the exact words in the title or description, store it as a field (for example `beat_miss`), say who links it to the results row, or defer the tag explicitly. OV 7.5 is also not in the OV section 2 ownership table: state whether it is owned here or carried.

### M10. Failure markers, counts and "last successful run" are undefined, and some text is UI behaviour - Major (Fix)
- Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness, structural.
- NT 73-75; OV 6.1 step 6; FS 295 (5.2, Z4: counts in `collector_runs.message`); CS 107 (`collector_paused` banner).
- "Last successful classification run" is undefined when the queue is empty (the LLM is not called). An "LLM down for over an hour" marker needs a health probe each run (`llm.health()` exists) and a queryable timestamp; a `message` string is not reliably queryable, so a one-row state table is proposed. Counts need a home (`collector_runs` has only `rows_fetched`, `rows_new`, `message`); align with FS Z4. The six counters do not sum (malformed or timed-out items land in no counter); add `error`. "Day" in the empty-day rule has no timezone and does not say whether it covers news only or all events. The marker and empty-day line (NT 73-74) and the tag display (NT 84-87) are Home presentation and belong in ui-redesign; this doc should state only the data it must provide and the Fastify read path. State how the "news filter unavailable" marker relates to the CS `collector_paused` banner.

### M11. The Open section is stale and out of step with OV 8.2 - Major (Fix)
- Lenses: structural, comprehension, zoom-out.
- NT 124-131; OV 186 (C1), OV 184 (C6), OV 217, OV 219.
- Line 126 lists "Whether the LLM stage is built at all", but NT 12 and 58 say it is kept and OV records it as decided (C1). Line 131 "Build order and approval for this phase" is open although build order is approved (OV 184, C6). Missing: OV 8.2 item 13 (LLM test set, prompt, timeout, retries, malformed JSON, injection defence, category enum, queue DDL), item 15 (Investing.com and LinkedIn terms: this doc owns them, and they are a gate on enabling RSS), and the new items from B1-B8 and M3. The same open item appears two or three times inside the stub (delete rights NT 36 and 128; rejected retention 81 and 129; stance 62 and 127; LLM contract 65 and 117; DDL 50, 82 and 116; Telegram dedupe 49 and 118; gap and cap 24, 119 and 130); keep one list.

### M12. The stub restates the overview instead of linking, and its Owned versus Carried split is wrong - Major (Fix, plus Decision)
- Lenses: zoom-out, structural.
- NT 15-96, 98-110; OV 18, 28.
- About two thirds of the stub is copied from the overview with a cite (RSS feed codes at NT 19-20 copy OV 70-71; Licence and terms 98-102 duplicates 25-26 and 32; Carried 104-110 is an index of pointers; Page fetch and the Telegram hosting and delete bullets restate OV 173-180). Copies drift: A1 and the other stale cites are the proof. The Keyword prefilter subsection (52-54) says "Owned by the filings doc" but sits under Owned rules. Decision: either this doc becomes the owner of OV section 6 wholesale (and the overview keeps a link), or it holds only deltas, open decisions and new content. A trimmed stub could be about 50 lines instead of 131. Beat/miss ownership: see M9.

### M13. Telegram message deletion is specified for a feature with no stated purpose - Major (Decision)
- Lenses: zoom-out, implementation-readiness, codebase-details, comprehension.
- NT 35-37, 128; OV 176, OV 8.2 item 2.
- The delete rule, the 48-hour window and the admin requirement are written in detail for rights that are "not decided", with no reason given. Offset confirmation already prevents re-reading, and deleting destroys the only durable copy in the group. Recommendation: the bot never deletes (a plain reader). That removes the admin requirement, the 48-hour constraint and an open item. If deletion stays, say what happens when `deleteMessage` fails or the window has passed, and whether X, LinkedIn and no-link messages are ever deleted.

### M14. Three features at three build phases in one stub; split the specs - Major (Decision)
- Lenses: zoom-out, implementation-readiness.
- NT 13, 112-122; OV 184.
- One build spec for RSS keyword-only, Telegram and the LLM stage would repeat FS's four revisions. Recommendation: write build specs in order, each only when its phase is next: (1) queue, dedupe and RSS (needs B1, B2, B3, B4, B7 decided), (2) the LLM stage (B5, M7, M8), (3) Telegram (B6, B8, M2, M4, M13). Readiness lens would instead put RSS last because it is OFF by default and the riskiest legally (OV 25-26, 51-54); zoom-out asks whether RSS before Telegram is the right order at all, since the user's real workflow evidence is hand-curated links. This is the user's call, and OV 184 (C6) currently fixes RSS first. Gate: FS rev 4 approved (FS 3), CS approved, OV 8.1 items 3-9 closed (OV 195-201).

### M15. RSS feed set, host terms gate and sample capture - Major (Decision)
- Lenses: zoom-out, comprehension, implementation-readiness, design.
- NT 19-26, 117; FS section 4.0 and T0; OV 25-26, 51-54, 280 (10.3).
- 11 feeds across two hosts serve two stated uses (beat/miss and broker ratings), yet NT 64 also needs RBI, Fed and inflation items. Feed codes (`news_95`, ...) are undescribed, no full URLs are given and no sample exists (Investing.com returned 403, so item shape is unknown). Both hosts' terms prohibit storing (NT 25-26). Recommendation: describe each feed; add a T0-style sample capture and an "unverified" marker as FS does; make reading the Investing.com RSS terms an explicit gate before enabling RSS; consider one feed per host in the first slice. NT 24 "gap and cap not set" needs a proposed default (design lens: a randomised gap of a few seconds, one request in flight per host, a per-run item cap).

### M16. Cross-source duplicates and reconciliation are not addressed - Major (Fix)
- Lenses: comprehension, codebase-details, design.
- NT 71, 79-82; FS 204 (4.4), D7; OV 135.
- News-derived results or macro items will duplicate filings rows and the macro doc's own rows, and consume the 3-per-stock cap. Add a one-line pointer to FS 4.4 and state that news rows show unreconciled until pass 2 is built, and list it as a dependency.

### M17. Telegram message shape is unspecified, and OV contradicts itself on DM versus group - Major (Decision, plus Fix)
- Lenses: comprehension, design, codebase-details, implementation-readiness.
- NT 30-33, 47-49; OV 77 (5.3, "user sends links to the bot") versus OV 175 (7.6, group); OV 254.
- State which applies. Unspecified: messages with no URL, several URLs, forwards, edited messages (recommend `allowed_updates=["message"]`), captions, entity extraction (`url` and `text_link`), what "title" means for a Telegram link (recommended: message text without the URL, else og:title, else the slug), URL canonicalisation and what "normalised title" and "content hash" are computed from (no body is stored), and an ignore list for X and LinkedIn hosts including shorteners (and whether such a message is left in place). Message `date` is UTC.

### N1. LinkedIn cite points at a section that does not mention LinkedIn - Nit (Fix)
- NT 32 cites OV 4.1 (OV 49-56), which never mentions LinkedIn. The only OV record is 8.2 item 15 (OV 219), which NT 102 cites correctly. Also: LinkedIn links are not queued or fetched, so the "terms not read" item may be unneeded (decision for the user).

### N2. "overview section 6, C1" is the wrong cite - Nit (Fix)
- NT 126. C1 is defined in OV 7.7 (OV 186), not section 6. Qualify the tag as "overview 7.7 C1": C1 to C6 mean something else in CS (C1 is the exchange cooldown decision, CS 4.3), and FS uses Z, D and Q tags.

### N3. Status line is stale and cites no sibling docs - Nit (Fix)
- NT 3 and 5-6. "follow the overview (sections 7 and 8)" omits section 6 where the LLM rules live; there is no date or revision line (siblings record the amendment date); no pointer to FS (the model to follow) or CS (governs runner, due rule, cooldown, migration numbers). "Build specs are not written yet" is correct for NT only (OV 9, "none of the split docs has build specs yet", is stale because FS exists; see out-of-scope notes).

### N4. Extra "Licence and terms" H2 duplicates other content - Nit (Fix)
- NT 98-102. Not present in the macro, Upstox or filings stubs (Upstox keeps licence as an H3 inside Owned rules). It repeats NT 25-26 and 32; the only unique content is the LinkedIn line. Fold into the RSS and Telegram subsections.

### N5. Build-spec checklist mixes design gaps with build-spec content - Nit (Fix)
- NT 112-122. Items 4 to 7 (config keys, env names, module paths, test counts) are build-spec content already covered by OV 217. Keep items 1 to 3 and replace the rest with one line pointing at the FS section 2 structure. Add the cross-document dependencies (M3). Recommended defaults for these, if the user wants them recorded now: owner modules `scanner/news_intake.py`, `scanner/telegram_links.py`, `scanner/news_llm.py`; offline command `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q` and `npm test --prefix server` (per OV 187), with an opt-in live script for the precision and recall run.

### N6. Terms undefined for a naive reader - Nit (Fix)
- NT 24, 47, 49, 54, 64, 67, 72. Undefined: `prefiltered_out` and `expired` (no state model; add a state table), "tier 1 / tier 2" (not defined or linked), "opt-in sample", "gap detector", "gap and cap" (FS has no "cap" parameter), "normalised title", "watchlist", "event tracker" versus "events table" versus "Home feed" versus "dashboard", and un-glossed externals (`getUpdates`, og:title, OpenRouter, `LLM_URL`: its default differs across `env.template:45` 127.0.0.1:11434, `start.ps1:64` host.docker.internal:11434, README:119 port 8000). Add a short local glossary or cite the OV glossary.

### N7. Event row fields omit items the overview wants - Nit (Fix)
- NT 79; OV 119, OV 134 (7.1), OV 148. Missing: `headline`, `company`, `tier`, `fetched_at` (FS has the column), the beat/miss field (M9), and the `status` value set (recommended: only `relevant` rows are stored). No `published_at` timezone rule.

### N8. Scope and Carried lists omit owned content - Nit (Fix)
- NT 8-13, 104-110. Scope omits page fetch, the intake queue and the beat/miss tag, which Owned rules covers. Carried omits the shortlist and event tiers (OV 7.1 and 7.2) that the Upstox stub carries.

### N9. Telegram and X wording repeated - Nit (Fix)
- NT 32-33 (X ignored twice), 32 and 102 (LinkedIn "not read" twice). Say each once.

## Cross-doc items for the owners of other files (not defects in NT, no action taken)

- OV 9: "None of the split docs has build specs yet" is stale (FS rev 4 exists). OV 8.1 item 3 likewise.
- OV 163: "Rejected items are not stored (section 6.2)"; the rule is in 6.1 step 5 (and see B4).
- OV 77 (5.3) versus OV 175 (7.6): DM versus group (M17).
- OV 98 versus OV 184: the LLM-only rule versus RSS keyword-only (B1).
- OV 122 (6.4): the test set is filings (M7).
- OV 152 versus CS 84: cap 3 hours versus 2 hours (FS 465 flags it as S2's).
- FS 465 notes pending OV edits (14 feeds becoming 8, the 7.3 and 7.4 lines) that are not yet applied.
- `docs/designs/fundamentals-upstox-secondary.md:177` cites "section 4.2 of home-event-sources.md" for the Telegram group; the current location is OV 7.6 (OV 173-180).
- `docs/designs/ui-redesign-brief.md:53` Telegram-token-as-Swarm-secret statement conflicts with SR.

## What must be decided or added before a build spec can be written

Decisions for the user, with the lens consensus:
1. What the RSS keyword-only phase writes, or merge it into the LLM phase (B1).
2. Extend `home_events` or add a separate news events table, and the ingest route and token role (B2).
3. Queue database (recommended: main database) and table names (B3).
4. Terminal-row dedupe memory, its retention (14 to 30 days proposed), and the retention rule for queue rows versus event rows (B4, M5).
5. LLM contract: config names, batch size, timeout, retry, malformed-JSON rule, category enum, `stance` kept or dropped, and the injection defence (B5, M8).
6. Telegram: verify the 24-hour retention, accept the limit or move off the laptop, offset storage, chat allowlist, delete rights, run-once source versus service, secret names, same bot or two (B6, M2, M4, M13).
7. Prefilter owner and policy, symbol and alias source, Telegram bypass (B7).
8. Page-fetch scope (Telegram only or RSS too) and the SSRF and size limits (B8).
9. Expiry clock and whether user-curated links expire (M6).
10. Test set population, size and labeller (M7).
11. Schedule per source, cooldown rows for new hosts, migration number arbitration with CS (M3).
12. Beat/miss: field, detector, linkage or defer (M9).
13. Whether the stub owns OV section 6 or holds only deltas (M12), and the split-spec order (M14).

Doc fixes that need no decision: M1, M10, M11, M16, N1 to N9, plus adding the header pointers to FS and CS, and re-listing retention and freshness under Carried only.
