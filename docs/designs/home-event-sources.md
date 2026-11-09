# Home event feed: sources and decisions

Status: brainstorm in progress. Not approved. No code written.
Owner: Vaibhav Pavtekar
Screen: Home, shortlist and event feed (`docs/designs/ui-redesign-spec.md` section 5.1, section 6)

## 1. Decisions so far

| # | Question | Decision | Source |
|---|---|---|---|
| 1 | Which events matter | Tiers 1 and 2 from the user's list (results, promoter and insider trades, regulatory actions, order wins, rating changes, corporate actions). Standard board-meeting notices are filtered out | User, 2026-11-09 |
| 2 | Where events come from | Exchange filings (NSE and BSE) for the **High-Priority** and **Catalyst & Momentum** feed tiers only | User |
| 3 | Beat/miss tag on results | From news RSS feeds. Open risk: the tag relies on media wording, not a verified consensus number | User; see section 5 |
| 4 | Broker rating changes | From news RSS feeds | User |
| 5 | Credit-rating agency actions | From exchange filings | User |
| 6 | Order win relative to market cap | Market cap is available in our data. Confirm the exact field and its refresh rate | User; to confirm |

## 2. Relevance filter for news feeds (decision)

**Decision (2026-11-09, updated the same day):** The dashboard shows only news and feed items that a local LLM marks as relevant to the criteria below. Raw RSS items never reach the dashboard, the events table or the API response. Items are processed whenever the LLM is available, and every relevant result is written to the event tracker and kept for future use.

**Pipeline**
1. Fetch RSS items from the sources in section 4.2 on a schedule. Fetching does not depend on the LLM. Each new item is written to an intake queue with: source, URL, published time, normalised title, and a content hash. The queue stores the title and link only, not article text.
2. Deduplicate by URL and by content hash, at queue insert.
3. Keyword prefilter (the draft filter in section 6). Items with no keyword and no watchlist symbol are marked "prefiltered_out" and do not call the LLM.
4. When the LLM is available, a worker drains the queue in batches, oldest first. Each remaining item is classified once, using the local LLM through tokenfrugal (`thinker` role). No model name is hardcoded in the app. The model returns compact JSON only: `{"relevant": true|false, "category": "<tier or macro>", "symbols": [], "sectors": [], "stance": null|"hawkish"|"dovish"|"neutral", "reason": "<max 25 words>"}`.
5. Items with `relevant` set to true are written to the event tracker (section 2.1 below). Items marked not relevant are marked "rejected" in the queue and kept only as counts.
6. Each run records counts: queued, prefiltered_out, sent_to_llm, relevant, rejected, expired.

**2.1 Event tracker storage**
- Each relevant item becomes one event row with: event_id, source, source_url, published_at, classified_at, category, symbols, sectors, stance, reason, model_id, prompt_version, status.
- Store the model_id and prompt_version on every row, so a later re-run can be compared with the first result.
- Rows are kept for future use (history, review, and later back-testing). The dashboard reads only a recent window (for example the last 7 days). The window is a display setting, not a deletion rule.
- The retention period for stored titles and links is an open question (section 7), together with the licence check for long-term storage.

**Criteria for "relevant"**
- A tier 1 or tier 2 event from section 1 (results, guidance, order wins, brokerage rating changes, rating-agency actions).
- The item names a symbol in the watchlist or the scanner universe.
- A macro item on RBI or Fed policy stance (section 4.3) or an India or US inflation release.
- Anything else is not relevant. General market commentary, opinion pieces, sponsored content and duplicate wire copies are not relevant.

**Failure behaviour**
- If the LLM is down or times out, queued items wait. Nothing is dropped while they wait. A queued item expires after 48 hours if it has still not been processed. Expired items are counted as "expired" and never shown. The dashboard shows a "news filter unavailable" marker with the time of the last successful run, once the LLM has been down for more than one hour.
- Exchange filings (section 4.1) and the economic calendar (section 8) do not depend on the LLM and keep updating.
- The Haiku fallback in CLAUDE.md applies to development tasks, not to runtime classification.

**Verification before launch**
- Build a labelled set of at least 100 items (relevant or not) from real feed output, and measure precision and recall of the LLM filter against it.
- Set the acceptance thresholds before measuring. They are an open decision (see section 7, still to decide).
- Re-measure after any change to the prompt, the model or the criteria.

**Consequences**
- Fewer items on screen, so each shown item has a classified reason the user can read.
- Latency: processing lag is recorded per item as `classified_at` minus `published_at`. It grows during LLM outages and returns to normal when the LLM is back. Each shown event carries its `classified_at` time.
- Items rejected by the LLM are not stored, so the user cannot see them. Per-run counts are the only audit trail for rejections.

## 3. Feed tiers (what the Home screen shows)

**High-Priority Alert Stream (top of feed)**
- Earnings and financial results. Tag: beat or miss vs estimates (see section 5).
- Regulatory and legal filings: SEBI orders, exchange clarifications, auditor resignations, governance flags.
- Significant insider transactions: promoter open-market buys and sells above a threshold percentage.

**Catalyst and Momentum Feed (secondary)**
- Major order wins and joint ventures, filtered by contract value relative to market cap. Also flag back-to-back wins within a month or quarter.
- Brokerage and credit-rating revisions, with target-price changes.
- Corporate action ex-dates: buybacks, dividends, rights issues.

Excluded: standard board-meeting notices, routine compliance notices.

## 4. Source registry

### 4.1 Exchange filings (NSE and BSE) — Home feed, in scope

NSE RSS (`nsearchives.nseindia.com`):
- `Financial_Results.xml`: results (High-Priority)
- `Integrated_Filing_Financials.xml`: results (High-Priority)
- `Sast_Regulation29.xml`, `Sast_Regulation31.xml`: promoter and insider disclosures (High-Priority)
- `Corporate_action.xml`: ex-dates, buybacks, dividends (Catalyst)
- `Corporate_Governance.xml`: governance flags (High-Priority)
- `Related_Party_Trans.xml`: related-party transactions (High-Priority, to confirm)
- `Online_announcements.xml`: general announcements. Use for order-win keyword matching (Catalyst)
- `Shareholding_Pattern.xml`: shareholding changes (to confirm tier)
- `Annual_Reports.xml`: not in the feed tiers yet (parked)

BSE XML (`bseindia.com`):
- `data/xml/announcements.aspx`: general announcements (Catalyst, for order-win matching)
- `data/XML/CorpActionFeed.aspx`: corporate actions (Catalyst)
- `Data/XML/FinancialResultsFeed.aspx`: results (High-Priority)
- `Data/XML/ShareholdingPattern_Feed.aspx`: shareholding changes (to confirm tier)
- `data/xml/notices.xml`: notices. Board-meeting notices are excluded; check for other content
- `Data/XML/AnnualReportFeed.aspx`: parked

Open: NSE and BSE feed terms of use, rate limits, and whether scraping these endpoints is allowed for an internal dashboard. Not yet checked.

### 4.2 News RSS — beat/miss and broker ratings

Investing.com (`in.investing.com/rss/`):
- `news_95`, `news_14`, `news_11`, `news_25`, `news_1061`, `news_1063`, `news_1062`

CNBC TV18 (`cnbctv18.com/commonfeeds/v1/cne/rss/`):
- `economy.xml`, `politics.xml`, `market.xml`, `world.xml`

Use: beat/miss tag on results; broker upgrades and downgrades. Licence to use these feeds in an internal dashboard: **not confirmed**.

### 4.3 Macro: rate decisions, stance and inflation — in scope, separate panel

Scope note: the user moved these into scope on 2026-11-09 for rate decisions, stance and inflation. Placement (Home or a separate macro panel) is not decided. Recommend a separate macro panel, so stock events stay separate from macro data.

RBI (India):
- `rbi.org.in/pressreleases_rss.xml`: **Priority 1.** MPC resolutions, repo rate changes, stance, inflation projections, MPC voting records. Keyword filter: "Monetary Policy", "Repo Rate", "Inflation", "MPC", "Stance"
- `rbi.org.in/Publication_rss.xml`: **Priority 2.** Monthly Bulletin, Monetary Policy Report, state-level inflation assessments, inflation expectations surveys. Poll weekly.
- `rbi.org.in/speeches_rss.xml`: **Priority 3.** Governor and Deputy Governor speeches. Contextual.
- `rbi.org.in/notifications_rss.xml`: **Ignore for rates.** Banking and compliance circulars.

Federal Reserve (US):
- `federalreserve.gov/feeds/press_monetary.xml`: FOMC statements and monetary policy press releases. Source of US stance.

FRED API (US inflation data):
- Key: `FREDAPI_KEY`, added to `.env` per the user's note. Not verified in this session.
- Candidate series: `CPIAUCSL` (US CPI all items), `CPILFESL` (US core CPI). Confirm series IDs before use.

India inflation data: **no source configured yet.** Candidate: MoSPI CPI (official, base 2024=100 from March 2026 data). Cadence: **monthly, not real time.** Release dates come from the MoSPI Advance Release Calendar, not a fixed day of the month. The usual pattern is the 12th, or the next working day, but dates can move (August 2026 data was set for 14 Sept). Next release: 12 Nov 2026, covering October 2026. Dates after that need to be read from the calendar PDF. Sources: [MoSPI September 2026 CPI press release](https://www.mospi.gov.in/uploads/latestreleasesfiles/1791801549227-Press%20Release%20for%20the%20month%20of%20September,%202026.pdf), [MoSPI advance release calendar 2026-27](https://www.mospi.gov.in/uploads/documents/releaseCalender/1791356248513-ARC_2026_27_Sept_2026.pdf). No official high-frequency India inflation series exists. The RBI projection and survey feeds in 3.3 cover India's forward view only.

### 4.4 Stance definitions (reference)

- **Hawkish:** prioritises inflation control. Signals readiness to raise rates or keep them high. Used when inflation runs persistently above target.
- **Dovish:** prioritises growth. Signals readiness to cut rates or add liquidity. Used in slowdowns or when inflation is well below the ceiling.
- **Neutral:** no bias. Future moves depend on incoming data.
- **Action vs stance:** the action is the rate change (for example, a 25 bp cut). The stance is the signal that comes with it. A cut can come with a hawkish stance, and a hold can come with a dovish one. The panel should show both fields separately.

## 5. Open risks

1. **Beat/miss from news.** News articles describe a result as beat or miss in journalist wording. No consensus number is attached. Options: (a) accept the media wording and label the tag "per news"; (b) drop the beat/miss tag until a consensus source is found. Decision pending.
2. **Feed rights.** News feed licences and NSE/BSE feed terms are unconfirmed. Check before building a collector.
3. **Freshness.** Alerts should arrive within minutes. Polling interval for each feed still to set.
4. **Market cap field.** Confirm which table and column holds market cap, and how often it refreshes. Needed for the order-win relative-size rule.
5. **Order-win keywords.** Draft list from the user's pasted notes (below). Needs testing against real filings to check false positives such as generic "contract" notices.

## 6. Draft order-win keyword filter

Tier 1 (direct award or order; highest precision):
- "Letter of Award", "LoA", "Award of order", "Receipt of order", "Work order", "Purchase order", "Bagged order", "Bags contract", "Order win"

Tier 2 (tender and stage gates):
- "LOI", "L1 bidder", "Lowest bidder", "Concession agreement", "Power Purchase Agreement", "PPA"
- "Contract" only with "awarded", "secured" or "signed"

Tier 3 (sector terms, optional):
- Infra and power: "EPC contract", "Commercial operations"
- Defence: "Ministry of Defence", "MoD", "Procurement order", "Supply contract"
- IT: "Multi-year deal", "Digital transformation contract", "Managed services agreement"

Search string (draft): ("Letter of Award" OR "LoA" OR "LOI" OR "Work Order" OR "Bagged") AND ("Crore" OR "Lakh" OR "Contract" OR "Order")

## 7. Still to decide (brainstorm questions)

- Q3: Freshness. Can the feed lag by one collector cycle, or must it be live?
- Q4: What makes a stock "shortlisted"? For example, a new event in the last N days, or only events matching the scan criteria.
- Q5: Event record fields. Suggested minimum: company, event type, time, headline, source link, tier, source name.
- News feed licence and exchange feed terms (section 5).
- Macro panel: Home or a separate panel (section 4.3). India CPI source (section 4.3). Confirm US CPI series IDs (section 4.3).
- Whether the Fed and RBI feeds need a rate-decision alert or only a feed.
- Beat/miss approach (section 5, item 1).
- Retention period for stored news titles, links and classifications in the event tracker, and licence review for storing them long term.

## 8. Economic calendar (market dashboard)

Purpose: show upcoming and recent releases that move rates and markets, so the dashboard shows what is due next and what just came out.

### 8.1 Calendar entries (as found on 2026-11-09, to verify against official pages)

| Event | Country | Next date | Source of truth | Status |
|---|---|---|---|---|
| CPI, October 2026 data | India | 12 Nov 2026 | [MoSPI advance release calendar](https://www.mospi.gov.in/uploads/documents/releaseCalender/1791356248513-ARC_2026_27_Sept_2026.pdf) | Confirmed in the Sept 2026 press release |
| CPI, October 2026 data | US | 10 Nov 2026, 8:30 a.m. ET | [BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm) | Confirmed on the BLS page (checked 2026-11-09) |
| CPI, November 2026 data | US | 10 Dec 2026, 8:30 a.m. ET | [BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm) | Confirmed on the BLS page (checked 2026-11-09) |
| MPC decision | India (RBI) | 2–4 Dec 2026 (decision on 4 Dec) | [RBI MPC schedule FY27](https://www.rbi.org.in/SCRIPTs/Annualpolicy.aspx) | Listed in the RBI schedule per a search summary (press release dated 23 Mar 2026). RBI page not opened directly. Verify |
| FOMC meeting | US (Fed) | 8–9 Dec 2026 (SEP meeting) | [Fed FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | Confirmed on the Fed page. The Dec statement date is not listed yet |

### 8.2 Conflicts to resolve before the dashboard goes live

1. **RBI repo rate after the 5–7 Oct 2026 meeting (open).** One 5paisa article says the repo rate rose 25 bps to 5.50%. Other coverage still shows 5.25%. Neither was checked against an RBI resolution. Check the October 2026 RBI resolution before showing any rate on the dashboard.
2. **FOMC December statement date (open).** The Fed page lists the 8–9 Dec meeting but not its statement date. Treat 9 Dec as the expected decision day until the Fed publishes it.
3. **MoSPI release time (open).** Not found. Do not show a time until it is confirmed.
4. **RBI dates (partly open).** The FY27 dates came from search summaries. Open the RBI page once before the dashboard uses them.

Resolved on 2026-11-09: the March 2026 FOMC date is 17–18 Mar (the earlier 19 Mar was wrong). US CPI dates 10 Nov and 10 Dec are confirmed on BLS.

### 8.3 Design considerations

- **Source hierarchy.** Each row stores its official source URL and the date it was checked. Third-party dates are marked "unverified" until checked against the official page.
- **Time zones.** Store every event in UTC with its local zone. Display in IST by default. US releases are 8:30 a.m. ET, which is 6:00 p.m. IST in winter and 7:00 p.m. IST in summer, so the timezone switch matters.
- **Calendar refresh.** The official calendars are published in advance, so the dashboard should not scrape them daily. Refresh once when a new calendar is published, then re-check after each release in case a date moved.
- **Holiday shifts.** Dates move when they fall on a holiday or a weekend (CPI: next working day). Keep the calendar as dated rows, not a formula.
- **Lead time and alerts.** Show the next event with a countdown. Decide the alert lead time (for example, 1 day and 1 hour before). Alerts for rate decisions and CPI are macro alerts, separate from the stock event alerts.
- **Actual versus expected.** Once a release is out, store the actual figure beside the scheduled date. Do not add a consensus forecast until a source is chosen (see section 5).
- **Scope.** Start with the four rows in 7.1 (India CPI, US CPI, RBI MPC, FOMC). Add others later (for example, India IIP, GDP, US payrolls) only if asked.
- **Storage.** A table of calendar rows (event, country, scheduled UTC time, source URL, checked date, status). It is read through the Fastify API. The browser must not read the database directly (spec section 6).

## 9. Links

- Spec: `docs/designs/ui-redesign-spec.md` (sections 5.1, 5.4, 6)
- Brief: `docs/designs/ui-redesign-brief.md` (Events and alerts)
