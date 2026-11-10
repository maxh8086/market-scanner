# Home event feed: sources and decisions

Status: draft, not approved. Decisions recorded 2026-11-09 and 2026-11-10 (section 7). Not approved: approval is pending the blocking items in section 8.
Owner: Vaibhav Pavtekar
Screen: Home, shortlist and event feed (`docs/designs/ui-redesign-spec.md` section 5.1, section 6)

## 1. Split docs

This overview holds the cross-cutting decisions and the licence position. Each source group has its own design doc. The filings spec is at revision 4 (draft, not approved, 2026-11-10). The news, macro and Upstox docs have no build spec yet.

- `docs/designs/home-events-filings.md`: NSE and BSE exchange filings, the events table, keyword rules, order-win rules, retention and the market cap field.
- `docs/designs/home-events-news-telegram.md`: news RSS feeds, the Telegram link bot, the news relevance filter (LLM stage) and the intake queue.
- `docs/designs/home-events-upstox-news.md`: Upstox News per-stock source. Blocked until written confirmation from Upstox.
- `docs/designs/home-events-macro-calendar.md`: macro panel (RBI, Fed, FRED, India CPI) and the economic calendar.

## 2. Ownership

Each rule has one owning doc. Where the owning doc does not yet carry the decided value, this overview keeps it, marked "held here", until the owning doc is updated (section 8).

| Rule | Owning doc | Decided value |
|---|---|---|
| Licence and feed rights | This overview | Here (section 4) |
| Event tiers, feed tiers, shortlist, event fields, Home cap | This overview | Here (section 7.1, 7.2) |
| Request policy: NSE and BSE | `home-events-filings.md` | Here (section 7.3) |
| Request policy: other hosts | Each split doc for its own hosts (section 7.3) | Here; numbers not set |
| Retention (3 years) and purge | `home-events-filings.md` | Here (section 7.4) |
| Keyword lists (order-win, macro and geopolitical) | `home-events-filings.md` | Here (section 9) |
| LLM contract and relevance filter | `home-events-news-telegram.md` | Here (section 6) |
| Macro series and calendar rows | `home-events-macro-calendar.md` | Here (section 10) |
| Upstox gating | `home-events-upstox-news.md` | Here (section 5.4) |

## 3. Glossary

- **ATH**: all-time high. The scanner rule is a new ATH today, or a last price within 26% of the ATH (`scanner/ath.py`, `classify_bucket`, `max_dist=26.0`).
- **UPTREND**: trend class from `scanner/indicators.py` (`classify_trend`). Last price is above both the 50-day EMA and the 200-day SMA.
- **Feed tier**: where an event sits on the Home screen. **High-Priority** is the top alert stream. **Catalyst** is the Catalyst and Momentum Feed (secondary).
- **Keyword level**: A, B or C for an order-win or macro keyword term. Level A has the highest precision. This replaces the word "tier" for keyword lists.
- **Event tier**: the user's tier 1 or tier 2 event types (section 7.1). Tier 1 and tier 2 events are the critical events.
- **Intake queue**: the table where each fetched news or Telegram item waits before its relevance check.
- **Analytics token**: `upstox_analytics_token`, the read-only Upstox token in the secret store (`secrets-and-roles.md`). It covers Upstox News.
- **Blocker**: an item in the blocking list of the six-lens re-review (`docs/progress/home-event-sources-rereview.md`). Section 8.1 lists them.

## 4. Licence and feed rights

The terms of NSE, BSE and the news feeds restrict storing and scraping. The user reads them as allowing personal use and accepts that risk. No redistribution, no public display, no commercial use. Upstox News is blocked until the user has written confirmation from Upstox.

### 4.1 Terms read

Read 2026-11-09 and 2026-11-10. Summaries only.

- NSE (website Terms of Use): no copying, storing, aggregating or distributing without prior written permission. The download exception does not clearly cover RSS. Automated collection and scraping are prohibited. The NSE Data Sharing and Usage Policy was not read.
- BSE: the terms page returned HTTP 403 and was not read. The announcements disclaimer gives information "AS IS". No redistribution or scraping terms found.
- Investing.com: prohibits using, storing, reproducing or distributing site data without written permission. The RSS index returned HTTP 403, so the feed's own terms are unread.
- CNBC TV18: prohibits copying, storing, republishing, scraping and database use without written authorisation. Prohibits repeating stock-call information outside the site. No personal-use carve-out found.
- User's reading (2026-11-09): the reproduction limit applies only when news is published under the user's name or on the user's website. The dashboard is an internal personal reference page. This does not address the storing, scraping and database clauses, which the collector triggers.
- Upstox News: the News page gives no redistribution or storage terms, and forum replies conflict. Written confirmation from Upstox is needed.
## 5. Source registry

### 5.1 Exchange filings (NSE and BSE): Home feed, in scope

Scope: High-Priority and Catalyst feed tiers only. Feed-to-field mapping is owned by the filings doc.

- NSE RSS (`nsearchives.nseindia.com`): `Financial_Results.xml` and `Integrated_Filing_Financials.xml` (results, High-Priority); `Sast_Regulation29.xml` and `Sast_Regulation31.xml` (promoter and insider, High-Priority); `Corporate_action.xml` (Catalyst); `Corporate_Governance.xml` (governance, High-Priority); `Related_Party_Trans.xml` (High-Priority, to confirm); `Online_announcements.xml` (order-win matching, Catalyst); `Shareholding_Pattern.xml` (tier to confirm). `Annual_Reports.xml` is parked.
- BSE XML (`bseindia.com`): `data/xml/announcements.aspx` (order-win matching, Catalyst); `data/XML/CorpActionFeed.aspx` (Catalyst); `Data/XML/FinancialResultsFeed.aspx` (results, High-Priority); `Data/XML/ShareholdingPattern_Feed.aspx` (tier to confirm); `data/xml/notices.xml` (board-meeting notices excluded; other content to check). `Data/XML/AnnualReportFeed.aspx` is parked.

Update 2026-11-10 (filings spec revision 4): the first build requests 8 NSE feeds only. `Online_announcements.xml` (order-win) is deferred (Q2) and all five BSE feeds are deferred (Z2). `Related_Party_Trans.xml` and `Shareholding_Pattern.xml` are on by default with a provisional tier (Q4).

### 5.2 News RSS: beat/miss and broker ratings

- Investing.com (`in.investing.com/rss/`): `news_95`, `news_14`, `news_11`, `news_25`, `news_1061`, `news_1063`, `news_1062`.
- CNBC TV18 (`cnbctv18.com/commonfeeds/v1/cne/rss/`): `economy.xml`, `politics.xml`, `market.xml`, `world.xml`.

Use: beat/miss tag on results, and broker upgrades and downgrades. RSS is OFF by default.

### 5.3 Telegram link bot: in scope, built later

The user sends news links to a Telegram bot. Each link is queued with its title, link, page headline and summary, and no article body. X links are ignored. LinkedIn links are not queued. The bot runs on the user's laptop for now (section 7.6).

### 5.4 Upstox News (per stock): blocked

Source: `GET https://api.upstox.com/v2/news` (the News endpoint of the official SDK), authenticated with the read-only analytics token. No static IP is needed.

- Category `instrument_keys`. Keys are `NSE_EQ|<ISIN>`, built from `symbol_sector.isin` (751 rows, all with an ISIN). Up to 30 keys per request, so the watchlist and scanner universe are batched in groups of 30. Each item is expected to carry its instrument key, so the symbol is known before the relevance check (section 6.1). Present or absent: unverified until a redacted sample is captured (decision D2 in `docs/progress/home-events-decisions-needed.md`).
- The endpoint returns about the last 7 days. Poll once a day, store new items, dedupe by `article_link`. This is the one exception to the schedule in section 7.3: a daily poll loses nothing only while the collector runs at least once in each 7-day window (`collector-split-spec.md` section 5, risk 5). A host that is off for longer loses items older than the window.
- Stored: headline, summary, link, source name `Upstox`, and the instrument key (present or absent: unverified, see D2). No article body. The 1-week age limit is proposed (section 8).
- `positions` and `holdings` categories returned 0 records with no error (2026-11-10 test). Not used.
- Rate limits: assumed to be Upstox's "Other Standard APIs" class (50/s, 500/min, 2000 per 30 minutes per user), as in the fundamentals doc. The News page class was not checked. No daily limit applies (project owner, 2026-11-10).
- Status: OFF by default, and blocked until written confirmation from Upstox (section 4).

### 5.5 Macro and calendar sources

- RBI press releases: `rbi.org.in/pressreleases_rss.xml`, priority 1 (MPC resolutions, repo rate, stance, inflation projections, MPC votes). Keyword filter: "Monetary Policy", "Repo Rate", "Inflation", "MPC", "Stance". `Publication_rss.xml` and `speeches_rss.xml` are dropped (C4).
- Federal Reserve: `federalreserve.gov/feeds/press_monetary.xml` (FOMC statements and monetary policy releases).
- FRED API: key in the env var `FREDAPI_KEY` (in `.env`; not verified in this session). Series: `CPIAUCSL` and `FEDFUNDS` only (C4).
- MoSPI India CPI calendar and press releases (section 10). BLS calendar for US CPI dates. Fed calendar page for FOMC dates.

## 6. News relevance filter (LLM stage)

Decision: the LLM stage is kept and in scope. It is built after the RSS keyword-only phase (section 7.7). The dashboard shows only news and feed items that a local LLM marks relevant. Raw RSS items never reach the dashboard, the events table or the API response.

### 6.1 Pipeline

1. Fetch RSS items on a schedule. Fetching does not depend on the LLM. Each new item goes into the intake queue with source, URL, published time, normalised title, content hash, the page's og:title (or title) and og:description (or meta description). No article body text.
2. Deduplicate by URL and by content hash, at queue insert.
3. Keyword prefilter (section 9). Items with no keyword and no watchlist symbol are marked `prefiltered_out` and do not call the LLM.
4. When the LLM is available, a worker drains the queue in batches, oldest first. Each item is classified once by the local LLM at `LLM_URL`, with no model name hardcoded. The model returns compact JSON only: `{"relevant": true|false, "category": "<tier or macro>", "symbols": [], "sectors": [], "stance": null|"hawkish"|"dovish"|"neutral", "reason": "<max 25 words>"}`. The `stance` field depends on open item 1 (section 8).
5. Relevant items are written to the event tracker (section 6.3). Items marked not relevant are marked `rejected` and kept as terminal `event_intake` rows for 14 to 30 days (section 6.3), then purged. Only the per-run counts are kept otherwise.
6. Each run records counts: queued, prefiltered_out, sent_to_llm, relevant, rejected, expired.

Criteria for relevant: an event tier 1 or tier 2 item (section 7.1); an item naming a symbol in the watchlist or scanner universe; or a macro item on RBI or Fed policy stance, or an India or US inflation release. Not relevant: general market commentary, opinion, sponsored content and duplicate wire copies.

### 6.2 Failure behaviour

- If the LLM is down or times out, queued items wait and nothing is dropped. A queued item expires after 48 hours if still unprocessed, is counted as `expired`, and is never shown. After the LLM has been down for more than one hour, the dashboard shows a "news filter unavailable" marker with the time of the last successful run.
- Exchange filings and the economic calendar do not depend on the LLM. The Haiku fallback in CLAUDE.md applies to development tasks, not to runtime classification.
- Third-party risk: if `LLM_URL` moves to OpenRouter, every headline and summary in the queue goes to a third party. That move needs its own decision, recorded here first.
- Empty-day rule: when no relevant item has been recorded for the day, the Home feed shows the most recent recorded events by date, with the line "No new news since [time of the last successful classification run]".
### 6.3 Event tracker storage

- **Storage decision (2026-11-10, user: "go ahead").** One separate events database holds events from all sources (filings spec D8). Only the Fastify API touches it (D9). Mongo is not used: Postgres `jsonb` holds raw payloads, and promotion from raw to processed stays in one transaction.
  - `event_intake` (staging, new, to be specified): every raw news or macro item, with its `jsonb` payload, source, dedupe hash, status (`new`, `processing`, `kept`, `rejected`, `expired`) and an expiry date. Terminal rows (`rejected`, `expired`) are kept 14 to 30 days (value open) so a re-polled item is not re-queued or re-classified. This is retention separate from the 3-year rule for event rows (section 7.4).
  - `home_events` (processed filings): as approved in the filings spec, NSE only, unchanged. Filings skip staging because they are structured and rule-filtered.
  - Processed news rows and processed macro and calendar rows: separate tables in the same events database, because their columns differ from filings (no ISIN or symbol required; summary, category, stance and LLM fields). The Home feed merges them through Fastify. Table names, columns and migration numbers (`002` onward in the events series) are owned by the news, macro and Upstox docs, and the numbers must be allocated once.
  - Superseded: the earlier idea of reusing `home_events` for news (news doc, "Storage and ingest" section) and of putting these tables in the main database.
- **Events-database migration allocation (single source, 2026-11-10).** Series `db/events_migrations/`, own `schema_migrations`. Other docs cite this table and do not choose numbers. A new claimant adds a row here first.

  | No. | Table | Owner doc | Status |
  |---|---|---|---|
  | 001 | `home_events` (NSE filings) | `home-events-filings-spec.md` 4.1 | built, merged (T2a, PR #75) |
  | 002 | `event_intake` (staging for news and macro items; shared by the news, Upstox news and macro docs) | `home-events-news-telegram.md` | proposed |
  | 003 | `news_events` (processed news, incl. Upstox news) | `home-events-news-telegram.md` | proposed |
  | 004 | `macro_events` (processed macro releases and calendar entries) | `home-events-macro-calendar.md` | proposed |
  | 005 | reserved: a separate calendar table, only if the macro doc splits 004 in two | `home-events-macro-calendar.md` | reserved |
  | 006 onward | unallocated | | |

  The main-database migration numbers are separate and are allocated in `collector-split-spec.md`. Each processed table is written only through a Fastify ingest route with its own token role (filings: `home-events-filings-spec.md` 4.6; pattern: `secrets-and-roles.md`).
- Each relevant item becomes one event row with: event_id, source, source_url, published_at, classified_at, category, symbols, sectors, stance, reason, model_id, prompt_version, status. Every row stores model_id and prompt_version, so a re-run can be compared with the first result.
Ingest routes and token roles (proposed). Decided 2026-11-10 (decision A1): each source has its own route and token. RSS and Telegram are treated as two sources (to confirm).

| Route (proposed) | Caller | Token role (proposed) |
|---|---|---|
| `POST /internal/events/intake/rss` | RSS fetcher | `rss_intake_ingest` |
| `POST /internal/events/intake/telegram` | Telegram reader | `telegram_intake_ingest` |
| `POST /internal/events/intake/upstox` | Upstox news poller | `upstox_news_ingest` |
| `POST /internal/events/news/batch`, plus the claim and status routes | LLM worker | `news_events_ingest` |
| `POST /internal/events/macro` | macro source | `macro_ingest` |
| `POST /internal/events/batch` | filings | `home_events_ingest` |

### 6.4 Verification

- Test set: 30 real filings from the opt-in sample. This replaces the earlier 100-item set.
- Acceptance: precision at least 0.85 and recall at least 0.90. Re-measure after any change to the prompt, the model or the criteria.

## 7. Decisions recorded 2026-11-09 and 2026-11-10

### 7.1 Event scope and display

- Events that matter: event tiers 1 and 2 (results, promoter and insider trades, regulatory actions, order wins, rating changes, corporate actions). Standard board-meeting notices and routine compliance notices are excluded.
- Sources: exchange filings for the High-Priority and Catalyst tiers. Broker rating changes come from news RSS. Credit-rating agency actions come from exchange filings.
- High-Priority Alert Stream (top of feed): results, with the beat/miss tag (section 7.5); regulatory and legal filings (SEBI orders, exchange clarifications, auditor resignations, governance flags); significant insider transactions, meaning promoter open-market buys and sells above a threshold percentage (threshold open).
- Catalyst and Momentum Feed (secondary): major order wins and joint ventures, filtered by contract value relative to market cap (threshold open); back-to-back wins within a month or quarter, flagged (threshold open); brokerage and credit-rating revisions with target-price changes; corporate action ex-dates (buybacks, dividends, rights issues).
- Critical events: event tier 1 and tier 2 events. They are kept long term and shown on the stock's timeline. The 30-day price-impact tracking is deferred (C5).
- Event record fields: company, event type, time, headline, source link, tier, source name, plus the classification fields in section 6.3.
- Home cap: at most 3 events per stock on the Home feed. This is a display cap only, not a storage limit. Every event stays on the stock's own timeline.
### 7.2 Shortlist

A stock is on the Home shortlist only if all three hold:

1. It is an ATH-scan match (section 3): a new ATH today, or a last price within 26% of its all-time high.
2. Its trend is UPTREND (section 3).
3. It has at least one corporate-event factor: `bonus_issue`, `demerger`, `orderbook_signal` or `expansion_signal` (`scanner/factors.py`). `factors_matched` is a local count in the enrichment code, not a function.

The shortlist is the intersection of the three. On the 2026-09-28 full run this gave 39 names (298 matches, of which 39 are UPTREND with at least one factor), per `handoff.md`. The event feed lists events; the shortlist lists stocks.

### 7.3 Freshness, poll schedule and request policy

- Alerts arrive within minutes while the collector runs. Each item shows when it was fetched. When the laptop is off, nothing polls, and this is a stated known limit.
- Poll every 5 minutes from 08:00 to 15:30 IST on trading days, and every hour at all other times, including when the market is closed. **Exchange filings (spec 5, 2026-11-10):** every 5 minutes, weekdays 08:00 to 20:55 IST (cron `*/5 8-20 * * 1-5`), because most results are filed after 15:30; the hourly off-hours poll is not built for filings. Trading days follow the NSE/BSE calendar. Upstox News is the exception and is polled once a day (section 5.4).
- Exchange filings and the economic calendar are the default sources. RSS stays OFF by default. RSS items older than 1 week are dropped; the same limit is proposed for Upstox News (section 8).
- NSE and BSE: 14 feeds were planned (section 5.1); the first build has 8 NSE feeds (see the section 5.1 update). They are requested one at a time per exchange, with a random gap of 5 to 8 seconds before each request, polled only on the schedule above. The 2 parked feeds are never requested. Exponential backoff on HTTP 429 or 403.
- Cooldown on failure: 15 minutes for the first pause, doubling on each further failure, capped at 3 hours. While paused, the dashboard shows a "source paused" marker. This replaces the earlier 24-hour kill switch. The policy is self-imposed; no NSE or BSE limit is published.
| Host | Owning doc | Gap | Cap | Status |
|---|---|---|---|---|
| NSE, BSE | `home-events-filings.md` | 5 to 8 s random, one request per exchange | Cooldown above | Set |
| Investing.com, CNBC TV18 (RSS) | `home-events-news-telegram.md` | Not set | Not set | Open |
| RBI, Federal Reserve, FRED, BLS, MoSPI | `home-events-macro-calendar.md` | Not set | Not set | Open |
| Upstox | `home-events-upstox-news.md` | Not set | Upstox class assumed (section 5.4) | Open |

### 7.4 Retention and storage

- All event rows, including news titles, links and Telegram updates, are kept for 3 years, then purged. There is no licence for news content, and the user accepts that risk.
- Amended 2026-11-10 (section 6.3): news and macro items that are rejected or expired stay in `event_intake` as terminal rows for 14 to 30 days (value open), only so they are not re-queued; they are then purged. Filings have no staging rows.
- Rejected items are not stored as event rows (section 6.1 step 5 and section 6.3). Per-run counts are the only trace; for exchange filings they are kept in the run message (`collector_runs.message`), not in stored columns (filings spec 5.2).

### 7.5 Beat/miss tag and market cap

- Vocabulary: "beat / miss / in line" everywhere (2026-11-10). The tag is labelled "per news" and shows only when the article itself uses one of those words. It is never inferred from numbers, and no consensus number is used. The source headline and link show next to it.
- The tag is not a filter, alert or ranking input. Revisit this if it is ever used to drive a decision.
- Market cap column: `mcap_cr` (approved 2026-11-10), in crore. It matches `scanner/fundamentals.py:38`, which maps "Market Cap" to `mcap_cr`. It is computed as price times shares, where shares are equity capital divided by face value (`scanner/fund_derive.py:195`; basis label checked 2026-11-10).
- Refresh: on the next fundamental data refresh, and from the Upstox realtime and end-of-day feed when the price source is Upstox. The Upstox company profile does not return the company's own market cap.
- Fundamentals tables (company profile, plus one table per Upstox endpoint: balance sheet, cash flow, income statement, share holdings, key ratios, corporate actions, competitors) are held here until moved to the filings doc (C3). No DDL is built.

### 7.6 Telegram link intake and X

- Telegram link intake is kept and in scope. The user posts shortlisted links in a Telegram group. The bot is a group admin and saves each link with its message date as it arrives.
- Delete rights are not decided (section 8). If granted, the bot deletes a message only after its row is saved, not after classification. Telegram only allows deleting messages sent less than 48 hours ago, so each link must be saved within that window.
- Hosting: the bot runs on the user's laptop, with no always-on host. It resumes from the last confirmed update (`offset` in getUpdates), because getUpdates has no time filter. Links posted while the laptop is off are picked up only if Telegram keeps unconfirmed updates long enough (unchecked, section 8). Revisit an always-on host if links are lost or the posting pattern changes.
- Page fetch: the collector fetches each publisher page for its headline and summary and stores them for personal use, accepting the terms risk in section 4. No article body text. This does not cover republishing.
- The Telegram reader is a new service and needs its own plan before it is built.
- X / Twitter: out of scope. No X API, no manual paste into the intake queue, no scraping or automating a logged-in X session. No X content enters the feed or the event tracker.

### 7.7 Build order, testing and cuts

- Build order (approved 2026-11-10, C6): filings first; then macro (the 4 calendar rows); then RSS keyword-only. Telegram, the LLM stage and Upstox come later.
- Cuts approved 2026-11-10: C3 (fundamentals tables and keyword reconciliation move into the filings doc); C4 (macro uses 4 calendar rows seeded by hand, and FRED `CPIAUCSL` and `FEDFUNDS` only; RBI priorities 2 and 3, the speeches feed and stance extraction are dropped); C5 (30-day price-impact tracking deferred); C6 (build order above).
- Not cut: the LLM stage (C1) and the Telegram bot (C2) are kept.
- Live-feed tests are opt-in and run outside the offline test command. The offline command (`.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`) uses recorded samples only and never calls the network.

## 8. Open items

### 8.1 Blocking items from the re-review

1. Status and "Still open" text: resolved by this rewrite.
2. Licence wording: resolved (section 4).
3. Split docs: open. The filings spec is at revision 4 (draft, not approved); the news, macro and Upstox docs have no build spec yet. Owner: each split doc (item 9).
4. Events DDL and dedupe key: drafted in `home-events-filings-spec.md` (revision 4), awaiting approval. BSE scrip code map: deferred with BSE (Z2). Owner: `home-events-filings.md` (item 11).
5. Rate-limit and kill-switch policy: partly resolved (section 7.3). Open: per-host numbers and cooldown (8.2 item 9). The cycle budget is resolved (8.2 item 10).
6. Wrong data facts: resolved here (`CPIMEDSL` removed, MoSPI 16:00 IST, `mcap_cr`). The split docs still carry old values (item 14).
7. Dangling and stale references: resolved here (sections renumbered). The split docs still cite old numbers (item 14).
8. Undefined thresholds: open (items 6, 9 and 10).
9. Governance rules: open for purge owner and schedule, rejected-row retention and Telegram retention (items 2, 3, 6 and 10). "Critical" for retention is defined in section 7.1.

### 8.2 Open items by owner

1. **Open.** The `stance` field in the LLM contract and the macro stance definitions (section 10.1), now that C4 drops stance extraction. Owner: `home-events-news-telegram.md` (contract); `home-events-macro-calendar.md` (panel).
2. **Open.** Whether the Telegram bot gets delete rights, and how long Telegram keeps unconfirmed updates (checked before laptop-only hosting is accepted). Owner: `home-events-news-telegram.md`.
3. **Proposed, not decided.** Rejected rows kept 30 days as a hash and a reason, so recall can be audited. Owner: `home-events-news-telegram.md`.
4. **Decided as deferred, 2026-11-10 (Z5).** Purge job: the future design is a purge inside the `home_filings` run (filings spec D5). Not built in the first build. Owner: `home-events-filings.md`.
5. **Proposed, not decided.** The meaning of "critical event" for impact tracking, once C5 is lifted. Owner: `home-events-filings.md`.
6. **Proposed, not decided.** Thresholds to set before build: significant insider trade (percentage), order-to-market-cap ratio, and back-to-back wins. Owner: `home-events-filings.md`.
7. **Proposed, not decided.** Trading-day calendar source. The working assumption is the NSE/BSE calendar. Owner: `home-events-macro-calendar.md`.
8. **Proposed, not decided.** Upstox News 1-week age limit and OFF by default (section 5.4). Owner: `home-events-upstox-news.md`.
9. **Open.** Per-host gap and cap numbers for RSS, RBI, Federal Reserve, FRED, BLS, MoSPI and Upstox, and the cooldown rule for hosts other than NSE and BSE (section 7.3). Owner: each split doc.
10. **Resolved 2026-11-10, revised.** Cycle budget: the first build has 8 NSE feeds per cycle, 40 to 64 s in gaps, worst case 224 s inside a 240 s run deadline (filings spec 5.3). Earlier figure: 14 feeds, 70 to 112 s. Owner: `home-events-filings.md`.
11. **Drafted, awaiting approval.** Events DDL, NSE cookie and header handling, failure behaviour and dedupe key are in `home-events-filings-spec.md`. Feed-to-field mapping for the 8 first-build feeds waits for the samples (spec T0). BSE scrip code map: deferred (Z2). Owner: `home-events-filings.md`.
12. **Open.** Keyword reconciliation: each term added to `scanner/factors.py` is reviewed one by one, the term table (section 9.1) moves to the filings doc (C3), and the "Contract" rule, "ORDER BOOK" and bare "AWARDED", L1 bidder and PPA terms, and optional level C terms are decided. Owner: `home-events-filings.md`.
13. **Open.** LLM stage: the 30 labelled real filings from the opt-in sample (with negatives), the prompt, timeout, retries, malformed-JSON handling, injection defence for untrusted headlines, category enum and queue DDL. Owner: `home-events-news-telegram.md`.
14. **Open.** Split docs still use stale section numbers and status text, and must match this overview. Owner: each split doc.
15. **Open.** Terms not yet read: NSE Data Sharing and Usage Policy; BSE terms page (HTTP 403); Investing.com RSS terms (HTTP 403); LinkedIn; Upstox API terms and developer agreement. Owner: `home-events-filings.md` (NSE, BSE); `home-events-news-telegram.md` (Investing.com, LinkedIn); `home-events-upstox-news.md` (Upstox).
16. **Open.** Macro: RBI and Fed poll cadence; alert lead times for rate decisions and CPI; the FRED pass condition for checking the series IDs. Owner: `home-events-macro-calendar.md`.
17. **Open.** India CPI: ingestion job spec (source page, parsing, DDL, schedule, failure handling; the job is decided, its spec is not written). Dates after 12 Nov 2026 come from the MoSPI advance release calendar. Release time 16:00 IST (user-confirmed 2026-11-10); a MoSPI page must still confirm it. Owner: `home-events-macro-calendar.md`.
18. **Blocked.** Written confirmation from Upstox that News may be stored and shown for personal use (section 4). Owner: `home-events-upstox-news.md`.
19. **Open.** Upstox: batch failure handling for 30-key requests, and a check of the News page rate-limit class. Owner: `home-events-upstox-news.md`.
20. **Open.** Approval of this overview waits for items 3 to 9 in section 8.1. Approval of each split doc waits for its build specs. Owner: this overview.

## 9. Keyword lists

### 9.1 Order-win terms: merged list

Decision (2026-11-10): merge the draft list below with the production lists in `scanner/factors.py`. Each term added to `factors.py` is reviewed one by one before the change. Nothing in code changes from this doc.

- Matching rule (as in `matches_orderbook`, `scanner/factors.py:828-847`, checked 2026-11-10): a row is excluded when its description is in `ORDERBOOK_DESC_EXCLUDE`. It is an order win when its description is in `ORDERBOOK_DESC_CATEGORIES` (exact match), or when its attachment text contains a keyword term as an uppercased substring. Descriptions are never matched by substring. The same rule applies to the merged list once it is in code.
- Keyword level A (highest precision): "Letter of Award", "LoA", "Award of order", "Receipt of order", "Work order", "Purchase order", "Bagged order", "Bags contract", "Order win".
- Keyword level B (tender and stage gates): "LOI", "L1 bidder", "Lowest bidder", "Concession agreement", "Power Purchase Agreement", "PPA". "Contract" only with "awarded", "secured" or "signed".
- Keyword level C (sector terms, optional): "EPC contract", "Commercial operations", "Ministry of Defence", "MoD", "Procurement order", "Supply contract", "Multi-year deal", "Digital transformation contract", "Managed services agreement".
Reconciliation with `scanner/factors.py` (checked 2026-11-10; held here until moved to the filings doc):

- Already covered: Letter of Award, Receipt of order, Work order, Order win. Bagged is covered as a substring (`BAGGED`); keep the phrase too.
- Add, after review: LoA (may match unrelated text); the "Award of order" form (`factors.py` has "AWARDING OF ORDER"); Purchase order (may appear in purchase-side disclosures); "Bags contract" (`factors.py` has only `BAGGING`); the LOI abbreviation, word-bounded (`factors.py` has the phrase only).
- Review: L1 bidder and lowest bidder are tender stage, not wins. Concession agreement and PPA are sector terms, for the filings doc. The "Contract" rule is a word combination, not a keyword list.
- In `factors.py` only: `ORDER BOOK`, `ORDER INFLOW`, `AWARDED` (alone), `BAGGING`, `SECURED AN ORDER`. `ORDER BOOK` and bare `AWARDED` can appear in results commentary. Keep or tighten after review.
- Keep: `ORDERBOOK_DESC_CATEGORIES` ("BAGGING/RECEIVING OF ORDERS/CONTRACTS", "AWARDING OF ORDER(S)/CONTRACT(S)"), the strongest signals; and `ORDERBOOK_DESC_EXCLUDE` (the three "orders passed" or litigation categories), without which court and regulatory "orders" would read as wins.

Test on the first Telegram batch (9 Nov 2026, 21 headlines chosen by the user): 0 of 21 match the order-win draft, because the batch is macro, market and corporate news. Testing against real filings for false positives, such as generic "contract" notices, is still open (section 8).

### 9.2 Macro and geopolitical terms

The prefilter matches any of these, case-insensitive, as whole words or phrases:

- Central banks: RBI, Reserve Bank, Monetary Policy, Repo Rate, MPC, Fed, Federal Reserve, FOMC, rate cut, rate hike, rate decision.
- Inflation releases: inflation, CPI, PCE.
- Geopolitical and trade (wider than the criteria in section 6.1; kept so the LLM sees them, to be confirmed): sanctions, tariff, tariffs.

Test on the 21-headline batch: 2 match (items 11 and 21). 16 of 21 entries used the URL slug instead of a headline, and 4 slugs are share-link IDs that cannot match. All 21 were chosen by the user, so the batch cannot measure false positives.

## 10. Macro panel and economic calendar

### 10.1 Macro panel

- Scope: rate decisions, stance and inflation, in a separate panel from the stock event feed. Whether rate decisions also appear in the Home feed is open: section 7.1 sets no rule for it. See the macro doc Open list, item B2 (decisions file, C2).
- RBI: priority 1 press releases only. Priorities 2 and 3 and stance extraction are dropped (C4).
- Stance definitions, kept pending open item 1. Hawkish: prioritises inflation control, signals readiness to raise or keep rates high. Dovish: prioritises growth, signals readiness to cut rates or add liquidity. Neutral: no bias; future moves depend on incoming data.
- Action and stance are separate fields. The action is the rate change (for example, a 25 bp cut). The stance is the signal that comes with it. A cut can come with a hawkish stance, and a hold with a dovish one.
- FRED series: `CPIAUCSL` (headline CPI) and `FEDFUNDS` only. `CPIMEDSL` is removed: it is the medical-care component of CPI, not headline inflation (user, 2026-11-10).
- India CPI: MoSPI, monthly, not real time. No official high-frequency India inflation series exists. The release is at 16:00 IST (confirmed by the user, 2026-11-10). The value is ingested by a job, not entered by hand. The 4 calendar rows are hand-seeded dates only. If a release is missed, the next available slot after the data release is used.
### 10.2 Calendar rows

| Event | Country | Next date | Source | Status |
|---|---|---|---|---|
| CPI, October 2026 data | India | 12 Nov 2026, 16:00 IST | MoSPI advance release calendar 2026-27 | Date in the September 2026 press release. Time confirmed by the user; no MoSPI page confirms it yet (section 8) |
| CPI, October 2026 data | US | 10 Nov 2026, 8:30 a.m. ET (19:00 IST) | BLS CPI schedule | Confirmed on the BLS page (2026-11-09). Released 10 Nov 2026. Next release 10 Dec 2026 (November data), time unverified |
| MPC decision | India (RBI) | 4 Dec 2026 (meeting 2 to 4 Dec), unverified | RBI schedule page, `rbi.org.in/SCRIPTs/Annualpolicy.aspx` (dated 23 Mar 2026) | Unverified. The page's own status text says the December decision has no date yet, which conflicts with 4 Dec. Decision time not given |
| FOMC meeting | US (Fed) | Statement 9 Dec 2026, 2:00 p.m. ET (meeting 8 to 9 Dec); 00:30 IST on 10 Dec | Fed December 2026 calendar | Press conference 2:30 p.m. ET. Minutes due 30 Dec |

### 10.3 Calendar conventions

- Source hierarchy: each row stores its official source URL and the date checked. Third-party dates are marked "unverified" until checked against the official page.
- Storage: table `macro_events` (migration 004, events database; section 6.3), holding calendar rows (event, country, scheduled UTC time, source URL, checked date, status), read through the Fastify API. The browser does not read the database directly.
- Time zones: store in UTC with the local zone; display in IST. US releases at 8:30 a.m. ET are 19:00 IST in winter (EST) and 18:00 IST in summer (EDT).
- Refresh and holidays: refresh once when a new calendar is published, and re-check after each release. Keep dated rows, not a formula; CPI moves to the next working day on a weekend or holiday.
- Data sources: BLS for US release dates (CPI, jobs, PPI); FRED for US series values; the Fed calendar page for FOMC dates (FRED does not carry them); RBI press releases for MPC dates, decisions and the repo rate; the MoSPI calendar for India CPI. Investing.com, Financial Modeling Prep and Trading Economics are not used.
- FRED terms: personal use is allowed. Series marked "Copyright" in their notes are owned by third parties, and using them outside personal use needs the owner's permission. The key is in the env var `FREDAPI_KEY`, not in the repo.
- Scope: the four events above, with the countdown and lead times open (section 8). Others (for example, India IIP, GDP, US payrolls) only if asked.

### 10.4 Conflicts resolved

- RBI repo rate after the 5 to 7 Oct 2026 meeting: raised by 25 bps to 5.50%. SDF is 5.25%, MSF and Bank Rate are 5.75%, and the stance changed to calibrated tightening (RBI press release dated 7 Oct 2026, checked 2026-11-09). Earlier 5.25% repo figures are stale.
- FOMC December statement: 9 Dec 2026, not 16 Dec. The March 2026 FOMC is 17 to 18 Mar (19 Mar was wrong).
- MoSPI release time: 16:00 IST, confirmed by the user (2026-11-10). Secondary sources say 4:00 p.m.; no MoSPI page confirms either yet (section 8).

## 11. Links

- Spec: `docs/designs/ui-redesign-spec.md` (sections 5.1, 5.4, 6)
- Brief: `docs/designs/ui-redesign-brief.md` (Events and alerts)
- Re-review: `docs/progress/home-event-sources-rereview.md`
