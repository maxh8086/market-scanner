# Home events: news RSS, LLM filter and Telegram bot

Status: draft, not approved. Owned rules and decisions follow the overview (sections 6, 7 and 8). Updated 2026-11-10 for the events-database storage decision (overview section 6.3). Build specs are not written yet.
Owner: Vaibhav Pavtekar
Screen: Home, shortlist and event feed (`docs/designs/ui-redesign-spec.md` section 5.1, section 6)
Overview: [home-event-sources.md](home-event-sources.md). Licence and feed rights, event tiers and the shortlist are owned by the overview (section 2). Retention rule: overview section 7.4. Purge owner: `home-events-filings.md` (overview section 2).
Governing specs: [home-events-filings-spec.md](home-events-filings-spec.md) (events database and ingest pattern, sections 4.5 and 4.6; dependencies in section 2) and [collector-split-spec.md](collector-split-spec.md) (runner, due rule, cooldowns, main-database migration numbers).

## Scope

- News RSS feeds, OFF by default (overview section 5.2).
- Telegram link bot. In scope, built later (overview section 7.6).
- Page fetch for queued links, the intake queue and the beat/miss tag (overview sections 6.1, 6.3 and 7.5).
- LLM relevance stage. Kept and in scope, built later (overview section 7.7, C1). Not part of the first build.
- Build order: filings first, then macro, then RSS keyword-only. Telegram, the LLM stage and Upstox come after that (overview section 7.7, C6).

## Storage and ingest (decided 2026-11-10)

- Intake queue: `event_intake` (migration 002, see the allocation table in overview section 6.3). It lives in the events database, separate from the main database. Only the Fastify API reads or writes it.
- Processed news rows: `news_events` (migration 003, same table). Not `home_events`. Filings keep `home_events` unchanged.
- The RSS fetcher and the Telegram reader both feed the same queue, `event_intake`, with the source recorded per row. The LLM worker drains it and writes processed rows to `news_events`.
- Migration numbers come only from the overview 6.3 allocation table. This doc owns 002 and 003 and no other number. Columns: to be specified in the build spec.

Proposed Fastify routes and token roles, in the style of `home-events-filings-spec.md` section 4.6:

| Route (proposed) | Caller | Token role (proposed) | Purpose |
|---|---|---|---|
| `POST /internal/events/intake/rss` | RSS fetcher | `rss_intake_ingest` | Insert raw RSS items into `event_intake`. Dedupe on the hash. Returns counts in the 4.6 style (`inserted`, `duplicates`, `invalid`). |
| `POST /internal/events/intake/telegram` | Telegram reader | `telegram_intake_ingest` | Insert raw Telegram link items into `event_intake`. Dedupe on the hash. Same response as the RSS route. |
| `POST /internal/events/intake/claim` | LLM worker | `news_events_ingest` | Claim `new` rows for a run and set them `processing`. Request and response shape: build spec. |
| `PATCH /internal/events/intake/status` | LLM worker | `news_events_ingest` | Set claimed rows to a terminal status (`kept`, `rejected`, `expired`). Error handling: open (see Open, B5). |
| `POST /internal/events/news/batch` | LLM worker | `news_events_ingest` | Insert processed rows into `news_events` and set their intake rows to `kept`, in one transaction (overview section 6.3). |

- Per-source routes and tokens: decided 2026-11-10 (decision A1 in `docs/progress/home-events-decisions-needed.md`). Each source has its own route and token. RSS and Telegram are treated as two sources (to confirm). The user may discontinue some sources later.
- Route and role names are proposed. The filings route `POST /internal/events/batch` stays filings-only. Each caller uses one bearer token. Token values never go in the repo, a doc or a log.
- The collector and the Telegram poller post through Fastify and never touch the events database. The collector keeps its direct access to the main database (`collector-split-spec.md` section 2, decision 3).
- The Telegram reader needs its own service token to read its secrets through the internal API (`secrets-and-roles.md` decision 10). That token is separate from `telegram_intake_ingest`.
- The Home feed merges `news_events` with `home_events` and the macro rows through Fastify (overview section 6.3). Home read routes are not named here. They belong to the Home read path spec.

## Owned rules

### RSS feeds

- Investing.com (`in.investing.com/rss/`): `news_95`, `news_14`, `news_11`, `news_25`, `news_1061`, `news_1063`, `news_1062` (overview section 5.2).
- CNBC TV18 (`cnbctv18.com/commonfeeds/v1/cne/rss/`): `economy.xml`, `politics.xml`, `market.xml`, `world.xml` (overview section 5.2).
- Use: beat/miss tag on results, and broker upgrades and downgrades.
- Status: OFF by default.
- RSS items older than 1 week are dropped (overview section 7.3).
- Request gap and cap for these hosts: not set. Cooldown rule for these hosts: not set (overview section 7.3, section 8.2 item 9).
- Investing.com RSS terms: not read (HTTP 403). Investing.com prohibits use, storage and reproduction without written permission (overview section 4.1).
- CNBC TV18 prohibits copying, storing, republishing, scraping and database use without written authorisation (overview section 4.1).

### Telegram link bot

- Users post shortlisted links in a Telegram group. The bot is a group admin and saves each link with its message date as it arrives (overview section 7.6).
- Each link is queued with its title, link, page headline and summary. No article body (overview section 5.3).
- LinkedIn links are not queued (overview section 5.3). LinkedIn terms: not read (overview section 8.2 item 15).
- X and Twitter are out of scope. No X content enters the feed or the event tracker (overview section 7.6).
- Hosting: the bot runs on the user's laptop, with no always-on host. It resumes from the last confirmed update (`offset` in getUpdates). Revisit an always-on host if links are lost or the posting pattern changes (overview section 7.6).
- Delete rule: if delete rights are granted, the bot deletes a message only after its row is saved, not after classification. Telegram only allows deleting messages sent less than 48 hours ago, so each link must be saved within that window (overview section 7.6).
- Delete rights: not decided (overview section 8.2 item 2).
- How long Telegram keeps unconfirmed updates: unchecked. This must be checked before laptop-only hosting is accepted (overview section 8.2 item 2).
- Bot token and chat ID: app secrets named `telegram_bot_token` and `telegram_chat_id`. They are read from the secrets store, not from environment variables. No value is written in this doc. The link group needs its own chat-ID secret (name not chosen; see Open).
- Telegram reader: a new service. It needs its own plan before build (overview section 7.6).

### Page fetch

- The collector fetches each publisher page for its og:title (or title) and og:description (or meta description). It stores them for personal use only. No article body text (overview sections 6.1 and 7.6).
- Accepts the terms risk in overview section 4. This does not cover republishing.
- Scope of fetch (Telegram only or RSS too) and the safety limits: open (see Open, B8).

### Intake queue

- Location: `event_intake` in the events database (migration 002). Routes are in the Storage and ingest section above.
- Queue insert fields: source, URL, published time, normalised title, content hash, og:title (or title), og:description (or meta description) (overview section 6.1 step 1). Columns beyond this list: to be specified in the build spec.
- Dedupe by URL and by content hash, at queue insert (overview section 6.1 step 2).
- Telegram dedupe key and gap detector for when the laptop is off: not specified (see Open, B6).

### Keyword prefilter

- Owned by the filings doc (overview section 9.2). This doc uses it. Items with no keyword and no watchlist symbol are marked `prefiltered_out` and do not call the LLM (overview section 6.1 step 3).

### LLM relevance stage

- Kept and in scope. Built after the RSS keyword-only phase (overview section 7.7, C1 and C6).
- Model: the local LLM at `LLM_URL`. No model name is hardcoded (overview section 6.1).
- Raw RSS items never reach the dashboard, the events table or the API response (overview section 6).
- Contract (overview section 6.1 step 4): compact JSON with `relevant`, `category`, `symbols`, `sectors`, `stance`, `reason` (max 25 words). The contract is open (see Open, B5 and M8).
- `stance`: null, "hawkish", "dovish" or "neutral". Open: depends on overview section 8.2 item 1.
- `category` enum: open.
- Relevance criteria (overview section 6.1): an event tier 1 or tier 2 item; an item naming a watchlist or scanner universe symbol; or a macro item on RBI or Fed policy stance, or an India or US inflation release. Not relevant: general market commentary, opinion, sponsored content and duplicate wire copies.
- Timeout, retries, batch size, malformed-JSON handling and prompt-injection defence for untrusted headlines: not specified (overview section 8.2 item 13).
- Third-party risk: if `LLM_URL` moves to OpenRouter, every headline and summary goes to a third party. That move needs its own decision, recorded in the overview first (overview section 6.2).
- Verification: test set and acceptance are open (see Open, M7). Acceptance thresholds: overview section 6.4 (precision at least 0.85, recall at least 0.90).

### Failure behaviour

- If the LLM is down or times out, queued items wait. No item is dropped before the 48-hour expiry (overview section 6.2). Expiry clock and whether user-curated links expire: open (see Open, M6).
- After the LLM has been down for more than one hour, the dashboard shows a "news filter unavailable" marker with the time of the last successful run (overview section 6.2).
- Empty-day rule: when no relevant item has been recorded for the day, the Home feed shows the most recent recorded events by date, with the line "No new news since [time of the last successful classification run]" (overview section 6.2).
- Each run records counts: queued, prefiltered_out, sent_to_llm, relevant, rejected, expired (overview section 6.1 step 6). Where the counts are stored: open (see Open, M10).

### Processed rows (`news_events`)

- Each relevant item becomes one `news_events` row (migration 003). The overview section 6.3 fields are event_id, source, source_url, published_at, classified_at, category, symbols, sectors, stance, reason, model_id, prompt_version and status. The overview section 7.1 event record also lists company, headline, tier and source name. Columns, types and the `status` value set: to be specified in the build spec.
- Every row stores model_id and prompt_version (overview section 6.3), so a re-run can be compared with the first result.
- Rejected items: terminal rows stay in `event_intake` for 14 to 30 days so a re-polled item is not re-queued (overview section 6.3, value open, section 8.2 item 3). They are not stored as `news_events` rows.
- Cross-source duplicates: news rows can duplicate `home_events` (filings) and macro rows. The reconciler that links them is filings spec section 4.4, which is not built. Until it is, news rows show unreconciled. The Home cap of 3 events per stock (overview section 7.1) applies to the merged feed.
- Beat/miss tag: vocabulary is in the next section. Its data path is open (see Open, M9).

### Beat/miss tag (news source)

- Vocabulary: "beat / miss / in line". Labelled "per news". Shown only when the article uses one of those words. Never inferred from numbers. No consensus number is used (overview section 7.5).
- Not a filter, alert or ranking input (overview section 7.5).

## Carried from the overview (not owned here)

- Licence position: overview section 4. Personal use only; the storing and scraping clauses are accepted as a risk. Feed-specific terms: see RSS feeds and Telegram link bot above.
- Event tiers and shortlist: overview sections 7.1 and 7.2.
- Poll schedule and freshness: overview section 7.3. When the laptop is off, nothing polls (overview section 7.3, stated known limit).
- Build order: overview section 7.7.
- Retention rule: overview section 7.4 (3-year rule for event rows; queue rows follow section 6.3). Purge owner: `home-events-filings.md` (overview section 2).
- Keyword lists (order-win and macro/geopolitical): overview section 9.
- Glossary and external terms: overview section 3.

## Build specs (stub, not written)

Missing before any build:

1. Queue DDL and processed-row DDL. Table names chosen (`event_intake` 002, `news_events` 003). Columns to be specified in the build spec.
2. LLM contract: request format, prompt, timeout, batch size, retries, malformed-JSON handling, `category` enum, and prompt-injection defence for untrusted headlines (see Open).
3. Telegram dedupe key and gap detector for when the laptop is off.

Config keys, env and secret names, owner modules, the test set and the acceptance command: to be set in the build spec, following the section 2 structure of `home-events-filings-spec.md`.

## Open

Items marked "Open (user decision)" are findings from the review that need the user. The question and the review's recommendation are in `docs/progress/home-events-news-telegram-decisions.md`.

- Open (user decision), B1: what the RSS keyword-only phase writes, or whether it merges into the LLM phase (see Owned rules, RSS feeds and LLM relevance stage).
- Open (user decision), B5: LLM contract, config names, batch size, timeout, retry, malformed-JSON rule, `category` enum, and prompt-injection defence (overview section 8.2 item 13).
- Open (user decision), B6: Telegram retention limit (unverified: the 24-hour figure is to be confirmed at core.telegram.org/bots/api), offset storage, and the chat allowlist. Overview section 8.2 item 2.
- Open (user decision), B7: prefilter owner and policy, the symbol and alias source for "watchlist", and whether Telegram links bypass the prefilter.
- Open (user decision), B8: page-fetch scope (Telegram only or RSS too), and the request safety and size limits.
- Open (user decision), M3: poll schedule per source, cooldown rows for new hosts, and main-database migration numbers (arbitrated with `collector-split-spec.md`). Events-database numbers 002 and 003 are allocated.
- Open (user decision), M4: Telegram reader as a run-once source or as a long-running service.
- Open (user decision), M6: expiry clock start, and whether user-curated Telegram links expire or are rejected.
- Open (user decision), M7: verification set population, size and labeller (overview section 6.4).
- Open (user decision), M8: `stance`, `sectors` and the `category` enum in the first contract (overview section 8.2 item 1).
- Open (user decision), M9: beat/miss field, detector, and link to the results row, or defer.
- Open (user decision), M10: where the run counts are stored, an `error` count, the state for "last successful run", and the timezone of "the day".
- Open (user decision), M12: whether this doc owns overview section 6 or holds only deltas.
- Open (user decision), M13: Telegram delete rights (overview section 8.2 item 2).
- Open (user decision), M14: order of the build specs (RSS, LLM stage, Telegram) against overview section 7.7.
- Open (user decision), M15: RSS feed set, the host terms gate (Investing.com terms unread, overview section 8.2 item 15), sample capture, and the per-host gap and cap (overview section 8.2 item 9).
- Open (user decision), M17: group or direct message (overview section 5.3 and 7.6 differ), message shape, title and URL rules, and the ignore list for X, LinkedIn and shorteners.
- Terminal-row window in `event_intake`: 14 to 30 days, value open (overview section 6.3, section 8.2 item 3).
- Stance field and definitions: overview section 8.2 item 1 (see M8).
- LinkedIn terms: not read. Whether they are needed at all, since LinkedIn links are not queued, is a user question.
