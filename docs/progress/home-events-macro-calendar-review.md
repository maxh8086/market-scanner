# Goldfish Review Report: home-events-macro-calendar.md

**Target:** `docs/designs/home-events-macro-calendar.md` (all 105 lines)
**Date:** 2026-11-10
**Mode:** REVIEW (default EGM, six lenses, one instance each, fresh parallel subagents)
**Lenses run:** egm-design, egm-codebase-details, egm-zoom-out, egm-comprehension, egm-implementation-readiness, egm-structural. All six reported. The synthesizer (this report) deduplicated and ranked.
**Context read by the lenses:** overview `home-event-sources.md` (amended 2026-11-10), `home-events-filings-spec.md` (rev 4), `collector-split-spec.md` (read-only), plus `ui-redesign-spec.md`, `secrets-and-roles.md`, and repo greps. No `.env` or `data/secrets.env` was read. No files were edited except this report.

Notation: DOC = the reviewed doc. OV = overview. FS = filings spec rev 4. SS = split spec. "Fix" = edit the doc (or the named file). "Decision" = the user must choose first.

## Verdict

**Not ready for a build spec.** The stub is honest about its own status ("build specs are not written yet" is still true) and nearly every overview section cite resolves. But it is a copy of OV sections 5.5 and 10, so it inherits their errors, and it says nothing about storage, write path, collector integration or its dependencies on FS and SS. The panel's core data (action, stance, repo rate) has no source. One conversion rule is factually wrong. Five blockers, about fourteen majors.

## Cite audit (all lenses agree)

- Resolve correctly: OV 4, 5.5, 7.3, 7.4, 7.7 (C4), 8.2 items 1, 7, 9, 16, 17, 10.1 to 10.4.
- Fail on content: DOC line 10 cites OV 7.1 for "rate decisions also appear in the feed". OV 7.1 has no such rule (the claim exists only at OV line 260, which cites 7.1 back).
- Loose: DOC line 3 ("sections 7 and 8") should cite 5.5 and 10. DOC lines 6 and 83 say retention is owned by the overview, but the OV section 2 table gives retention to the filings doc. DOC line 5 and 9 cite `ui-redesign-spec.md` 5.1 and 6, which exist but contain no macro panel or calendar ("market dashboard" is not a screen in that spec).

## Blockers

### B1. Storage location and write path are undecided (Decision, then Fix). Lenses: design, codebase, zoom-out, readiness, structural, comprehension
- DOC 55 says only "a table of calendar rows ... read through the Fastify API". DOC 91 says table names are not chosen. No database, write path, token role or read endpoint is named.
- If events database: FS D8/D9 apply (only Fastify touches it). The collector must POST through new internal endpoints. FS 4.6 defines only `POST /internal/events/batch` for `home_events`, with token role `home_events_ingest`. A new `db/events_migrations/002_...` is needed, ordered against other events-database claimants. The API login is SELECT and INSERT only (FS 4.1), but calendar rows need `status` and `checked date` updates.
- If main database: the collector writes directly (SS 4.5), Fastify needs SELECT grants like migrations 042/043 and a read endpoint. This does not break the Fastify-only rule or the UI-through-API rule.
- Lens split: zoom-out recommends the main database (macro rows are not events: no ISIN, no exchange). Others left it open. This is a user choice.
- Also required: name the readers (for example `GET /api/macro`, `GET /api/calendar`), the owner of those endpoint contracts, and whether `validateBatch`, `post_events` and `checkIngestToken` are generalised or duplicated.

### B2. "Rate decisions also appear in the feed" has no backing rule and cannot be stored in `home_events` (Decision plus Fix). Lenses: design, codebase, zoom-out, readiness, structural, comprehension
- DOC 10; OV line 260; OV 7.1 (lines 127-135) has no rate-decision rule. FS `home_events` DDL (FS about lines 130-148) has `isin` and `symbol` NOT NULL, `exchange CHECK IN ('NSE')`, a closed six-value `event_type`, and two `feed_tier` values.
- Options: (a) cut "also in the feed" for v1; (b) have the Home events API merge a macro store at read time (do not widen `home_events`); (c) amend the FS schema (nullable symbol and ISIN, new type and exchange). Zoom-out recommends (a).
- Also undefined: feed tier, and dedupe against the LLM route (OV 6.1 "macro item on RBI or Fed policy stance"). Fix the cite in DOC line 10 and OV line 260 whichever way this goes.

### B3. The panel's data has no source, and the scope contradicts C4 (Decision). Lenses: all six
- DOC 13 cuts "stance extraction" (OV 7.7 C4). DOC 10 and 21-22 keep rate decisions, action and stance as panel fields. An RBI or Fed RSS item carries a title and a link, so action (a 25 bp change), new rate (5.50%, DOC 67) and stance need text parsing (the cut extraction) or hand entry.
- Stance vocabulary mismatch: DOC 22 defines hawkish, dovish and neutral. RBI's own terms (accommodative, neutral, withdrawal of accommodation, calibrated tightening in DOC 67) do not map. The Fed states no stance in that form. The neutral definition drops "future moves depend on incoming data" (OV line 262). DOC 21's "a cut can come with a hawkish stance" has no worked example (the 7 Oct 2026 case is a hike with tightening). "Stance" also means a stock-trend column in ui-redesign-spec 5.1.
- Options: hand-seeded decision rows; verbatim source text with no classification; action only; deferred; deterministic title parse. Zoom-out proposes: decision date, headline, link, verbatim stance text, optional hand-entered action and rate. A field list with units and sources per panel value is required in all cases.
- Corollary: the two RSS fetchers with the keyword filter (DOC 19-20) may be over-built for about 16 decisions a year (zoom-out). The filter (five terms, includes "Stance", no "Fed") also differs from the OV 9.2 macro prefilter, which the OV section 2 table assigns to the filings doc.

### B4. No collector integration and no dependency section (Decision, then Fix). Lenses: design, readiness, codebase, structural, comprehension
- The doc never links FS or SS and has no "Governing spec" line or dependency table (compare FS section 2 and FS line 7).
- Missing: collector source names (one `home_macro` or several: RBI/Fed poll, FRED, India CPI job), cron per source, `collector_sources` and `collector_settings` registration, whether they are events sources (API-down skip, SS 4.5), `config/collector_services.json` and `collector_runtime.json` entries, `_valid_param_keys` (returns an empty set for unknown sources), the `tests/test_collect_sources.py` pinned source set, the manual-first rollout (`ensure_sources()` placeholder-cron hazard, FS about line 120), and the migration number. Main-database migration number claimants today: SS S2 (047), S2a, S5a, S8, and the FS registration. Macro would be another. Events-database `002` is also contested.
- Prerequisites for "build second" (DOC 12) that none exist yet: SS S1a (run-once, `skipped`), S2 (cooldown), S3 (containerised Fastify), S4, S5a; FS T2, T5. SS M9 says services for new home-events sources belong to the owning spec's plan, and FS lists macro as out of scope, so nobody currently owns macro registration.
- Reuse (codebase lens): FS T3a/T3c define `classify_response` and `redact_error`. Do not write a second copy. Choose a separate module (for example `scanner/home_macro.py`) because FS Z6 puts everything in `scanner/home_events.py` and its tasks edit that file serially. `lxml` and `requests` are already in `requirements.txt`.

### B5. IST conversion for US releases is reversed (Fix: DOC 56 and OV line 279). Lenses: design, codebase, zoom-out, comprehension, structural, readiness
- DOC 56 says 8:30 a.m. ET is 6:00 p.m. IST in winter and 7:00 p.m. in summer. EST is UTC-5, so 13:30 UTC is 19:00 IST in winter. EDT is UTC-4, so 12:30 UTC is 18:00 IST in summer.
- Today's US CPI row (10 Nov, after US DST ended 1 Nov) is 19:00 IST.
- The FOMC statement (DOC 50, 2:00 p.m. EST on 9 Dec) is 19:00 UTC, which is 00:30 IST on **10 Dec**. An IST display shows a different date from the row label. Decide the display rule.
- Fix both docs. Store UTC plus an IANA zone (`America/New_York`, `Asia/Kolkata`) and add a test that converts via `zoneinfo`, never a hand-typed offset.

## Major

### M1. Calendar rows contradict themselves, today's date and the proposed schema (Fix plus Decision). DOC 41-59
- US CPI "Next date 10 Nov 2026" (DOC 48) is today (2026-11-10), while its status already says next release 10 Dec. By 10 Dec all four seeded rows are past, and there is no rule for rollover or who inserts the successor ("hand-seeded dates only" DOC 43 versus "re-check after each release" DOC 57 versus "dates after 12 Nov come from the MoSPI calendar" DOC 39). Zoom-out suggests seeding the full year in one pass, one row per occurrence, from a checked-in file.
- MPC row (DOC 49, also OV line 272) gives 4 Dec from the RBI schedule page dated 23 Mar 2026, yet says "the December decision has no date on the page yet". Both cannot hold. Per DOC 54 the row should be marked "unverified" or the source corrected. No decision time is given for the RBI row either.
- India CPI row: source "MoSPI advance release calendar" versus status "Date in the September 2026 press release".
- FOMC row packs three timestamps (statement, press conference, minutes 30 Dec) into one row. DOC 59 says four events only. Say whether minutes and press conference are rows (Decision).
- Schema (DOC 55-56): "scheduled UTC time" has no local-zone column (DOC 56 says store the local zone), no all-day or nullable time for date-only rows, no status enum (only "unverified" is used; "user-confirmed" and "released" are not covered by DOC 54), no unique key, no type for `source_url` and `checked_at`, and no rule for which country's calendar defines "next working day" (DOC 57).
- Label the seed table "as of 2026-11-10" and add a test that no seeded row is in the past at build time.

### M2. Poll cadence follows neither OV 7.3 nor the SS runner (Decision). DOC 72, 84
- OV 7.3 (line 149) default: every 5 minutes 08:00 to 15:30 IST on trading days, hourly otherwise. SS runs one cron per source. FS already overrode the OV default with a stated cron. DOC says "open" and also "carried from the overview".
- Macro events fall outside that window: Fed statement at 00:30 IST, US CPI at 18:00 or 19:00 IST, India CPI 16:00 IST (after 15:30). A filings-style IST window (`8-20`) would catch the Fed statement about 7.5 hours late. Do not gate US events on the NSE calendar.
- Choose: one low-frequency source with a conservative cron, or calendar-driven windows around each row's time. Also say whether RSS "default off" and "older than 1 week dropped" (OV 7.3) apply to RBI and Fed.

### M3. Cooldown and per-host request policy are mis-owned and not mapped to SS (Decision plus Fix). DOC 75-77, 82
- SS 4.3 and S2 define `exchange_cooldown` rows only for `nse`, `bse`, `upstox`, `screener`. There is none for RBI, Fed, FRED, BLS or MoSPI. Decide: request new rows from the SS session (FS did this for its hosts), or state that no shared cooldown applies.
- The OV section 2 table assigns "other hosts" request policy to each split doc, so this doc owns gap, cap and cooldown for them (OV 8.2 item 9). DOC 82 then lists the poll schedule as "not owned here". Move it into owned rules.
- Cap conflict is already open (OV line 152: 3 h; SS 4.3a: 2 h; FS line 465). Defer to SS and do not restate. Decide whether the SS 4.2 15-minute retry rule applies.
- List only hosts actually requested. If dates are hand-seeded, BLS and the Fed calendar page are never polled (DOC 58 and 77 overstate this).

### M4. India CPI ingestion job: scope, scheduling and "slot" (Decision plus Fix). DOC 36-39, 91
- It is the heaviest item in a doc whose other values are hand-entered, and C4 favours hand-seeding. The job is a user decision, so confirm or revisit (zoom-out suggests storing the value by hand with the press-release link in v1). Source format (HTML, PDF, Excel) and MoSPI terms are unknown.
- Scheduling: SS counts only `ok` runs and runs only the latest missed slot (SS 4.2). A single cron slot at 16:00 on the 12th that finds nothing posted records `ok` and waits for the next slot. The spec must define a release-day polling window, daily polls until found, and the status of a "not yet published" run.
- DOC 38 "the next available slot after the data release" is undefined: who misses it (MoSPI or the collector with the laptop off), and what is a slot. Define in SS terms or delete.

### M5. FRED series semantics, pass condition and key (Decision plus Fix). DOC 24-30
- `CPIAUCSL` is an index level, not an inflation rate. Define the displayed unit and where it is computed (YoY percentage via FRED `units=pc1` or computed), whether revisions are handled, and observation date versus release date. `FEDFUNDS` is a monthly average of the effective rate and lags the FOMC action, so it duplicates or conflicts with the decision row. Propose a concrete pass condition (series metadata title, units and frequency match, recent observation) to close OV 8.2 item 16.
- Key placement: DOC 28 says `FREDAPI_KEY` in `.env`, not verified. It is in no code, not in `env.template`, and is off the naming pattern of other keys. `secrets-and-roles.md` moves app keys into the `app_secret` store with collectors reading through the service token (`fetch_secret`). Decide secret store versus `.env`, and register the name accordingly. Never print the value.

### M6. Trading-day calendar: three conflicting sources, probably unnecessary (Decision). DOC 61-63, 95
- DOC and OV 8.2 item 7: NSE/BSE calendar (working assumption). FS D6b: Upstox market-holidays API (decided source). SS risk 8: the only holiday list is `EXCHANGE_HOLIDAYS_2026` in `ui-v2/src/lib/marketSession.ts` (unchecked broker summary; Python is weekday-only). 2026-11-10 is itself in that list as a holiday.
- Macro needs per-country calendars (India for MoSPI and RBI, US for BLS and the Fed), and the stored official dates already encode holidays. Suggest dropping stub item 6 and closing OV 8.2 item 7 as "weekday cron; holidays cost one empty run", or reassigning it to a cross-cutting owner.

### M7. Retention for macro and calendar rows is not stated (Decision). DOC 6, 82-84
- OV 7.4 covers event rows, news titles, links and Telegram updates for 3 years. Macro series and calendar rows are not events, and the purge is deferred (FS Z5) inside the `home_filings` run. Say keep (tiny) or 3 years, and name the purge owner. Also correct the ownership wording (see N1).

### M8. No UI home and no read contract (Decision plus Fix). DOC 5, 9-11
- "Market dashboard" (DOC 11, OV 10.2) is not a screen in `ui-redesign-spec.md`. Its 5.1 is the scan table and shortlist, section 6 is the event rule, and section 7 says market mood is "Not available". Name the screen, the owning UI spec, the endpoints, and empty and stale states (ui-redesign-spec section 8). Add a one-paragraph goal (what the user sees and why). Calendar and panel need endpoints that the browser reads only via Fastify (UI-through-API rule).

### M9. Alert lead times have no alert channel (Decision). DOC 73, 101
- No alert mechanism for macro exists in any doc. Options: dashboard countdown (OV 10.3 "countdown and lead times open"; DOC dropped "countdown" silently), push through the existing Telegram path (`scanner/expiry_alerts.py` with `token_alert_sent` dedupe is a reuse candidate), or cut from v1 (zoom-out: speculative for four dated events a month).

### M10. Terms and fetchability of the macro hosts are unread (Decision plus Fix). DOC 30; OV 4.1, 8.2 item 15
- OV 4.1 and item 15 cover NSE, BSE, Investing.com, CNBC, Upstox and LinkedIn only. RBI, Fed, BLS and MoSPI terms are neither read nor listed as unread. DOC records only FRED. Add them to item 15 or record the user's personal-use acceptance. RBI, BLS and MoSPI may block scripted clients; user agent and cookie needs are unknown.
- No sample-capture task exists (FS T0 precedent): fetch each URL once, save under the sample directory, record tag and date formats, check feed depth. A wrong URL could return 403 and trigger a cooldown. Consider the FRED release-dates API for BLS and Fed dates before scraping HTML (verify).

### M11. The "Build specs (stub)" list is incomplete (Fix). DOC 86-96
- Compared with FS rev 4, still missing: database and endpoint list, token role and name, `AppDeps` and health-check changes, file-change and must-not-change lists, config-key table in FS section 7 style (key, default, unit, validation), migration numbers and rollout hazards with down steps, runner behaviour (API-down, cooldown, status mapping, run deadline), sample-capture task, fixture policy (real samples not committed, synthetic committed), parsers and per-parser tests (empty, malformed, HTML 200, missing field, bad date), phases and checkpoints with per-task acceptance commands, and an "Alternatives Considered" section (events versus main database, polling versus calendar-driven fetch).
- Several stub items restate Open items. Merge the two lists and point by number.

### M12. Test plan item 7 describes a network check as a test (Fix). DOC 96; OV 7.7 line 187
- "Each calendar date matches its official page" needs the network. It must be opt-in and outside the offline command. Offline tests use recorded samples: IST/ET conversion, YoY computation, keyword filter (with a negative fixture, since "Inflation" and "Stance" match unrelated RBI releases), seed-file validity, `plan()` shape. The acceptance command already exists (`.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`), so "to be set before build" can be settled now.

### M13. Ownership and structure of the doc (Fix). DOC 3, 6, 65-84, 98-104
- "Owned rules" contains items that are open or proposed, not decided (stance definitions DOC 22, trading-day calendar DOC 61-63, cadence DOC 70-73, rate limits DOC 75-77). Make Owned rules decided-only and state each open item once, in Open, with an owner. The 16:00 IST confirmation, India CPI job, trading-day calendar, stance and cadence each appear two or three times.
- "Conflicts resolved" (DOC 65-68) duplicates OV 10.4 as a changelog, omits the MoSPI bullet, and its repo-rate figures go stale at the next decision. Replace with a pointer, and move the data to seed content.
- Two live copies of OV section 10 rules now exist (OV line 29 says "held here until the owning doc is updated"). Pick the governing copy and shrink the other to a pointer.

## Nits

- **N1.** DOC 3 header cite and DOC 6 / 83 retention ownership (see Cite audit). Fix.
- **N2.** DOC 36 and OV 8.2 item 17 / 10.4 frame "4:00 p.m." in secondary sources against "16:00 IST". They are the same time. The only open point is that no MoSPI page confirms it. OV item 17's "the macro doc's 4:00 PM statement must be corrected" is stale: DOC does not contain it. Fix both.
- **N3.** DOC 104 lists "Build order and approval for this phase" as open, but build order was approved (OV 7.7 C6, 2026-11-10; DOC 12). Only approval of the build spec remains. Fix.
- **N4.** DOC 58 lists "India CPI and WPI" and "RBI press releases (MPC dates)" while DOC 59 limits scope to four events and DOC 49 sources MPC dates from the RBI schedule page. Drop WPI, pick one MPC source, and split manual lookups from polled sources.
- **N5.** DOC 19 keyword filter versus OV 9.2: define which list serves which stage, whether it matches title or description, whole words or substring, and define "priority 1" (priorities 2 and 3 exist only in the cut statement).
- **N6.** DOC 5 "Screen" line is boilerplate from the sibling stubs. DOC 6 links only the overview. Add links to FS and SS. Line 3 status should state the doc's role and say FS rev 4 and SS exist.
- **N7.** Undefined terms and acronyms: MoSPI, BLS, FRED, MPC, FOMC, SDF, MSF, Bank Rate, ET, "advance release calendar", "the job", "events database". "bp" (DOC 21) versus "bps" (DOC 67). Add a short glossary.
- **N8.** OV defects found in passing (overview edits, outside this doc): OV line 9 "none of the split docs has build specs yet" is stale; merged bullets at OV lines 92 and 280; OV line 152 states a generic cooldown while the table says macro hosts are "not set"; OV 8.2 item 14 (stale section numbers) is partly done.

## Fix versus decision summary

- **Decisions for the user (resolve first):** B1, B2, B3, B4 (source layout and cron), M2, M3 (host rows), M4 (job in or out of v1), M5 (units and key placement), M6, M7, M8 (screen), M9, M10 (terms), M1 (row model, FOMC sub-events), M13 (governing copy of section 10).
- **Fixes to the doc (no decision needed):** B5 (also OV line 279), M1 schema columns, M11, M12, N1 to N7, M13 structure.
- **Fixes to other files:** OV lines 260, 279, 9, 92, 280, 8.2 item 17 (and a possible cap conflict at line 152 versus SS 4.3a).

## Suggested order

1. Decide B1 and B2 (database, write path, feed integration).
2. Decide B3 and the v1 scope (stance source, India CPI job, RSS fetchers, alerts, trading-day calendar). The zoom-out lens recommends the smallest v1: hand-seeded full-year dates, a panel row with link and verbatim stance, two FRED series with a defined transform, main database, no alerts, no calendar module. This is a recommendation, not a decision.
3. Decide B4 and M3 (source layout, cron, host cooldown request to the SS session) and write the dependency table.
4. Fix the wrong and stale facts (B5, M1 contradictions, N2, N3) in this doc and the overview.
5. Rewrite the build-spec list against M11 and add the sample-capture task before DDL.

## Lens notes

- All six lenses independently found B1, B2, B3 and B5. Cooldown host rows, the OV 7.3 cadence mismatch, the three-way holiday conflict, and the FRED semantics and key placement were found by at least five.
- Verified from the repo by lenses: no FRED, MoSPI or macro code exists; `env.template` has no FRED key; highest main-database migration is `046_token_expiry_alert.sql`.
- Not verified by any lens (no network): calendar dates, the RBI repo rate, and the feed URLs.
- One lens (design) did not read the other three standards; findings were not affected.
