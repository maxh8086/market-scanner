# Home events sources: decisions needed (consolidated)

Date: 2026-11-10
Status: A1 to A9 decided (see each entry). D4 is resolved (2026-11-10). Other B, C, D and E entries remain recommendations unless their own Status line says decided.

A1 to A9 are decided. The B, C, D and E recommendations are the orchestrator's suggestions only. No build task is dispatched from the news and Telegram, macro and calendar, or Upstox news docs.

How to answer: reply with the ID and accept, change, or defer (for example "A1 accept", "B2 change: 2 items per call", "C7 defer").

Sources: the three decision files in `docs/progress/` (news and Telegram, macro and calendar, Upstox news) and `docs/designs/home-event-sources.md` section 6.3. Events-database migration numbers follow section 6.3: 002 `event_intake`, 003 `news_events`, 004 `macro_events`, 005 reserved (only if the macro calendar table is split). Entry numbers here are new. The original finding IDs are in each entry's Source line.

---

## A. Cross-cutting decisions (answer once, applies to several docs)

A1 decided by the user on 2026-11-10: a separate ingest route and token for each source; the user may discontinue some later. RSS and Telegram are two sources, confirmed by the user on 2026-11-10. A2 to A8 were accepted at their recommended answers by the user on 2026-11-10.

**A1. Ingest route and token model**
- Question: Should RSS, Telegram, Upstox news and macro all send raw items through one shared intake route, or does each source get its own route and token?
- Source: Upstox F1 (token part), Upstox readiness blocker 1, zoom-out major 1, structural major 2, news roles `news_intake_ingest` and `news_events_ingest`, macro B1 (route helpers). The brief's label "macro B4 (helpers)" is wrong: macro B4 is collector layout (see C11, A3).
- Recommended answer [SUPERSEDED by the decision above; old route and role, not in effect]: Use one shared raw-intake route, `POST /internal/events/intake/batch` with role `news_intake_ingest`, for RSS, Telegram and Upstox. Upstox gets no route of its own, and macro keeps its processed-row route with role `macro_ingest`. Copy the filings helpers `validateBatch` and `checkIngestToken` first and generalise later; add per-source tokens only if you want per-source revocation.
- Why: One route means one validation and dedupe path, and the filings helpers already exist.
- Blocks: route names in all three builds, the token rows in `secrets-and-roles.md`, and the events API.

**A2. Poll schedule per source and cooldown rows**
Status: accepted at the recommended answer by the user on 2026-11-10. Widened 2026-11-10 (host list): the cooldown rows cover every collection host, not only the scraped hosts in the recommended answer below. Hosts and keys: Investing.com (`investing_com`) and CNBC TV18 (`cnbc_tv18`) for news; `nse`, `bse`, `upstox` and `screener` (split spec 4.3 exchange rows); RBI (`rbi`), the Federal Reserve calendar page (`federal_reserve`), `fred` (FRED/ALFRED API), `bls` and `mospi` (macro). Decided 2026-11-10: the table is `source_cooldown`, keyed by host, with the same per-key independence rule (the split-spec owner decides). Backoff classes (user, 2026-11-10, final): API class (`upstox`, `fred`) starts at 3 minutes, doubles to 6 minutes, caps at 15 minutes. Other class (every remaining host, including the web-scraped `nse`, `bse` and `rbi`) starts at 15 minutes, doubles, caps at 1 hour. Split spec S2 writes the values. Telegram-linked hosts: a row is created the first time a host appears in an accepted link, by an idempotent function, with the other class as default (confirmed 2026-11-10; the function name is proposed). The Upstox clause below is superseded: Upstox uses the shared `upstox` row.
- Question: Should each source have its own cron, and which hosts need a shared cooldown row in the collector-split spec?
- Source: news M3; macro M2, M3 and B4; Upstox cron slot (readiness 15) and zoom-out 6. Merged.
- Recommended answer (superseded in part by the status line above): Give each source its own cron, as the filings spec does, not an in-run window. Ask the split-spec owner for cooldown rows only for scraped public hosts that can return 403 (Investing.com, CNBC TV18, RBI, Fed, BLS, MoSPI). For Upstox, rely on the client's 429 handling (about 26 calls a day) and confirm with the split-spec owner that no row is needed; the Upstox slot is one daily run after the 20:55 IST filings close, for example 21:30 IST (to confirm).
- Why: The overview's 5-minute window misses macro release times, and one cron string cannot serve every source.
- Blocks: cron lines in each build spec, split-spec cooldown rows, and the Upstox schedule. The 3 h vs 2 h cap conflict (overview 7.3 vs split 4.3a) is replaced by the 2026-11-10 caps (API 15 minutes, other 1 hour); the split-spec owner writes the values.

**A3. How each source registers with the collector**
Status: accepted at the recommended answer by the user on 2026-11-10.
- Question: Does each source run as a run-once collector source, and is a blocked source registered before its blocker clears?
- Source: news M4, macro B4, Upstox F6. Merged.
- Recommended answer: Every source runs once per cron. Telegram is `telegram_links` on a cron of about 5 minutes, with its offset in a one-row main-database table. Macro is one source for RBI and Fed, with India CPI separate only if C5 keeps the job. Upstox is not registered in `SOURCES` or `config/collector_services.json` until its blocker clears, so the `enabled` and `default_enabled` keys are removed.
- Why: Run-once matches the collector model, and an unregistered Upstox source leaves one switch to flip later.
- Blocks: main-database migration numbers for the offset table and registration (owned by the collector-split spec, not the events series), and the registry entries.

**A4. Document ownership and size**
Status: accepted at the recommended answer by the user on 2026-11-10.
- Question: Who owns shared rules and source detail, and how small must the Upstox doc become?
- Source: news M12, macro M13, Upstox F16, zoom-out 9, rerun structural 7 and comprehension 6. The zoom-out lens wants shrinking, while the readiness lens wants more detail. Merged.
- Recommended answer: Each source doc holds its own deltas and open items. The overview stays owner of shared rules until each build spec is approved (overview section 2). Shrink the Upstox doc to a stub of about 50 lines, and write its detail in the build spec only after the licence gate (A6) clears. Keep it as a separate file, not folded into the news doc.
- Why: Shrinking now and adding detail after the licence gate settles the zoom-out and readiness disagreement.
- Blocks: overview section 10 edit (see F), each doc's Open list, and the Upstox build spec.

**A5. Build order and the LLM gate**
Status: accepted at the recommended answer by the user on 2026-11-10.
- Question: Does anything reach `news_events` or the API before the LLM relevance stage exists, and in what order are the build specs written?
- Source: news B1 and M14; Upstox F1 (LLM ordering part) and zoom-out 2. Merged.
- Recommended answer: Nothing reaches `news_events` or the API before the LLM stage exists. Merge keyword-only RSS into the LLM phase, so RSS stays OFF until the LLM worker exists. Write three build specs in phase order (queue, dedupe and RSS; then the LLM stage; then Telegram), each only when its phase is next. Upstox is last and waits for the licence answer. Then amend overview 6 and 7.7.
- Why: Without the LLM stage there is no gate, so raw items would reach the API unfiltered. The macro doc records the build order as approved on 2026-11-10, so this change needs a fresh yes.
- Blocks: the three build specs, overview sections 6 and 7.7, and the Upstox build.

**A6. Terms-of-use gates before any fetch**
Status: accepted at the recommended answer by the user on 2026-11-10.
- Question: Must each source's terms be read and recorded before any fetch, and what happens to sources whose terms may prohibit storing?
- Source: news M15 and N1, macro M10, Upstox licence (ui-redesign decision 1, Finding 14) and F2, Upstox overview item 18. Merged.
- Recommended answer: Each source needs a recorded gate before it is enabled: terms read and recorded in overview 8.2 item 15, and a redacted sample captured and kept out of git before any field table is written. Keep Investing.com and CNBC TV18 OFF until their terms are read; the review says both prohibit storing, which is unverified until read. Drop the LinkedIn terms reading, since LinkedIn links are not queued or fetched. For Upstox, capture one redacted sample now (capture publishes nothing), but enable nothing until Upstox confirms in writing.
- Why: Most host terms are unread, and the Upstox licence is not confirmed.
- Blocks: every RSS, Telegram link, macro and Upstox fetch, and the field tables.

**A7. Retention and purge ownership**
Status: accepted at the recommended answer by the user on 2026-11-10.
- Question: How long are terminal intake rows kept, are macro rows purged, and is raw Telegram update JSON stored?
- Source: news M5 (residual), macro M7, Upstox retention lines. Merged.
- Recommended answer: Keep terminal `event_intake` rows (`rejected`, `expired`) for 30 days; the value is accepted at 30 days on 2026-11-10. Keep macro and calendar rows with no purge in v1. Store no raw Telegram update JSON, since it carries user names and ids. The purge itself stays deferred and is owned by the filings doc (filings spec 5.5).
- Why: Terminal rows must outlast the window in which a source re-polls old items.
- Blocks: the intake retention setting, the filings purge owner, and overview 8.2 item 4.

**A8. Telegram chat type, secret names and bot count**
Status: accepted at the recommended answer by the user on 2026-11-10.
- Question: Are links posted in a group or sent to the bot directly, what secret name holds the group's chat id, and is there one bot or two?
- Source: news M17 and residual M2. Merged.
- Recommended answer: Links are posted in a group, because overview 7.6 is the later section and the rest of the doc assumes it; overview 5.3 should be aligned. Give the group chat id its own secret name (name chosen at build, not here). Use one bot, so there is one `getUpdates` poller per token.
- Why: The news doc already assumes a group, and one bot needs only one poller.
- Blocks: the Telegram reader build, the group chat id row in `secrets-and-roles.md`, and the allowlist rule (B3).

**A9. `ensure_source_row` design (first-sight function for Telegram-linked hosts)**
Status: decided 2026-11-10 by the user's delegation ("you decide best"). The recommended answers below are adopted. The function name is still proposed; the split-spec owner (the user) may rename it.
- Question: How the first-sight function behaves: key normalisation, idempotency, call sites, reads of a missing row, the meaning of "accepted link", redirects, class correction, and the limit of the `/internal/due` filter.
- Source: the 2026-11-10 review of the cooldown host decisions (A2, section 7.3).
- Recommended answer (adopted):
  1. Keys: lowercase the host, strip a leading `www.` and any port, and do no other rewriting. Known hosts map to the fixed keys in A2 through a table in code. Any other host uses its normalised name as its key.
  2. Idempotent: `INSERT ... ON CONFLICT (host_key) DO NOTHING`, then read the row. The function returns the existing or new row, with its backoff class.
  3. Call sites: (a) when a Telegram link is accepted and stored, before any fetch; (b) the fetcher calls it before each request, so a host created at run time is also covered.
  4. Missing row: a read never treats a missing row as "no cooldown". The fetcher calls the function first, so a missing row is created with the other class.
  5. Accepted link: a Telegram link that the news pipeline stores as an event candidate. A link the pipeline rejects creates no row.
  6. Redirects: the row is keyed on the host the link names. If a fetch redirects to another host, that host also gets a row from the function before the redirect is followed.
  7. Class correction: the function never changes an existing row's class. An owner corrects a class by hand, with a recorded `UPDATE`.
  8. `/internal/due`: S5a filters only the hosts in the config file. Hosts created at run time are covered by the fetcher's own check before each request (S5a).
- Why: A newly seen host must not run without a cooldown row, and a missing row must never look like "no cooldown".
- Blocks: the news reader build, split spec S2 (table and function), and S5a.

---

## B. News and Telegram

**B1. What the RSS keyword-only phase writes**
- Question: Should the RSS keyword-only phase write anything before the LLM stage exists, or wait for it?
- Source: news B1 (blocker). Point to A5; not repeated here.
- Recommended answer: See A5. Merge keyword-only RSS into the LLM phase, so RSS stays OFF until the LLM worker exists.
- Why: Raw RSS items must not reach the events table or API without a classifier.
- Blocks: the same as A5.

**B2. LLM contract, config names and injection defence**
- Question: Which config names does the LLM use, what batch size, timeout and retry rule apply, what happens on malformed JSON or LLM down, and how do collector containers receive the config?
- Source: news B5 (blocker). Collector container config is not settled by the review.
- Recommended answer: Reuse `scanner/llm.py` with a news-relevance kind and its own prompt-version constant, using the proposed names `LLM_API` and `LLM_MODEL`, one item per call to start, a timeout of about 120 s (well under the 900 s default), and one retry. On malformed JSON or LLM down, mark the item `skipped` with `api_unavailable`; put untrusted text only in a delimited data block and validate every output field in code.
- Why: Article text can steer the model, so the defences must sit in code, not only in the prompt.
- Blocks: the LLM contract, the `category` enum (B8), and the container config.

**B3. Telegram retention limit, offset storage and allowlist**
- Question: Accept the Telegram retention limit as a known limit, or move the bot to an always-on host? Where is the offset stored, and does the reader accept only the link-group chat?
- Source: news B6 (blocker).
- Recommended answer: Accept the limit as stated, and close overview 8.2 item 2 on that. Verify the 24-hour figure at core.telegram.org/bots/api#getupdates first, since it is unverified. Commit queue rows first, then advance the offset (at least once, with dedupe on `(chat_id, message_id, url_hash)`). The reader accepts only the configured link-group chat id, and a `last_ok_at` warning replaces the gap detector.
- Why: A bot on a laptop misses updates while the laptop is off, and committing before advancing avoids losing links.
- Blocks: the Telegram reader build and overview 8.2 item 2.

**B4. Prefilter owner, symbol source and Telegram treatment**
- Question: Who owns the keyword prefilter, what does "watchlist" mean (the watchlist is browser localStorage only), and do Telegram links go through the prefilter?
- Source: news B7 (blocker).
- Recommended answer: The news doc owns `prefilter()` and overview 9.2. "Watchlist" means the scanner universe, with an alias source (a `company_name` column or a small alias config). The prefilter applies to RSS only, and Telegram links always go to the LLM; Telegram links skip dedupe against terminal RSS rows but still dedupe against their own earlier rows.
- Why: The filings doc has no prefilter, and the browser watchlist is not visible to the server.
- Blocks: the prefilter code, overview 9.2, and the Upstox prefilter note (F).

**B5. Page-fetch scope and safety limits**
- Question: Should article pages be fetched for RSS items as well as Telegram links, and which safety and size limits apply?
- Source: news B8 (blocker).
- Recommended answer: Fetch only for Telegram links. Before build: http and https only; block loopback, private and link-local addresses after DNS resolution and on each redirect; redirect cap 3; timeout 10 s; response cap 256 KB; no cookies; one request in flight per host. On failure, save the link with null og fields, retry at most twice, and do not fail the run.
- Why: RSS already carries title and description, and the review says the Investing.com and CNBC TV18 terms prohibit article fetching (unverified until read).
- Blocks: the Telegram link fetcher and its safety tests.

**B6. Expiry clock and user-curated links**
- Question: When does the 48-hour expiry clock start, and should user-curated Telegram links expire?
- Source: news M6 (major).
- Recommended answer: Start the clock at `queued_at`. User-curated Telegram links do not expire; they wait and are shown. Only RSS items expire.
- Why: A Friday-evening link is over 60 hours old by Monday, so a clock that runs while the laptop is off would expire it before anyone sees it.
- Blocks: the expiry job and the Home display rules.

**B7. Verification set population, size and labeller**
- Question: Which items form the verification set, how big is it, and who labels it?
- Source: news M7 (major). Overview 6.4 needs the same change (see F).
- Recommended answer: Use a labelled set of real RSS and Telegram items, with negatives from the excluded classes, sized to the recall target (30 is too few for recall of 0.90). Git-ignore real samples and commit synthetic fixtures. Run the live precision and recall check as an opt-in script outside the offline command. The project owner labels the set.
- Why: The 30-filing set never passes through the news LLM stage, so it does not test news.
- Blocks: the test set, overview 6.4, and the LLM phase acceptance.

**B8. Contract fields: stance, sectors and category**
- Question: Keep `stance`, `sectors` and the `category` enum in the first contract, and what values does `category` take?
- Source: news M8 (major); overview 8.2 item 1. Macro stance extraction was dropped (overview C4).
- Recommended answer: Drop `stance` and probably `sectors` from the first contract and add them later, since `prompt_version` is stored. Use the filings `event_type` values plus news values (`order_win`, `broker_rating`, `credit_rating`, `regulatory`, `macro_*`, and a plain symbol-mention value), and enforce the `reason` length in code. Leave the precedence rule for an opinion piece that names a symbol open until the contract is drafted (no pick in the review).
- Why: `stance` has no consumer now that macro stance extraction is dropped.
- Blocks: the LLM output contract (B2), and the `news_events` columns (migration 003).

**B9. Beat/miss tag data path**
- Question: Where does the beat/miss value live, who links it to the results row, and is it built now?
- Source: news M9 (major).
- Recommended answer: Defer the tag and say so in the doc. If built later, derive it in code from the exact words in the title or description, store it as a field such as `beat_miss`, name who links it to the results row, and write the word-boundary rule.
- Why: The review finds no data path for it, and the first contract is already large (B8).
- Blocks: `news_events` fields (migration 003) and the results display (overview 7.1 and 7.5).

**B10. Run counts, failure state and the day boundary**
- Question: Where are run counts stored (`collector_runs` has no column for them), is there an `error` count, how is the last successful classification run stored when the queue is empty, and which timezone defines "the day"?
- Source: news M10 (major).
- Recommended answer: Add a one-row state table for the last successful run and the LLM-down marker, with an `error` counter aligned with the filings spec Z4 counts; define "the day" in IST. Whether the "news filter unavailable" marker reuses the collector-split `collector_paused` banner is for the split-spec owner to confirm.
- Why: The six counters do not sum without an error count.
- Blocks: the run-status display and the collector-split banner.

**B11. Stub scope: own overview section 6, or hold deltas only**
- Question: Should the news doc own overview section 6, or hold only deltas and open items?
- Source: news M12 (major). Point to A4.
- Recommended answer: See A4: hold deltas only, and the overview stays owner of shared rules.
- Why: Each rule then has one owner (overview section 2).
- Blocks: the news doc structure and overview section 6.

**B12. Telegram message deletion**
- Question: Should the bot delete messages from the group at all?
- Source: news M13 (major); overview 8.2 item 2.
- Recommended answer: No. The bot never deletes messages; it is a plain reader. That removes the admin-rights need, the 48-hour constraint and one open item. If deletion stays, state what happens when `deleteMessage` fails or the window has passed.
- Why: Deleting removes the only durable copy in the group, and the review finds no stated purpose.
- Blocks: the bot's admin rights and overview 8.2 item 2.

**B13. Build order of the news specs**
- Question: Should the build specs be one, or three in phase order (RSS, LLM, Telegram)?
- Source: news M14 (major). Point to A5.
- Recommended answer: See A5: three build specs, each written when its phase is next.
- Why: The phase order follows the LLM gate.
- Blocks: the news build specs.

**B14. RSS feed set, terms gate, sample capture, gap and cap**
- Question: Which RSS feeds are in the first slice (11 feeds on two hosts serve two uses, and the LLM stage would also need RBI, Fed and inflation items), and what gap and cap apply per host?
- Source: news M15 (major); overview 8.2 items 9 and 15.
- Recommended answer: Describe each feed in the doc. Add a T0-style sample capture with an "unverified" marker, as the filings spec does. Make the Investing.com terms reading a gate before RSS is enabled (A6). Start with one feed per host. Use a random gap of a few seconds, one request in flight per host, and a per-run item cap (cap value to set).
- Why: Both hosts' terms are unread, so RSS stays OFF until the gate clears.
- Blocks: the RSS build and overview 8.2 items 9 and 15.

**B15. Telegram chat type, message shape and title rules**
- Question: Are links posted in a group or sent to the bot directly? How are messages with no URL, several URLs, forwards, edits and captions handled, and how is a link's title made?
- Source: news M17 (major). Point to A8 for group or direct.
- Recommended answer: Group, per A8. Set `allowed_updates=["message"]`. Title is the message text without the URL, else og:title, else the slug. Canonicalise URLs and ignore X, LinkedIn and shorteners (ignore list to confirm).
- Why: The title rule gives every Telegram link a readable name without a fetch.
- Blocks: the Telegram reader and the link queue.

---

## C. Macro and calendar

**C1. Rate-decision data (action, new rate, stance)**
- Question: For each rate decision, where do the action (for example a 25 bp cut), the new rate and the stance come from?
- Source: macro B3 (decision). The stance vocabulary is open (overview 8.2 item 1).
- Recommended answer: Store the decision date, headline, link and verbatim stance text, with an optional hand-entered action and rate. Do no stance classification in v1.
- Why: RBI's terms (accommodative, neutral, calibrated tightening) do not map onto hawkish, dovish and neutral, and the Fed states no stance in that form.
- Blocks: the panel fields, `macro_events` (migration 004), and C8.

**C2. Rate decisions in the Home feed**
- Question: Do rate decisions also appear in the Home feed, at which tier, and how do they dedupe against the LLM route?
- Source: macro B2 (residual).
- Recommended answer: Cut rate decisions from the Home feed for v1. The other options are a read-time merge in the Home API or an amended filings schema.
- Why: The cut is the smallest option; the other two change how rows are merged.
- Blocks: the Home feed merge in Fastify, and the filings schema if amended.

**C3. Display date for US times in IST**
- Question: Which date is shown when a US time falls on another date in IST? (The FOMC statement at 2:00 p.m. EST on 9 Dec is 00:30 IST on 10 Dec.)
- Source: macro B5 (residual).
- Recommended answer: Show the IST date, and show the original ET date in the label.
- Why: One time zone stays on screen, and the source date stays visible.
- Blocks: the calendar display and its tests.

**C4. Calendar row rollover**
- Question: Who adds next year's rows, is the full year seeded in one pass, are FOMC minutes and the press conference separate rows, and what are the row status values?
- Source: macro M1 (residual).
- Recommended answer: Seed the full year in one pass from a checked-in file. Make minutes and the press conference separate rows. Use the status values `scheduled` and `released`.
- Why: One reviewable file makes the yearly work a single change.
- Blocks: the calendar seed file, `macro_events` (004), and reserved 005 if the table is split.

**C5. India CPI job in v1**
- Question: Is the India CPI job in v1, or is the value entered by hand with the press-release link? What do "next available slot" and the release-day window mean, and what is the status of a "not yet published" run?
- Source: macro M4. See also macro B4 (A3).
- Recommended answer: Enter India CPI by hand, with the press-release link, in v1 (the zoom-out lens's suggestion).
- Why: One value a month is small enough to enter by hand.
- Blocks: the India CPI build item and the source list in A3.

**C6. FRED units, revisions and key placement**
- Question: Which unit is shown for headline CPI, how are revisions and observation versus release dates handled, how is FEDFUNDS used beside decision rows, and is the FRED key in the app secret store or in `.env`?
- Source: macro M5 (major). The review gives no pick on units or key placement.
- Recommended answer: Display YoY percent (FRED `units=pc1`). Store `FREDAPI_KEY` in the app secret store, and register the name in `secrets-and-roles.md`, not in `.env`. Revisions, date handling and FEDFUNDS use stay open until the field list is written.
- Why: The index level CPIAUCSL is not a rate, so showing it raw would mislead.
- Blocks: the FRED build, the secret-store row, and the FRED pass condition (overview item 16).

**C7. Trading-day calendar**
- Question: Does macro need a trading-day calendar at all? Candidates are the NSE/BSE calendar (overview item 7), the Upstox holidays API (filings D6b), or a holiday list in UI code (`EXCHANGE_HOLIDAYS_2026`, not checked here; unverified).
- Source: macro M6 (major).
- Recommended answer: Drop the trading-day calendar. Use a weekday cron, so a holiday costs one empty run. Close overview 8.2 item 7 on that.
- Why: One empty run on a holiday costs little, and it removes a third calendar source.
- Blocks: macro build item 6 and overview 8.2 item 7.

**C8. Which screen shows the panel and calendar**
- Question: Which screen shows the macro panel and the calendar, which UI spec owns it, and which endpoints and empty and stale states apply?
- Source: macro M8 (major). Overview 10.2 calls it the "market dashboard", which is not a screen in `ui-redesign-spec.md`.
- Recommended answer: A macro panel and calendar block on the Home screen, owned by the UI redesign spec, with its empty and stale states named in that spec.
- Why: The "market dashboard" is not a screen in the UI spec, so nothing owns it today.
- Blocks: the read endpoints (C17), and the UI spec update.

**C9. Alerts for rate decisions and CPI**
- Question: Should rate decisions and CPI get a dashboard countdown, a push through the Telegram path, or no alerts in v1? Lead times are also open (overview 8.2 item 16).
- Source: macro M9 (major).
- Recommended answer: Cut alerts from v1.
- Why: Four dated events a month are speculative for an alert channel (zoom-out lens).
- Blocks: overview 10.3 countdown item and the lead-time decision (overview 8.2 item 16).

**C10. Terms of use for RBI, Fed, BLS and MoSPI**
- Question: Should the terms of these four hosts be read and recorded before any fetch, or should the user's personal-use acceptance be recorded instead?
- Source: macro M10 (major). Point to A6 for the gate.
- Recommended answer: Apply the A6 gate: read the terms in a sample-capture step before any fetch, and record the result in overview item 15.
- Why: The four hosts are not listed in overview 4.1 or item 15, and some sites may block scripted clients (unverified).
- Blocks: every macro fetch.

**C11. Collector layout for macro sources**
- Question: Does macro run as one source or several (RBI and Fed polling, FRED, India CPI), with which cron, and are they registered as events sources?
- Source: macro B4 (decision). See A2 and A3.
- Recommended answer: One macro source for RBI and Fed on one low-frequency cron. India CPI is a separate source only if C5 keeps the job.
- Why: The zoom-out framing assumed the main database, which the storage decision replaced, so it needs a re-read.
- Blocks: build spec items 2 and 5, and the registry entries in `config/collector_services.json`.

**C12. Poll cadence for macro**
- Question: Should macro use one low-frequency cron, or calendar windows around each release? Do the RSS "default off" and "1-week drop" rules apply to RBI and Fed?
- Source: macro M2 (decision). See A2.
- Recommended answer: One low-frequency cron for the RBI and Fed feeds, with calendar windows only for dated releases. No recommendation on the RSS rules; leave open.
- Why: The 5-minute window misses Fed 00:30 IST, US CPI 18:00 or 19:00 IST, and India CPI 16:00 IST.
- Blocks: the cadence section, overview 7.3, and the cron lines.

**C13. Cooldown rows for macro hosts**
Status: FRED gets a row (`fred`, API class), answered 2026-11-10 (user host list). The retry timing is set by the backoff classes in the A2 status line (2026-11-10). The overview's 3 h cap and split 4.3a's 2 h cap are superseded by the 2026-11-10 caps (API 15 minutes, other 1 hour; split-spec owner writes the values).
- Question: Should the split-spec session add cooldown rows for RBI, Fed, FRED, BLS and MoSPI, or should the doc state that no shared cooldown applies? Does the 15-minute retry rule apply?
- Source: macro M3 (decision). See A2 and E4.
- Recommended answer: Request the rows, as the filings spec did for its hosts, so a wrong URL that returns 403 cannot trigger repeated requests. The 15-minute retry question is answered by the backoff classes (A2 status, 2026-11-10). The 3 h vs 2 h cap conflict is replaced by the 2026-11-10 caps (API 15 minutes, other 1 hour); the split-spec owner writes the values.
- Why: Scraped public hosts can return 403, and the policy needs one owner.
- Blocks: split-spec cooldown rows, and the macro gap and cap (overview 8.2 item 9).

**C14. Retention for macro and calendar rows**
- Question: Keep these rows, or keep them 3 years like event rows? Who runs the purge?
- Source: macro M7 (decision). See A7.
- Recommended answer: Keep them (they are small), with no purge in v1. Any later purge is owned by the filings doc.
- Why: The rows are small, so no purge is needed yet.
- Blocks: the `macro_events` retention note and overview 8.2 item 4.

**C15. Which copy governs the macro facts in overview section 10**
- Question: Does this doc or overview section 10 govern the macro and calendar rules? Should open items (stance definitions, trading-day calendar, cadence, rate limits) move to the Open list with one owner each?
- Source: macro M13 (decision). See A4.
- Recommended answer: This doc governs the macro rules, since the overview's ownership table gives the macro rows to this doc. Overview section 10 becomes a pointer. Move the open items to the Open list with one owner each.
- Why: One governing copy stops two versions from drifting apart.
- Blocks: overview section 10 (see F) and this doc's Open list.

**C16. Keyword list for the RBI and Fed feed filter**
- Question: Which keyword list does the RBI and Fed filter use (this doc or overview 9.2), does it match title or description, whole words or substring, and what does "priority 1" mean now that priorities 2 and 3 are cut?
- Source: macro N5 (decision).
- Recommended answer: One list for these feeds, kept in this doc, matched as whole words in the title and description, with a negative fixture in tests. Remove the "priority 1" label, since priorities 2 and 3 are cut.
- Why: The two lists differ (this doc has "Stance" but no "Fed"; the overview macro prefilter has "Fed"), so the same item can be kept by one and dropped by the other.
- Blocks: the macro feed filter, and the keyword lists owned by the filings doc and overview 9.2.

**C17. Owner of the macro read contracts**
- Question: Who owns `GET /api/macro` and `GET /api/calendar`, and are the filings route helpers copied or generalised for macro?
- Source: macro B1 (other owner).
- Recommended answer: Copy the helpers first (see A1), and have the UI spec name the owner of the two read contracts.
- Why: The storage decision is applied, and this question belongs to the filings doc and the UI spec.
- Blocks: the macro read path and the UI spec.

**C18. Unverified times and dates (a check, not a decision)**
- Question: Three items are unverified: the MoSPI 16:00 IST time, the December MPC date on the RBI schedule page, and the BLS release time for the November-data row.
- Source: macro U1 (open, unverified).
- Recommended answer: Check each against its source page before the schedule is set. No user choice is needed.
- Why: These times set the cadence in C12 and the calendar seed in C4.
- Blocks: C4, C5 and C12.

---

## D. Upstox news

**D1. Feed tier, event type and LLM ordering**
- Question: Which feed tier and event type do Upstox items take (overview 7.1), and may the Upstox build ship before the LLM relevance stage exists (overview 7.7)?
- Source: Upstox F1 (remaining parts). Token part is A1; ordering part is A5.
- Recommended answer: Feed tier and event type: no recommendation in the review; leave open. LLM ordering: no. The Upstox build waits for the LLM stage (A5).
- Why: Without the stage there is no gate, so nothing reaches `news_events` before it exists.
- Blocks: the Upstox build and the overview 7.1 feed rule.

**D2. Attribution to a symbol, and what empty data means**
- Question: If the live payload has no instrument key on each item, how is an article linked to a symbol? May a redacted sample be captured before Upstox confirms? Does zero items across all keys mean "no news" or "broken"?
- Source: Upstox F2.
- Recommended answer: Capture one redacted sample now, kept out of git, because capture publishes nothing. Defer the attribution choice until the sample shows whether the instrument key is on each item. Treat zero items across all keys as a "zero items" warning, not as success.
- Why: Only the sample shows which fallback is needed. The default path batches up to 30 instrument keys per request (overview 5.4), about 26 calls a run for 751 keys. One request per key (about 751 calls a day) is the review's fallback, used only if items lack the instrument key.
- Option, added 2026-11-10 (no recommendation; the sample decides): if items carry no instrument key, match the headline and summary against company names in stock_snapshots.company (only stock_snapshots.company holds a company name; symbol_sector and constituent_membership join by ISIN for sector and index and have no name column). No extra Upstox calls. Risk: false positives on generic words and group names; test on the sample.
- Blocks: the endpoint and request shape, the stored-fields list, and the sample (A6 still applies).

**D3. Dedupe key and seen-links store**
- Question: Is the dedupe key `article_link` alone, or `(article_link, instrument key)`? Should a seen-links store be adopted, or overview 8.2 item 3 for this source?
- Source: Upstox F3. Overview 8.2 item 3 is owned by the news doc.
- Recommended answer: Dedupe on the news doc's intake hash, with `article_link` as the hash input and the instrument key kept in the `jsonb` payload (the zoom-out form). This differs from the orchestrator draft, which used `(article_link, instrument key)`. The zoom-out form drops the second symbol when one article is tagged to two keys, so keep the zoom-out form unless the sample shows one article tagged to several keys; then use the draft form. Do not cite overview 8.2 item 3 as a hash rule. The 30-day rule for terminal rows is home-event-sources.md:192 and A7.
- Why: The filings convention (source prefix plus hash, filings 4.2) keeps one dedupe path.
- Blocks: the `event_intake` dedupe column (migration 002) and the Upstox retention (A7).

**D4. SDK or UpstoxClient for the News call (resolved 2026-11-10)**
- Status: resolved. The user's rule (2026-11-10): use `UpstoxClient` if it supports every required feature, otherwise the SDK. Result: `UpstoxClient._get` (`scanner/upstox.py:269`). No SDK dependency for News.
- Question: Should the News call use the official SDK (a new dependency in three files) or `UpstoxClient._get`?
- Source: Upstox F8.
- Feature check (reviewed 2026-11-10):
  - Bearer auth with the analytics token: present (`UpstoxClient.__init__`).
  - `GET /v2/news` with `category=instrument_keys` and up to 30 comma-separated keys: `_get(url, params)` takes the params. One new News method is needed (no SDK).
  - Paging with `page_number`, `page_size` and `metadata.total_pages`: `_get` returns the JSON, so the caller loops. New code, no SDK.
  - Multi-window rate limit and 429 escalation: present (`_RateLimiter`, `_handle_429`).
  - Error on a non-200 response: present, with the status and body in the message. `UpstoxError` has no status field, so D7 needs a small addition.
  - Timeout: fixed at 60 s. The timeout argument in D8 is a small addition, not a gap.
  - Headers accepted by the News endpoint: unverified (`Content-Type: application/json` on GET; review item 12). This is a go/no-go in the live capture.
  - Cloudflare: the client's headers already work for quotes and candles in production, and News uses the same host and headers. The live capture confirms it.
- Switch rule: move to the SDK only if the live News call with the client's headers returns a Cloudflare 403 (see D7).
- Why: The client already has auth, the limiter and 429 handling, so a News call is one new method plus paging, with no new dependency.
- Blocks: nothing now. The live capture checks the two items above. Fundamentals doc item 6 (SDK for fundamentals fetches) is a separate decision and is not changed by this one.

**D5. The 1-week age limit**
- Question: Keep the 1-week age limit (overview 8.2 item 8)? If kept, does it measure `published_at` or fetch time?
- Source: Upstox F11.
- Recommended answer: Drop it for the first build, since the endpoint already returns about 7 days.
- Why: The limit filters almost nothing, and the review calls it a near no-op if kept.
- Blocks: overview 8.2 item 8.

**D6. Universe and first-poll size**
- Question: Which rows form the Upstox universe, and what LLM load does the first poll create?
- Source: Upstox F13.
- Recommended answer: Start with the shortlist (about 39 names, 2 calls) and cap or skip the first-poll backlog. Move to the full 751-stock ISIN set only after LLM load is measured. This changes the orchestrator draft, which chose 751 rows with an estimate first, because the first poll can send up to 7 days of articles for 751 stocks to the local LLM.
- Why: A measured load is safer than an estimate, and the shortlist fits one run.
- Blocks: the universe and batching design, and the LLM timing.

**D7. Auth failure or Cloudflare 403 (new, comprehension 3)**
- Question: How does the poller tell an auth failure from a Cloudflare 403?
- Source: rerun comprehension 3 (new item).
- Recommended answer: Decide after the redacted sample is captured. Until then, treat a non-JSON 403 body as Cloudflare, not as an auth failure. No Cloudflare branch exists in scanner/upstox.py; the generic raise is around lines 283-295. Supporting evidence: fundamentals-upstox-secondary.md:105 (urllib 403, Cloudflare error 1010).
- Why: A plain 403 looks like a bad token, and the wrong label sends the operator to the wrong fix.
- Blocks: the error handling in the Upstox client and the sample capture (D2).

**D8. Timeout and 5xx retry on the News call (new, readiness 3)**
- Question: Should the News call have a timeout and a 5xx retry, and how does a batch failure appear?
- Source: rerun readiness 3 (new item); Upstox overview item 19 (batch failure handling, News page rate-limit class). Merged.
- Recommended answer: Add a timeout argument to a new `UpstoxClient` News method, and have the poller catch request exceptions and `UpstoxError`. Keep 5xx retry out of v1.
- Why: A hung call would stall the run, and 5xx retry can wait to keep v1 small.
- Blocks: the poller error path and overview item 19.

**D9. How OFF is enforced**
- Question: How is the OFF state enforced, given that `collector_settings.mode` allows only `scheduled` or `manual`, and a UI "Run now" can start a manual source?
- Source: Upstox F6. Point to A3.
- Recommended answer: See A3: leave the source out of `SOURCES` and `config/collector_services.json` until it is unblocked. Specs may be written while it is disabled. Evidence: the mode CHECK is db/migrations/001_core.sql:84; the Python guard is scanner/collect/settings.py:79-80; request_run checks SOURCES only (settings.py:136-137); the UI Run now calls it at ui/app/api.py:507. config/collector_services.json exists only in the docs.
- Why: One switch then remains to flip.
- Blocks: the Upstox registration and the build specs.

**D10. Which doc owns the Upstox values**
- Question: Does this stub own the Upstox values (poll, batch, age limit, token role), or does overview 5.4 keep them?
- Source: Upstox F16. Point to A4.
- Recommended answer: See A4: overview 5.4 stays owner until the build spec is approved.
- Why: This is the status quo under overview section 2.
- Blocks: the Upstox doc's owned-rules section.

---

## E. Process decisions (not from the docs)

**E1. Apply the doc-only fixes now**
- Question: Apply the doc-only fixes in section F now?
- Source: process. Cross-document items from all three reviews.
- Recommended answer: Yes. They need no decision.
- Why: Stale cites in one doc mislead the others.
- Blocks: nothing else; the overview edits in section F.

**E2. Commit the docs on a docs branch**
- Question: Commit the uncommitted doc and progress files (all changes under `docs/designs/` and `docs/progress/`) on a docs branch, with a PR and merge commit?
- Source: process (git status at session start shows many uncommitted doc files).
- Recommended answer: Yes, one docs PR, with the human author only and no Co-Authored-By trailer or footer.
- Why: Links between these docs point at the working tree, so they should land together.
- Blocks: the merge of the docs and this file.

**E3. Filings wave 2**
- Question: Start wave 2 of the filings spec (T2b, T3b, T5b, then T3c, T4b and so on, per filings spec section 9) now?
- Source: process. This is filings work, not work from these three docs, so the "no build task from these docs" rule does not cover it.
- Recommended answer: Start only on your explicit go-ahead, in spec order. T5c also waits until `server/src/index.ts` (modified) and `server/src/kiteToken.ts` (untracked) are committed or stashed.
- Why: The filings build has its own approvals.
- Blocks: T2b, T3b, T5b and T5c.

**E4. Relay of the collector-split requests**
- Question: Who receives `docs/progress/collector-split-spec-requests.md`? The split spec's owner is the user.
- Source: process.
- Recommended answer: resolved 2026-11-10. The user owns the split spec and reviews the requests file directly.
- Why: Cooldown rows (A2, C13) and registration numbers (A3) wait on the split spec.
- Blocks: A2, A3, C13, and S2 writing the 2026-11-10 backoff values.

**E5. Blocked items**
- Question: Who clears the two blocked items, T0 (a network path NSE accepts) and T1 (the split-spec migration number)?
- Source: process.
- Recommended answer: Leave both blocked until the blocker clears. T1 clears when E4 is done.
- Why: Neither can run now. T1 needs a main-database migration number, not an events number.
- Blocks: T0 and T1.

**E6. Approval of the macro build spec**
- Question: Approve the macro build spec for its phase once it is written?
- Source: process (macro doc, Open: build approval).
- Recommended answer: Approve only after A5 and the C decisions it depends on are answered.
- Why: The doc asks for approval of the build spec for this phase.
- Blocks: the macro build.

---

## F. Doc-only fixes still to apply (no decision needed)

Reply "apply" to have these made. Items marked "after" wait for a decision first.

- Overview 6.1 step 5 (about line 106): "kept only as counts" conflicts with 6.3. Align to 6.3, which keeps terminal rows in `event_intake`.
- Overview 6.3 (about line 123): the "superseded" bullet cites news doc lines 82 and 116, which were rewritten.
- Overview 6.3 event-row field list versus filings 4.1 `home_events` columns: align after B8 is decided.
- Overview 7.4 (about line 181): "Rejected items are not stored as event rows (section 6.2)" cites the wrong rule; point to 6.1 step 5 and 6.3.
- Overview 10.1 (about line 278): cites section 7.1 for a rule that is not there.
- Overview 10.2 (about lines 289 to 290): the MPC row contradicts the macro doc, and the US row is dated today.
- Overview 10.3 (about line 297): IST conversion is reversed. 8:30 a.m. ET is 19:00 IST in winter and 18:00 IST in summer. Remove WPI, which is out of scope. Line 296: say the table is `macro_events` (migration 004).
- Overview 10.3 (line 298) and 5.5 (line 92): merged RBI and Fed bullets, and merged refresh and data-sources bullets. Split them.
- Overview 8.2 item 17 (about line 239): the "4:00 PM" wording is stale; 16:00 IST and 4:00 p.m. are the same time.
- Overview lines 9, 77, 98, 122 and 163, and section 8.1 item 3: stale "no build specs yet" and similar wording (the filings spec revision 4 exists).
- Overview 8.2 item 15: add the Upstox API terms and developer agreement to the "terms not read" list.
- Overview 5.4: the instrument-key sentence (line 83) is not in the stored-fields list (line 85). The "loses nothing" wording needs the collector-uptime condition (about 7 days).
- Overview 6.4 (line 139): the test set is filings, not news and Telegram. Change after B7 is decided.
- Overview 6 and 7.7 (after A5): amend the LLM-only rule (line 98) against the RSS keyword-only build (line 202). Applied 2026-11-10 (A5 accepted).
- Overview 5.3 and 7.6 (after A8): align direct message versus group. Applied 2026-11-10 (A8 accepted).
- Overview section 9.2 and the filings keyword lists (after C16): align the macro prefilter and the feed filter.
- `docs/designs/ui-redesign-brief.md` line 53 (resolved 2026-11-11): the brief now says the Telegram token is in the secrets store, per `secrets-and-roles.md`. The earlier Docker-secret wording is gone.
- `docs/designs/fundamentals-upstox-secondary.md` line 177: cites "section 4.2 of home-event-sources.md" for the Telegram group. The current location is overview 7.6.
- `docs/progress/execution-ledger.md` line 39: cites `home-event-sources.md` 4.5 for Upstox News terms. The content is now at overview 4.1 and 5.4.
- `docs/designs/secrets-and-roles.md` (after A1 and C6): add the `macro_ingest` and `upstox_news_ingest` role rows if kept, the FRED key name, and the service-token mapping to `collector` (Upstox finding 19).
- Upstox doc, rerun fixes: lines 6 and 48 cite the wrong purge owner. It must be `home-events-filings-spec.md` section 5.5 for the design; `home-events-filings.md` owns it by overview section 2.
- Upstox doc, rerun fixes: the item-3 dedupe cites on lines 49 and 142 need correcting.
- Upstox doc, rerun fixes: rename the "decided 2026-11-10" heading so only the storage route is marked decided.
- Upstox doc, rerun fixes: name the prefilter owner. The rerun asks for the filings doc, but news B4 recommends the news doc. Hold this until B4 is decided.
- Upstox doc, rerun fixes: mark the 30-key limit as unverified; name `fundamentals-upstox-secondary.md` wherever "the fundamentals doc" appears; cite split 4.3a on line 100.
- Upstox doc, rerun fixes: use one status vocabulary (decided, proposed, open, unverified) with a legend; replace "per the review" with a cite or "unverified".
- Upstox doc, rerun fixes: add the ingest token location and `EVENTS_API_BASE_URL` to the Open list; reorder Scope before Blocked; delete the licence restatement on line 92.
- Upstox review file: the summary says "12 Majors, 6 Nits", but the headings show 15 Majors and 3 Nits. Both total 20; correct the summary.
- Unverified, not checked here: the review says Fastify reads an Upstox token from `data/secrets.env`. Check when `server/src/secrets.ts` is next reviewed.
