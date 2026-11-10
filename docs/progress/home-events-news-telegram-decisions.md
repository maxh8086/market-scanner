# News and Telegram doc: findings needing a user decision

Source: `docs/progress/home-events-news-telegram-review.md` (2026-11-10), applied to `docs/designs/home-events-news-telegram.md` after the events-database storage decision (overview section 6.3). Line numbers are the current line numbers in the doc. Each entry gives the question, the review's recommendation (quoted briefly), and the doc lines affected. The doc carries a matching "Open (user decision)" bullet for each item. Nothing below is decided.

## Findings

### B1. What the RSS keyword-only phase writes (Blocker)

Question: the build order says RSS keyword-only comes before the LLM stage, but raw RSS items must never reach the events table or the API, and without an LLM there is no classifier. What does the keyword-only phase write, or should it wait for the LLM?

Review's recommendation: either (a) merge keyword-only RSS into the LLM phase, so RSS stays OFF until the LLM worker exists (the implementation-readiness lens recommends this), or (b) let keyword-only items become event rows only on a deterministic rule (beat/miss word, rating term), with `model_id` null and an explicit `status`. Then amend overview sections 6 and 7.7.

Doc lines: 15 (build order), 81 (LLM relevance stage), 142 (Open).

### B5. LLM contract, config names and injection defence (Blocker)

Question: which config names the LLM uses (the review proposes `LLM_API` and `LLM_MODEL`), the batch size (1 item per call or 10 with ids), the timeout (not the 900 s default), the retry rule, the malformed-JSON rule, and how the collector containers receive the config.

Review's recommendation: reuse `scanner/llm.py`, add a news-relevance kind with its own prompt-version constant, and require structural injection defence (untrusted text only in a delimited data block, code validation of every output field, `source_url` from the queue row). Its items for the user are batch size, timeout and the retry rule, and it says a status is needed when the LLM is down (`skipped`, as `api_unavailable`).

Doc lines: 85 to 90 (contract, timeout and injection defence), 143 (Open).

### B6. Telegram retention limit, offset storage and chat allowlist (Blocker)

Question: accept the Telegram retention limit as a known limit, or move the bot to an always-on host? The 24-hour figure is unverified and must be checked at core.telegram.org/bots/api#getupdates before anything is decided. Also: where the offset is stored, and whether the reader accepts only the configured link-group chat.

Review's recommendation: accept the limit as stated, or move off the laptop, and close overview 8.2 item 2 on that. On storage it recommends committing queue rows first and then advancing the offset (at-least-once with dedupe), with dedupe key `(chat_id, message_id, url_hash)`, and a `last_ok_at` warning instead of a "gap detector". On the allowlist it says the reader must accept only the configured link-group chat id.

Doc lines: 60 (unconfirmed updates, unchecked), 61 (link-group secret), 75 (dedupe and gap detector), 144 (Open).

### B7. Prefilter owner, symbol source and Telegram treatment (Blocker)

Question: who owns the keyword prefilter (the doc says the filings doc, but that doc has no prefilter); what counts as "watchlist" (the watchlist is browser localStorage only, so there is no server-side source); and whether Telegram links go through the prefilter at all.

Review's recommendation: this doc owns `prefilter()` and overview 9.2; define "watchlist" as the scanner universe; add an alias source (a `company_name` column or a small alias config); the prefilter applies to RSS only and Telegram links always go to the LLM; Telegram origin bypasses dedupe against terminal RSS rows but still dedupes against its own earlier rows.

Doc lines: 64 and 79 (prefilter), 75 (dedupe), 145 (Open).

### B8. Page-fetch scope and safety limits (Blocker)

Question: should the collector fetch article pages for RSS items as well as Telegram links? RSS feeds already carry title and description, and fetching article pages is what the Investing.com and CNBC TV18 terms prohibit. Also: the SSRF and size limits, and the failure behaviour.

Review's recommendation: fetch only for Telegram links. Before build: http and https only; block loopback, private and link-local addresses after DNS resolution and each redirect; redirect cap 3; timeout 10 s; response cap 256 KB; no cookies; one in-flight request per host. On failure: save the link with null og fields, retry at most twice, do not fail the run.

Doc lines: 64 to 68 (page fetch), 146 (Open).

### M3. Poll schedule, cooldown rows and migration arbitration (Major)

Question: the overview's "every 5 minutes in market hours, hourly otherwise" cannot be one cron string. Which cron applies per source (or is an in-run window used)? Which cooldown rows exist for Investing.com, CNBC TV18, Telegram and publisher hosts, which have none? Who arbitrates the main-database migration numbers, which the collector-split spec owns? Events-database numbers 002 and 003 are already allocated.

Review's recommendation: no single recommendation. It offers choices: one cron per source, or an in-run gate, or amend overview 7.3; for cooldowns, request rows from the collector-split spec (S2) or use a per-host in-run rule; and ask the collector-split spec for one migration registry. No recommendation in the review on the cooldown choice.

Proposed by orchestrator draft: one cron per source (as the filings spec does), and cooldown rows requested from the collector-split spec, so the policy has one owner.

Doc lines: 122 (poll schedule, Carried), 147 (Open).

### M4. Telegram reader: run-once source or long-running service (Major)

Question: the collector model runs every source as a run-once container, but a Telegram reader that "saves each link as it arrives" implies a push that getUpdates does not give. Run-once or long-running?

Review's recommendation: replace "new service" with a source such as `telegram_links` under the collector-split spec, cron about every 5 minutes, with the offset in a one-row main-database table. A long-running service needs an explicit collector-split exception.

Doc lines: 62 (Telegram reader), 148 (Open).

### M6. Expiry clock start and user-curated links (Major)

Question: when does the 48-hour expiry clock start (insert time, published time or message date), does it run while the laptop is off, and should a user-curated Telegram link expire at all, or should only RSS items expire?

Review's recommendation: the clock starts at `queued_at`. On expiry of user-curated links the review asks the question without a recommendation. It also reports that a Friday-evening link is over 60 hours old by Monday.

Proposed by orchestrator draft: the clock starts at `queued_at`, and user-curated Telegram links do not expire (they wait, and are shown); only RSS items expire.

Doc lines: 96 (failure behaviour), 149 (Open).

### M7. Verification set population, size and labeller (Major)

Question: the overview's test set is "30 real filings from the opt-in sample", but filings do not go through the LLM. Which population should be labelled, how big should it be, and who labels it? Thirty items cannot support a recall of 0.90 with any precision.

Review's recommendation: a labelled set of real RSS and Telegram items with negatives drawn from the excluded classes, sized to the target; real samples git-ignored, synthetic fixtures committed; the live precision and recall run is an opt-in script outside the offline command; the test must cover prefilter plus LLM end to end.

Doc lines: 92 (verification), 150 (Open). Overview 6.4 (line 139) also needs the same change; see cross-document items.

### M8. Contract fields: stance, sectors and category (Major)

Question: keep `stance`, `sectors` and the `category` enum in the first contract? The enum is undefined. Macro stance extraction was dropped (overview C4), so `stance` has no consumer.

Review's recommendation: drop `stance` (and probably `sectors`) from the first contract and add later, since `prompt_version` is stored. If `stance` stays, allow it only for macro categories. Use the filings `event_type` values plus news values (`order_win`, `broker_rating`, `credit_rating`, `regulatory`, `macro_*`, and a plain symbol-mention value). Enforce the `reason` length in code. Settle the precedence rule for an opinion piece that names a universe symbol.

Doc lines: 87 (stance), 88 (category), 151 (Open).

### M9. Beat/miss tag data path (Major)

Question: where does the beat/miss value live, who links a news item to the results row, and is the tag built now or deferred?

Review's recommendation: derive it in code from the exact words in the title or description, store it as a field (for example `beat_miss`), name who links it to the results row, or defer the tag explicitly. The word-boundary rule is also missing.

Doc lines: 107 (processed rows), 152 (Open).

### M10. Run counts, failure state and the day boundary (Major)

Question: where are the run counts stored (`collector_runs` has no column for them), is there an `error` count (the six counters do not sum), how is "last successful classification run" stored when the queue is empty, and what timezone defines "the day"?

Review's recommendation: no single recommendation. The review proposes a one-row state table for the last successful run and the LLM-down marker, aligned with the filings spec Z4 counts, and an `error` counter. It also asks how the "news filter unavailable" marker relates to the collector-split `collector_paused` banner.

Doc lines: 99 (counts), 153 (Open).

### M12. Stub scope: own overview section 6, or hold deltas only (Major)

Question: should this doc become the full owner of overview section 6 (LLM and RSS rules), with the overview keeping a link, or hold only deltas, open decisions and new content? The current stub restates about two thirds of the overview.

Review's recommendation: no recommendation in the review. It names both options and notes a trimmed stub could be about 50 lines.

Proposed by orchestrator draft: hold deltas only. The overview stays the owner of the shared rules, so each rule has one owner (overview section 2).

Doc lines: whole doc (structure), 154 (Open).

### M13. Telegram message deletion (Major)

Question: should the bot delete messages from the group at all? Deletion is specified in detail, but no purpose is given, and deleting removes the only durable copy in the group. It also needs admin rights.

Review's recommendation: the bot never deletes (a plain reader). That removes the admin requirement, the 48-hour constraint and an open item. If deletion stays, say what happens when `deleteMessage` fails or the window has passed.

Doc lines: 58 (delete rule), 59 (delete rights), 155 (Open).

### M14. Split the specs and set the build order (Major)

Question: should one build spec cover RSS keyword-only, the LLM stage and Telegram, or three specs written in phase order? The overview fixes RSS first (overview 7.7, C6). The readiness lens would put RSS last (it is OFF by default and the riskiest legally). The zoom-out lens asks whether RSS before Telegram is the right order at all.

Review's recommendation: write three build specs, each only when its phase is next: (1) queue, dedupe and RSS, (2) the LLM stage, (3) Telegram. The gate is the filings spec approval and the collector-split approval. The review says this is the user's call.

Doc lines: 15 (build order), 156 (Open).

### M15. RSS feed set, terms gate and sample capture (Major)

Question: which RSS feeds are in the first slice (11 feeds across two hosts serve two uses, and the LLM stage would also need RBI, Fed and inflation items), and should reading the Investing.com RSS terms be a gate before RSS is enabled? Both hosts' terms prohibit storing. Also, what are the per-host gap and cap values (overview 8.2 item 9)?

Review's recommendation: describe each feed; add a T0-style sample capture with an "unverified" marker, as the filings spec does; make the Investing.com terms reading an explicit gate before RSS is enabled; consider one feed per host in the first slice. For gap and cap, the design lens proposes a randomised gap of a few seconds, one request in flight per host, and a per-run item cap.

Doc lines: 40 to 48 (RSS feeds), 157 (Open).

### M17. Telegram chat type and message shape (Major)

Question: are the links posted in a group or sent to the bot directly? Overview 5.3 says the user sends links to the bot, and overview 7.6 says a group. Also: how are messages with no URL, several URLs, forwards, edits and captions handled, and how is the "title" of a Telegram link made?

Review's recommendation: state which applies (no recommendation given on group versus direct message). For message shape it recommends `allowed_updates=["message"]`, and for title the message text without the URL, else og:title, else the slug. It also asks for URL canonicalisation and an ignore list for X, LinkedIn and shorteners.

Proposed by orchestrator draft: a group, because overview 7.6 is the later section and the rest of the doc assumes a group. The user should confirm.

Doc lines: 53 (Telegram users post), 158 (Open).

## Cross-document items for other owners

These are copied from the review, with current line numbers where the overview has moved. None of these files was edited.

- Overview line 9 (section 1): "None of the split docs has build specs yet" is stale, since the filings spec revision 4 exists. Overview 8.1 item 3 says the same.
- Overview line 106 (section 6.1 step 5): "Items marked not relevant are marked rejected and kept only as counts" conflicts with overview 6.3 (line 120), which keeps terminal rows in `event_intake`. Found while applying the storage decision.
- Overview line 123 (section 6.3): the "superseded" bullet cites news doc lines 82 and 116. Those lines were rewritten, so the cite is stale.
- Overview line 181 (section 7.4): "Rejected items are not stored as event rows (section 6.2)". The rule is in 6.1 step 5 and is now also in 6.3 (see the item above).
- Overview lines 77 (section 5.3) and 193 (section 7.6): direct message to the bot versus group (M17).
- Overview line 98 (section 6) versus line 202 (section 7.7): LLM-only rule versus RSS keyword-only build (B1).
- Overview line 139 (section 6.4): the test set is filings, not news and Telegram (M7).
- Overview line 169 (section 7.3) versus `collector-split-spec.md` line 84: cooldown cap 3 hours versus 2 hours. The filings spec flags this as collector-split S2's.
- `home-events-filings-spec.md` section 5 (review cites line 465): pending overview edits (14 feeds becoming 8, the 7.3 and 7.4 lines). Part of this may already be applied (overview lines 66 and 166); the owner should check.
- `docs/designs/fundamentals-upstox-secondary.md` line 177 cites "section 4.2 of home-event-sources.md" for the Telegram group. The current location is overview section 7.6.
- `docs/designs/ui-redesign-brief.md` line 53 describes the Telegram token as a Docker Swarm secret read from `/run/secrets/`. That conflicts with `secrets-and-roles.md`, which stores it in the secrets store.

## Residual questions inside applied findings (not decided)

These are not separate findings. They remain inside findings the doc already fixed, and need the user if the user wants them settled.

- M2: the link group needs its own chat-ID secret. The name is not chosen (the doc says "name not chosen"). One bot or two (one `getUpdates` poller per token) is also not chosen.
- M5: the review recommends storing no raw Telegram update JSON, because it carries user names and ids. The doc does not say so yet. It also asks who owns purge for queue rows, since the filings spec defers even the events purge.
- N1: the review asks whether the LinkedIn terms reading is needed at all, since LinkedIn links are not queued or fetched.
