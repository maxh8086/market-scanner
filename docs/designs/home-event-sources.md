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
1. Fetch RSS items from the sources in section 4.2 on a schedule. Fetching does not depend on the LLM. Each new item is written to an intake queue with: source, URL, published time, normalised title, and a content hash. The queue stores the title, the link, and the page's headline and summary (the page's og:title or title, and its og:description or meta description). It does not store article body text.
2. Deduplicate by URL and by content hash, at queue insert.
3. Keyword prefilter (the draft filter in section 6). Items with no keyword and no watchlist symbol are marked "prefiltered_out" and do not call the LLM.
4. When the LLM is available, a worker drains the queue in batches, oldest first. Each remaining item is classified once, using the local LLM at `LLM_URL`. No model name is hardcoded in the app. The endpoint may move to OpenRouter later (see Failure behaviour, third-party risk). The model returns compact JSON only: `{"relevant": true|false, "category": "<tier or macro>", "symbols": [], "sectors": [], "stance": null|"hawkish"|"dovish"|"neutral", "reason": "<max 25 words>"}`.
5. Items with `relevant` set to true are written to the event tracker (section 2.1 below). Items marked not relevant are marked "rejected" in the queue and kept only as counts.
6. Each run records counts: queued, prefiltered_out, sent_to_llm, relevant, rejected, expired.

**2.1 Event tracker storage**
- Each relevant item becomes one event row with: event_id, source, source_url, published_at, classified_at, category, symbols, sectors, stance, reason, model_id, prompt_version, status.
- Store the model_id and prompt_version on every row, so a later re-run can be compared with the first result.
- Rows are kept for future use (history, review, and later back-testing). The dashboard reads only a recent window (for example the last 7 days). The window is a display setting, not a deletion rule.
- News titles and links are not kept long term (no licence). Only critical events are kept, with their timeline and price-impact tracking. The window and the critical-event rule are in section 7.

**Criteria for "relevant"**
- A tier 1 or tier 2 event from section 1 (results, guidance, order wins, brokerage rating changes, rating-agency actions).
- The item names a symbol in the watchlist or the scanner universe.
- A macro item on RBI or Fed policy stance (section 4.3) or an India or US inflation release.
- Anything else is not relevant. General market commentary, opinion pieces, sponsored content and duplicate wire copies are not relevant.

**Failure behaviour**
- If the LLM is down or times out, queued items wait. Nothing is dropped while they wait. A queued item expires after 48 hours if it has still not been processed. Expired items are counted as "expired" and never shown. The dashboard shows a "news filter unavailable" marker with the time of the last successful run, once the LLM has been down for more than one hour.
- Exchange filings (section 4.1) and the economic calendar (section 8) do not depend on the LLM and keep updating.
- The Haiku fallback in CLAUDE.md applies to development tasks, not to runtime classification.
- **Third-party risk.** If `LLM_URL` moves to OpenRouter, every headline and summary in the queue is sent to a third party. That move needs its own decision and a note in this section before it happens.
- **Empty-day rule.** When no relevant item has been recorded for the day, the Home feed shows the most recent recorded events by date, with the line "No new news since [time of the last successful classification run]".

**Verification before launch**
- Build a labelled set of at least 100 items (relevant or not) from real feed output, and measure precision and recall of the LLM filter against it.
- Use the acceptance thresholds in section 7 (precision 0.85, recall 0.90).
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

Terms check (read 2026-11-09):
- NSE (website Terms of Use, https://www.nseindia.com/static/nse-terms-of-use): content must not be copied, stored (in hardcopy or an electronic retrieval system), aggregated, adapted or distributed without NSE's prior written permission. The exception covers content that is available for download, and the terms do not say whether RSS items fall under it, so it cannot be relied on for RSS. Systematic or automated data collection, including scraping, data mining and data harvesting, is prohibited. The NSE Data Sharing and Usage Policy (market data) was not read.
- BSE: the BSE terms page returned HTTP 403 and was not read. The announcements disclaimer says information is provided "AS IS" without warranty, and BSE does not pre-verify company announcements. No redistribution or scraping terms were found in search results.
- Impact: a collector that stores NSE items conflicts with the NSE clauses above, even for personal use. Section 7 records the user's decision (option a, 2026-11-09): collect for personal use only, accepting the terms risk.
- Rate limits: not checked.
- Status: not decided. See section 7.

### 4.2 News RSS — beat/miss and broker ratings

Investing.com (`in.investing.com/rss/`):
- `news_95`, `news_14`, `news_11`, `news_25`, `news_1061`, `news_1063`, `news_1062`

CNBC TV18 (`cnbctv18.com/commonfeeds/v1/cne/rss/`):
- `economy.xml`, `politics.xml`, `market.xml`, `world.xml`

Use: beat/miss tag on results; broker upgrades and downgrades. Licence to use these feeds in an internal dashboard: **not confirmed**.
X / Twitter: out of scope. No X API, no manual paste into the intake queue, and no scraping or automating a logged-in X session (see section 7).
Telegram links: the user can send a news link to a Telegram bot. The bot queues it with the same fields as RSS items (title, link, page headline and summary). X links are ignored. Page fetch for the headline and summary is subject to the licence check in section 5.
Terms check (read 2026-11-09):
- Investing.com (terms page, risk disclosure section): prohibits using, storing, reproducing, displaying, modifying, transmitting or distributing the site's data without written permission from the site owner (Fusion Media) or the data provider. No RSS, syndication, personal-use or non-commercial clause found in the text read. The RSS index page returned HTTP 403, so the feed's own terms are unread.
- CNBC TV18 (terms of use, sections 3 and 4): prohibits copying, storing, reproducing or republishing site content without written authorisation. Prohibits scraping, crawling or extracting data without express written permission. Prohibits using site content in a searchable or machine-readable form, including as a database, without written authorisation. Prohibits repeating stock-call information outside the site. No personal-use carve-out found.
- User's reading (2026-11-09): the reproduction limit applies only when news is published under the user's name or on the user's website. The dashboard is an internal page for personal reference. It shows headline and summary with the source link, and is not published. The user's view is that the policies do not apply to it. This reading covers reproduction and publishing. It does not address the storing, using, scraping and database clauses above, which the dashboard's collector would trigger.
- Status: decided 2026-11-09 (section 7). The user chose to fetch and store headlines and summaries from these sites for personal use, and accepts the terms risk described above.
First Telegram batch (9 Nov 2026) publishers: Moneycontrol, Investing.com, NDTV Profit, Economic Times, Business Standard, Firstpost, pv-magazine India, The Verge, Inshorts, and Google share links (the publisher is not shown in the link). The batch also had two LinkedIn posts. LinkedIn is not a news source in this design, so LinkedIn links are not queued (its terms have not been checked).

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

1. **Beat/miss from news.** News articles describe a result as beat or miss in journalist wording. No consensus number is attached. Decision (2026-11-09): option (a). Keep the tag and label it "per news". Show the tag only when the article itself uses "beat", "miss" or "in line". Never infer it from numbers. Show the source headline and link next to the tag. Do not use the tag as a filter, alert or ranking input. Revisit (b) if the tag is ever used to drive a decision.
2. **Feed rights (resolved 2026-11-09).** The user verified that the news feeds and NSE/BSE feed terms are open for personal use. This is the user's reading, recorded here. It covers personal use only. The storing and scraping clauses in section 4.2 still apply, as recorded there.
3. **Freshness (resolved 2026-11-09).** Alerts should arrive within minutes. Poll every 5 minutes from 08:00 to 15:30 IST on trading days. Poll every hour at all other times, including when the market is closed. Times are IST, the market's time zone. Trading days follow the NSE/BSE calendar.
4. **Market cap field (refresh rule decided 2026-11-09).** Market cap refreshes on the next fundamental data refresh. If the price source is Upstox, it also refreshes from the realtime and end-of-day Upstox feed. The repo does not store a market cap column under that name. It is computed in `scanner/fund_derive.py` (`market_cap_cr` = price x shares), and the shares come from equity capital divided by face value. Its `basis` label says "price x (TTM PAT / TTM EPS)", which does not match the code, so the label needs correcting. The table and column that store the value are still open. Needed for the order-win relative-size rule.
5. **Order-win keywords.** Draft list from the user's pasted notes (below). Needs testing against real filings to check false positives such as generic "contract" notices.
6. Page fetch. Fetching publisher pages for a headline and summary (RSS links and Telegram links) falls under the same licence check as the news feeds in section 4.2. Terms read 2026-11-09 (section 4.2). The user's personal-use reading does not cover the storing and scraping clauses. Decided 2026-11-09 (section 7): fetch and store, for personal use, accepting the terms risk.

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

Test on the first Telegram batch (9 Nov 2026, 21 headlines chosen by the user): 0 of 21 match the draft filter above. The filter covers order wins only. The batch is macro, market and corporate news, so the filter would mark all 21 as prefiltered_out. Macro keyword set (added 2026-11-09). The prefilter matches any of these, case-insensitive, as whole words or phrases:

- Central banks: RBI, Reserve Bank, Monetary Policy, Repo Rate, MPC, Fed, Federal Reserve, FOMC, rate cut, rate hike, rate decision
- Inflation releases: inflation, CPI, PCE
- Geopolitical and trade (wider than the section 2 criteria; kept so the LLM sees them, to be confirmed): sanctions, tariff, tariffs

Test result on the macro set: 2 of 21 entries match. Matched: 11 (Gold, quoted headline, Fed and inflation) and 21 (Trump, URL slug, sanctions and tariffs). Not matched: 19. Two LinkedIn posts and one Inshorts promo have no text and cannot match. 16 of 21 entries used the URL slug instead of a headline; for four of those, the slug is a share-link ID, so they cannot match either. All 21 were chosen by the user, so this batch cannot measure false positives.

## 7. Decisions from brainstorm (answered 2026-11-09)

**Q3. Freshness.** Use frequent polling with a visible timestamp (option C). Each item shows when it was fetched. The RSS source is built and tested, but it stays OFF by default because the laptop is not always on. Exchange filings and the economic calendar are the default sources.

**RSS age limit (decided 2026-11-09).** RSS items older than 1 week are dropped and do not show on the Home panel. The done test for the RSS module is that RSS items appear on the Home panel.

**Q4. What makes a stock "shortlisted".** Use the existing ATH scanner rule, not a new one. A stock is on the Home shortlist only if all three hold:
1. It is an ATH-scan match: a new ATH today, or its last price is within 26% of its all-time high (`scanner/ath.py`, `classify_bucket`, default `max_dist=26.0`).
2. Its trend is UPTREND: last price is above both the 50-day EMA and the 200-day SMA (`scanner/indicators.py`, `classify_trend`).
3. It has at least one corporate-event factor: bonus issue, demerger, order-book signal or expansion signal (`scanner/factors.py`, `factors_matched`).
The shortlist is the intersection of these three. On the 2026-09-28 full run this gave 39 names (298 matches, of which 39 are UPTREND with at least one factor), per `handoff.md`. The event feed is separate: it lists events, and the shortlist lists stocks that pass the three rules above.

**Q5. Event record fields.** Use the fields you listed: company, event type, time, headline, source link, tier, source name. The classification fields in section 2.1 (category, stance, reason, model ID, prompt version, status) are kept as well.

**Macro panel.** A separate panel for the economic calendar and its outcomes (scheduled date, then actual result once published), not part of the Home event feed.

**Fed and RBI.** A rate decision triggers an alert and also appears in the feed.

**Beat/miss.** Do not compute a beat or miss against a consensus number. Process the news and show it as met or failed, based on the wording, as the source reports it.

**Licence and retention.** There is no licence for news content, so news titles and links are not kept long term. Keep only critical events, track their progress over time on the timeline, and track their price impact over a set period. The exact window is still open (see below).

**Decided on 2026-11-09:**
- **Critical events:** tier 1 and tier 2 events. Both are kept long term and tracked.
- **Impact window:** price impact is tracked for 30 days after each critical event.
- **Event cap per symbol:** show at most 3 events per stock on the Home feed. This is a Home display cap only. It is not a storage limit, and it does not apply to a stock's own timeline.

**Decided on 2026-11-09 (continued):**
- **Cap rationale:** the cap of 3 events per stock applies to the Home feed only. It keeps the Home feed readable, so one stock with many filings in a week does not push other shortlisted stocks off screen. Every event for a stock is still shown on that stock's own timeline, in the event tracker. This matters because a user who opens a single stock can scan its full event history there, and the Home feed is only the entry point.
- **News-filter acceptance targets (set on 2026-11-09):** measured on a labelled set of at least 100 items from real feed output (section 2). Precision of at least 0.85, because the dashboard shows only items marked relevant, so each false positive is visible noise. Recall of at least 0.90. The news feed is now the only route for news items to the dashboard, so a missed relevant item is not seen anywhere else. Exchange filings remain the primary source for filings. Re-measure after any change to the prompt, model, or criteria.
- **Exchange feed licence (decided 2026-11-09):** the user chose option (a): collect NSE and BSE filing items for personal use only, accepting the terms risk in section 4.1. This is the same stance as the news sites. The NSE website terms prohibit storing, copying and automated collection of content without written permission. The earlier note "no licence terms apply" was written before those terms were read and is withdrawn. The collector must not redistribute items, and it must keep only the fields the Home feed needs. Rate limits are still unchecked.
- **India CPI source:** the MoSPI advance release calendar (section 8.1), as recommended in this document.
- **X / Twitter: out of scope.** Decided 2026-11-09: no X API tier, no manual paste of X posts into the intake queue, and no scraping or automating a logged-in X session. No X content enters the feed or the event tracker.
- **Live-feed testing.** Decided 2026-11-09: live-feed tests are opt-in and run outside the offline test command. The offline test command (`.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`) uses recorded samples only and never calls the network. The live-feed tests need an explicit flag or environment variable to run, and they are not part of the default test run.
- **Telegram link intake.** Decided 2026-11-09: the user can send news links to a Telegram bot. Each link is queued with the same fields as RSS items (title, link, page headline and summary, no article body). The bot ignores X links. The Telegram reader is a new service and needs its own plan before it is built. Hosting is open: a laptop-hosted bot can resume from the last update it confirmed (the `offset` in Telegram's getUpdates), not from a timestamp, because getUpdates has no time filter. The length of time Telegram keeps unconfirmed updates is not stated on the Bot API page and needs checking before a laptop-only setup is accepted.

Telegram group flow (decided 2026-11-09). The user posts shortlisted links in a Telegram group. The bot is an admin of that group and is given the "delete messages" right only. It saves each link with its message date as it arrives. It deletes the message from the group only after its row is saved in the database, not after classification. Deletion does not wait for the LLM, because the row holds the raw URL until classification. Telegram only allows deleting messages sent less than 48 hours ago, so each link must be saved within that window.

Hosting (decided 2026-11-09). The user is the only poster to the group, and the links are news they have already read. The bot runs on the user's laptop for now, with no always-on host. Links posted while the laptop is off are picked up when it next runs, from the last confirmed Telegram update. This depends on Telegram keeping unconfirmed updates long enough, which is still unchecked (see the retention note above). If the laptop is off longer than that window, those links are lost. Revisit an always-on host if that happens or if the posting pattern changes. Whether fetching a publisher page for its headline and summary is allowed is still open (section 5).
- **Collector fetch and storage.** Decided 2026-11-09: the collector fetches each publisher page for its headline and summary, and stores them, for personal use. The user accepts the terms risk recorded in section 4.2 (Investing.com and CNBC TV18 storing and scraping clauses). Article body text is still not stored. This decision does not cover republishing or any use outside the user's personal reference page.

**Still open:**
- None.

## 8. Economic calendar (market dashboard)

Purpose: show upcoming and recent releases that move rates and markets, so the dashboard shows what is due next and what just came out.

### 8.1 Calendar entries (as found on 2026-11-09, to verify against official pages)

| Event | Country | Next date | Source of truth | Status |
|---|---|---|---|---|
| CPI, October 2026 data | India | 12 Nov 2026 | [MoSPI advance release calendar](https://www.mospi.gov.in/uploads/documents/releaseCalender/1791356248513-ARC_2026_27_Sept_2026.pdf) | Confirmed in the Sept 2026 press release |
| CPI, October 2026 data | US | 10 Nov 2026, 8:30 a.m. ET | [BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm) | Confirmed on the BLS page (checked 2026-11-09) |
| CPI, November 2026 data | US | 10 Dec 2026, 8:30 a.m. ET | [BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm) | Confirmed on the BLS page (checked 2026-11-09) |
| MPC decision | India (RBI) | 2–4 Dec 2026 (decision on 4 Dec) | [RBI MPC schedule FY27](https://www.rbi.org.in/SCRIPTs/Annualpolicy.aspx) | Dates come from secondary sources (5paisa, Angel One and others) that cite the RBI calendar of 23 Mar 2026. The RBI FY27 calendar page is not yet opened directly. Verify |
| FOMC meeting | US (Fed) | 8–9 Dec 2026, statement 2:00 p.m. ET on 9 Dec | [Fed December 2026 calendar](https://www.federalreserve.gov/newsevents/2026-december.htm) | Confirmed on the Fed page (checked 2026-11-09). Press conference 2:30 p.m. ET; minutes due 30 Dec |

### 8.2 Conflicts to resolve before the dashboard goes live

1. **RBI repo rate after the 5–7 Oct 2026 meeting (resolved).** The RBI press release "Monetary Policy Statement, 2026-27, Resolution of the Monetary Policy Committee, October 5 to 7, 2026" (dated 7 Oct 2026) says the MPC raised the policy repo rate by 25 bps to 5.50%. SDF is 5.25%, MSF and Bank Rate 5.75%, stance changed to calibrated tightening. The 5.25% figures are stale. Checked 2026-11-09 on rbi.org.in.
2. **FOMC December statement date (resolved).** The Fed's December 2026 page gives the statement at 2:00 p.m. ET on 9 Dec, the press conference at 2:30 p.m. ET, and minutes on 30 Dec. The 16 Dec date seen on one site is wrong. Checked 2026-11-09.
3. **MoSPI release time (partly open).** Secondary sources (Bajaj Broking and others) say CPI moved to a 4:00 p.m. release from the October 2024 data, to match market close. Not confirmed on a MoSPI page. Do not show a time on the dashboard until the MoSPI release calendar or press release confirms it. The 12 Nov date in 8.1 also needs the same check, because one April 2026 release was embargoed to 4:00 p.m. on the 13th.
4. **RBI FY27 calendar (resolved 2026-11-09).** The RBI schedule page (rbi.org.in/SCRIPTs/Annualpolicy.aspx, dated 23 Mar 2026) lists the meeting dates: 6–8 Apr, 3–5 Jun, 3–5 Aug, 5–7 Oct, 2–4 Dec 2026, and 3–5 Feb 2027. The October decision (7 Oct 2026) is on the page. The December decision has no date on the page yet, which is expected because the meeting has not happened. The dashboard can show 4 Dec as the decision date, marked as scheduled.

Resolved on 2026-11-09: the March 2026 FOMC date is 17–18 Mar (the earlier 19 Mar was wrong). US CPI dates 10 Nov and 10 Dec are confirmed on BLS.

### 8.3 Design considerations

- **Source hierarchy.** Each row stores its official source URL and the date it was checked. Third-party dates are marked "unverified" until checked against the official page.
- **Time zones.** Store every event in UTC with its local zone. Display in IST by default. US releases are 8:30 a.m. ET, which is 6:00 p.m. IST in winter and 7:00 p.m. IST in summer, so the timezone switch matters.
- **Calendar refresh.** The official calendars are published in advance, so the dashboard should not scrape them daily. Refresh once when a new calendar is published, then re-check after each release in case a date moved.
- **Holiday shifts.** Dates move when they fall on a holiday or a weekend (CPI: next working day). Keep the calendar as dated rows, not a formula.
- **Lead time and alerts.** Show the next event with a countdown. Decide the alert lead time (for example, 1 day and 1 hour before). Alerts for rate decisions and CPI are macro alerts, separate from the stock event alerts.
- **Actual versus expected.** Once a release is out, store the actual figure beside the scheduled date. Do not add a consensus forecast until a source is chosen (see section 5).
- **Data source for the calendar (decided 2026-11-09).**
  - **US release dates:** the BLS release calendar is the source of dates and times for CPI, jobs and PPI (decided 2026-11-09).
  - **US release values and Fed series:** the FRED API (`fred/series/observations` for values) covers US economic series. FOMC meeting and statement dates stay on the Fed's own calendar page, because FRED does not carry them.
  - **FRED terms:** the Terms of Use allow personal use. Series marked "Copyright" in their notes are owned by third parties, and using them outside personal use needs the owner's permission. The key is set as the environment variable `FREDAPI_KEY` and is not stored in the repo.
  - **RBI data:** RBI press releases on rbi.org.in are the source for MPC dates, decisions and the repo rate.
  - **India data releases (CPI, WPI):** the MoSPI calendar, as listed in 8.1.
  - Investing.com data is not reused. Financial Modeling Prep and Trading Economics are not used for now, so the planned FMP key test is dropped.
- **Scope.** Start with the four rows in 8.1 (India CPI, US CPI, RBI MPC, FOMC). Add others later (for example, India IIP, GDP, US payrolls) only if asked.
- **Storage.** A table of calendar rows (event, country, scheduled UTC time, source URL, checked date, status). It is read through the Fastify API. The browser must not read the database directly (spec section 6).

## 9. Links

- Spec: `docs/designs/ui-redesign-spec.md` (sections 5.1, 5.4, 6)
- Brief: `docs/designs/ui-redesign-brief.md` (Events and alerts)
