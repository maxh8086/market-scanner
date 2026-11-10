# Home events: macro panel and economic calendar

Status: draft, not approved. Owned rules and decisions follow the overview (sections 5.5 and 10). Storage decided 2026-11-10 (overview section 6.3). Build specs are not written yet.
Owner: Vaibhav Pavtekar
Screen: Home, shortlist and event feed (`docs/designs/ui-redesign-spec.md` section 5.1, section 6)
Overview: [home-event-sources.md](home-event-sources.md). The licence and the Home feed rules are owned by the overview (section 2). Retention ownership is in the filings doc (overview section 2). The retention and purge rule is in overview section 7.4.
Related specs: [home-events-filings-spec.md](home-events-filings-spec.md) (rev 4) and [collector-split-spec.md](collector-split-spec.md). See Dependencies.
Open decisions and findings for the user: [home-events-macro-calendar-decisions.md](../progress/home-events-macro-calendar-decisions.md).

## Scope

- Macro panel: rate decisions, stance and inflation, in a panel separate from the stock event feed (overview section 10.1). Rate decisions are rows in `macro_events` (see Storage). Whether they also appear in the Home feed is open (see Open).
- Economic calendar for the market dashboard (overview section 10.2).
- Build second, after filings (overview section 7.7).
- Cut: RBI priorities 2 and 3, the speeches feed and stance extraction (overview sections 5.5, 7.7 C4).

## Glossary

- **ET**: Eastern Time (US). **IST**: India Standard Time, UTC+5:30 all year.
- **BLS**: US Bureau of Labor Statistics. Publishes the CPI release dates.
- **FRED**: Federal Reserve Bank of St. Louis economic data service. Publishes the series values.
- **FOMC**: Federal Open Market Committee. The Fed's policy body; its meetings produce a statement, a press conference and minutes.
- **Fed**: the US Federal Reserve.
- **RBI**: Reserve Bank of India. **MPC**: the RBI's Monetary Policy Committee.
- **MoSPI**: Ministry of Statistics and Programme Implementation (India). Publishes India CPI.
- **SDF**, **MSF**, **Bank Rate**: RBI policy rates (standing deposit facility, marginal standing facility, and the Bank Rate). Used in the conflicts section.
- **bp**: basis point (0.01 percentage point).
- **Advance release calendar**: MoSPI's published schedule of future release dates.
- **Events database**: the separate Postgres database for event tables (overview section 6.3; filings spec D8).
- **The job**: the India CPI ingestion job (overview section 8.2 item 17; build specs item 3).

## Storage (decided 2026-11-10)

- Only the Fastify API connects to the events database. The collector posts through Fastify and never connects to the events database (filings spec 4.6, D9; overview section 6.3). Nothing in this doc writes to the main database.
- Raw items: `event_intake` (migration 002 in the events database; owned by `home-events-news-telegram.md`). Raw RBI, Fed and MoSPI items are staged there. Hand-seeded calendar rows are not raw items and do not pass through intake.
- Processed rows: `macro_events` (migration 004 in the events database; owned here). It holds rate decisions, CPI releases and calendar entries. It requires no ISIN and no symbol.
- Rate decisions are rows in `macro_events`, not in `home_events`. `home_events` requires ISIN and symbol, accepts NSE only and has six equity event types (filings spec 4.1), so it cannot hold them.
- If the calendar is split from the releases, the calendar takes migration 005 (reserved). Migration numbers come from the allocation table in overview section 6.3. This doc chooses none.
- Read path: the Home feed merges macro rows through Fastify (overview section 6.3). The browser reads them only through the API.
- Proposed routes, named in the style of filings spec 4.6 (names proposed, not built):
  - `POST /internal/events/macro`: body `{"rows": [...]}` for `macro_events`, at most 500 rows, bearer token role `macro_ingest` (proposed). Returns `{inserted, duplicates, invalid}`, the same contract as filings spec 4.6. Caller: the macro collector source(s).
  - Raw items: no raw-intake route for macro is defined yet. The news doc routes cover RSS, Telegram and Upstox only (decision A1, 2026-11-10). Macro raw-item route: open.
  - `GET /api/macro` and `GET /api/calendar` (proposed reader names, for the UI through Fastify). The owner of their contracts is open (see Open).
- Token role `macro_ingest` (proposed), following `secrets-and-roles.md` and the `home_events_ingest` pattern in filings spec 4.6. Token values never go in the repo, this doc or a log.
- Columns: to be specified in the build spec.

## Dependencies

- Collector split spec (`collector-split-spec.md`). The macro source(s) run in their own container only after:
  - S1a: run-once path that writes run rows, including `skipped`;
  - S2: exchange cooldown table, migration 047 in the main database. Macro hosts need rows only if Open item M3 says so;
  - S3: compose template and the `server` service;
  - S4: watchdog;
  - S5a: `GET /internal/due`.
  Build order is in split spec section 6. Main-database migration numbers are allocated there.
- Filings spec (`home-events-filings-spec.md`). This doc relies on the events database migration 001 pattern and the events pool (T2a, T2b), and on the Fastify events route and auth pattern (T5a to T5c). It reuses `classify_response` and `redact_error` (T3a, T3c) and does not copy them. Filings code lives in one module (Z6, decided). Proposed: macro code in a separate module.
- Migration numbers: overview section 6.3 allocation table (002 news doc, 004 here, 005 reserved). This doc takes no number of its own.
- Overview section 6.3: the storage decision.

## Owned rules

### Macro panel

- RBI: priority 1 press releases only (`rbi.org.in/pressreleases_rss.xml`) (overview section 5.5). Keyword filter: "Monetary Policy", "Repo Rate", "Inflation", "MPC", "Stance".
- Federal Reserve: `federalreserve.gov/feeds/press_monetary.xml` (FOMC statements and monetary policy releases) (overview section 5.5).
- Action and stance are separate fields. The action is the rate change (for example, a 25 bp cut). The stance is the signal that comes with it. A cut can come with a hawkish stance, and a hold with a dovish one (overview section 10.1).
- Stance definitions, pending: hawkish (prioritises inflation control, signals readiness to raise or keep rates high); dovish (prioritises growth, signals readiness to cut or add liquidity); neutral (no bias). Open (overview section 8.2 item 1).

### FRED

- Series: `CPIAUCSL` (headline CPI) and `FEDFUNDS` only (overview sections 5.5, 10.1).
- `CPIMEDSL` is removed. It is the medical-care component of CPI, not headline inflation (user, 2026-11-10) (overview section 10.1).
- Key: env var `FREDAPI_KEY`, in `.env`. Not verified in this session (overview section 5.5).
- Pass condition for checking the series IDs: open (overview section 8.2 item 16).
- Terms: personal use is allowed. Series marked "Copyright" are owned by third parties and need the owner's permission outside personal use (overview section 10.3).

### India CPI

- Source: MoSPI India CPI calendar and press releases (overview section 5.5, 10.3).
- Monthly, not real time. No official high-frequency India inflation series exists (overview section 10.1).
- Release time: 16:00 IST. Confirmed by the user 2026-11-10. The MoSPI page does not yet confirm it. The "4:00 p.m." in secondary sources is the same time (overview sections 8.2 item 17 and 10.4).
- The value is ingested by a job, not entered by hand. The job is decided. Its spec is not written: source page, parsing, DDL, schedule and failure handling are open (overview section 8.2 item 17).
- If a release is missed, the next available slot after the data release is used (overview section 10.1). "Slot" is not defined here (see Open).
- Dates after 12 Nov 2026 come from the MoSPI advance release calendar (overview section 8.2 item 17).

### Calendar rows

Rows, hand-seeded as dates only (overview sections 7.7 C4 and 10.1). Rows are as of 2026-11-10. The US row for October data is today.

| Event | Country | Next date | Source | Status |
|---|---|---|---|---|
| CPI, October 2026 data | India | 12 Nov 2026, 16:00 IST | MoSPI advance release calendar 2026-27 | Date in the September 2026 press release. Time confirmed by the user; the MoSPI page does not yet confirm it |
| CPI, October 2026 data | US | 10 Nov 2026, 8:30 a.m. ET (today; 19:00 IST) | BLS CPI schedule | Confirmed on the BLS page (2026-11-09). Release is today |
| CPI, November 2026 data | US | 10 Dec 2026; time to be confirmed from the source page | BLS CPI schedule | Next release per the BLS page checked 2026-11-09. Time not stated in this doc |
| MPC decision | India (RBI) | 4 Dec 2026 (meeting 2 to 4 Dec), to be confirmed from the source page | RBI schedule page, `rbi.org.in/SCRIPTs/Annualpolicy.aspx` (dated 23 Mar 2026) | Unverified. The same status text says the December decision has no date on the page yet, which conflicts with the 4 Dec date. Decision time not given |
| FOMC meeting | US (Fed) | Statement 9 Dec 2026, 2:00 p.m. ET (meeting 8 to 9 Dec); 00:30 IST on 10 Dec | Fed December 2026 calendar | Press conference 2:30 p.m. ET. Minutes due 30 Dec |

### Calendar conventions

- Source hierarchy: each row stores its official source URL and the date checked. Third-party dates are marked "unverified" until checked against the official page (overview section 10.3).
- Storage: the calendar rows are `macro_events` rows in the events database, read through the Fastify API (see Storage).
- Time zones: store the UTC instant and the IANA zone name (`America/New_York` for ET, `Asia/Kolkata` for IST). IST is UTC+5:30 all year. US times convert with the zone's offset on that date:
  - EST (UTC-5, winter): 8:30 a.m. ET is 13:30 UTC, which is 19:00 IST.
  - EDT (UTC-4, summer): 8:30 a.m. ET is 12:30 UTC, which is 18:00 IST.
  - FOMC statement at 2:00 p.m. EST is 19:00 UTC, which is 00:30 IST on the next day. At 2:00 p.m. EDT it is 18:00 UTC, which is 23:30 IST the same day.
  - Which date to display (ET or IST) is open (see Open). Code converts with `zoneinfo`, never with a hand-typed offset (overview section 10.3).
- Refresh: once when a new calendar is published, and re-check after each release. Keep dated rows, not a formula. CPI moves to the next working day on a weekend or holiday (overview section 10.3).
- Data sources: BLS (US release dates); FRED (US series values); Fed calendar page (FOMC dates); RBI press releases (decisions and repo rate) and the RBI schedule page (MPC dates); MoSPI calendar (India CPI). WPI is out of scope. Calendar dates are hand-seeded and checked by hand against these pages. Investing.com, Financial Modeling Prep and Trading Economics are not used (overview section 10.3).
- Scope: the four events above. Others (for example, India IIP, GDP, US payrolls) only if asked (overview section 10.3).

### Trading-day calendar

- Working assumption: the NSE/BSE calendar. Proposed, not decided (overview section 8.2 item 7).

### Conflicts resolved

- RBI repo rate: raised by 25 bp to 5.50% after the 5 to 7 Oct 2026 meeting. SDF 5.25%, MSF and Bank Rate 5.75%. Stance changed to calibrated tightening (RBI press release 7 Oct 2026, checked 2026-11-09). Earlier 5.25% repo figures are stale (overview section 10.4).
- FOMC December statement: 9 Dec 2026, not 16 Dec (overview section 10.4).

### Cadence and lead times

- RBI and Fed poll cadence: open (overview section 8.2 item 16).
- Alert lead times for rate decisions and CPI: open (overview section 8.2 item 16).

### Rate limits and gaps

- RBI, Federal Reserve, FRED, BLS and MoSPI: gap and cap not set. Cooldown rule not set (overview section 7.3 table, section 8.2 item 9).

## Carried from the overview (not owned here)

- Licence position: overview section 4.
- Build order: overview section 7.7 (approved 2026-11-10, C6).
- Freshness and poll schedule: overview section 7.3.
- Retention rules and purge: overview section 7.4. The ownership of the retention row is the filings doc (overview section 2).

## Build specs (stub, not written)

Missing before any build. Items that need a decision point to the Open list. Nothing below is a decision.

1. DDL for `macro_events` (migration 004, events database) and for a calendar table only if it is split (migration 005). Columns to be specified in the build spec, including the local-zone column (see Calendar conventions). Unique key and nullable time for date-only rows: to be specified.
2. Config keys with defaults and units: poll cadence for RBI and Fed, alert lead times, and the India CPI job schedule. None set (see Open).
3. Ingestion job spec for India CPI: source page, parsing, DDL, schedule and failure handling. The job is decided; its scope and slot rule are open (see Open).
4. Env var names: `FREDAPI_KEY` is named in the overview. Others not chosen. Where the key is stored is open (see Open).
5. Owner module paths for the macro fetchers and the calendar reader: not chosen (see Dependencies).
6. Holiday calendar source for trading days: see Open (overview section 8.2 item 7).
7. Sample capture, before DDL: fetch each source URL once, save under the sample directory, and record tag and date formats and feed depth. Not written. Fixture policy (proposed): real samples are not committed; synthetic fixtures are committed.
8. Offline tests, run by `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`: IST and ET conversion through `zoneinfo`; YoY computation; keyword filter, with a negative fixture (RBI releases that contain "Inflation" or "Stance" but are unrelated); calendar seed-file validity, including that no seeded row is in the past at build time; `plan()` shape.
9. Opt-in network check: each calendar date against its official page. Runs only on request and is outside the offline command. It is not a unit test.
10. Not yet written: the config-key table (style of filings spec section 7); migration rollout and down steps; runner behaviour (API-down skip, cooldown, status mapping, run deadline; split spec sections 4.3 and 4.5); phases and per-task acceptance commands; "Alternatives considered" (events versus main database: decided, events database; polling versus calendar-driven fetch: open).

## Open

- **Open (user decision), B2.** Do rate decisions also appear in the Home feed? If yes: which feed tier, and how do they dedupe against the LLM route (overview section 6.1)? The review lists three options: cut for v1; the Home events API merges macro rows at read time; or amend the filings schema. Line 10.
- **Open (user decision), B3.** Where do the rate action, the new rate and the stance come from: typed by hand, verbatim source text, action only, or a parse of the title? The stance vocabulary (hawkish, dovish, neutral against RBI's own terms) and the stance field definitions are open (overview section 8.2 item 1). Lines 10, 21 to 22, 67.
- **Open (user decision), B4.** Collector layout: one macro source, or one per source (RBI and Fed poll, FRED, India CPI job); cron for each; registration as events sources; registration migration number (split spec). See Dependencies and lines 36 to 39.
- **Open (user decision), B5.** Display date for US times that fall on a different date in IST (the FOMC statement shows 10 Dec in IST). Lines 50 and 56.
- **Open (user decision), M1.** Rollover of calendar rows: who adds the next year's rows, and whether the full year is seeded in one pass from a checked-in file. Whether the FOMC minutes and press conference are rows or sub-events of the statement row. Status values for rows. Lines 43, 47 to 50, 57.
- **Open (user decision), M2.** Poll cadence. Overview section 7.3 gives 5-minute polling from 08:00 to 15:30 IST on trading days, which misses the macro times (Fed statement 00:30 IST, US CPI 18:00 or 19:00 IST, India CPI 16:00 IST). Choose one low-frequency cron, or calendar-driven windows around each row's time. Whether the RSS "default off" and "older than 1 week dropped" rules (overview 7.3) apply to RBI and Fed. Lines 72 and 83.
- **Open (user decision), M3.** Cooldown rows for RBI, Federal Reserve, FRED, BLS and MoSPI (requested from the split spec session), or a statement that no shared cooldown applies. Whether the 15-minute retry rule (split spec 4.2) applies. The cap conflict (overview section 7.3 says 3 h; split spec 4.3a says 2 h) is deferred to the split spec. Lines 75 to 77 and 82.
- **Open (user decision), M4.** Is the India CPI job in v1, or is the value entered by hand with the press-release link? Define "the next available slot" (line 38) in split spec terms or delete it. Define the release-day polling window and the status of a "not yet published" run. Lines 36 to 39.
- **Open (user decision), M5.** FRED: which unit is displayed for CPI (index level, or YoY percent by `units=pc1` or computed); revisions; observation date versus release date; how `FEDFUNDS` (a monthly average that lags the FOMC action) is used beside decision rows; the pass condition for the series IDs (overview item 16). Key: app secret store (`secrets-and-roles.md`) or `.env` (line 28). Lines 24 to 30.
- **Open (user decision), M6.** Trading-day calendar: drop it (weekday cron; holidays cost one empty run), keep the NSE/BSE calendar, or reassign it to a cross-cutting owner. The filings spec names the Upstox market-holidays API (D6b), and overview item 7 names NSE/BSE. Lines 61 to 63 and 95.
- **Open (user decision), M7.** Retention for macro and calendar rows: keep (small) or 3 years like event rows. Name the purge owner (overview section 8.2 item 4 defers the purge to the filings run). Line 84.
- **Open (user decision), M8.** Which screen shows the macro panel and the calendar. Overview section 10.2 calls it the "market dashboard", which is not a screen in `ui-redesign-spec.md` (section 5.1 is the scan table, section 6 the event rule, and section 7 says market mood is not available). Name the screen, the owning UI spec, the endpoints, and the empty and stale states. Lines 5 and 11.
- **Open (user decision), M9.** Alert channel for rate decisions and CPI: dashboard countdown (overview section 10.3 open), push through the existing Telegram path, or cut from v1. Lead times are open (overview section 8.2 item 16). Lines 73 and 101.
- **Open (user decision), M10.** Terms of use for RBI, Federal Reserve, BLS and MoSPI are unverified: not read, and not listed in overview section 4.1 or item 15. Read them and record the result, or record the user's personal-use acceptance. The sites may block scripted clients; that is unverified. Lines 30 and 58.
- **Open (user decision), M13.** Which copy governs the facts in overview section 10: this doc or the overview. The other becomes a pointer. Stance definitions, the trading-day calendar, cadence and rate limits sit under Owned rules but are open; each needs one owner and a line in this Open list. Lines 3, 65 to 68 and 98 to 104.
- **Open (user decision), N5.** Which keyword list the RBI and Fed filter uses (line 19 versus overview section 9.2); whether it matches title or description; whole word or substring; what "priority 1" means now that priorities 2 and 3 are cut.
- **Open (other owner), B1.** Owner of the macro read contracts (`GET /api/macro`, `GET /api/calendar`). Whether the filings route helpers (`validateBatch`, `checkIngestToken`) are generalised or copied for macro. The filings spec (4.6) owns those helpers.
- **Open (unverified), U1.** MoSPI 16:00 IST time (overview section 8.2 item 17). The December MPC date on the RBI schedule page (see the MPC row). The BLS release time for the November-data row. Terms of use for the four hosts (M10).
- **Open (build approval).** Approval of the build spec for this phase. Build order was approved 2026-11-10 (overview section 7.7, C6).
- **Open.** Stance field and definitions (overview section 8.2 item 1).
- **Open.** RBI and Fed poll cadence, alert lead times, and the FRED pass condition (overview section 8.2 item 16).
- **Open.** India CPI job spec and MoSPI confirmation of 16:00 IST (overview section 8.2 item 17).
- **Open.** Trading-day calendar source (overview section 8.2 item 7).
