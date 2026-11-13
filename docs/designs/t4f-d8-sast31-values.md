# T4f decision D8: insider threshold and age floor for `nse:Sast_Regulation31`

Status: DECIDED 2026-11-13 (user, option B): no size threshold, ingest_floor_days = 730 for all eight feeds (not 365). The recommendation below is kept as written for the record; where it says 365, the decided value is 730. Written 2026-11-13 from repo files and the fixture only. No live NSE call was made.
Fixture: `tests/fixtures/home_events/nse_Sast_Regulation31.xml` (20 items). "Age" is counted from 2026-11-13; the spec counts from the 2026-11-11 sample date.

## 1. What the feed offers

Each of the 20 items has four fields: `title` (company name), `link` (a zip file), `description` and `pubDate`. Nothing else (filings spec line 176).
- `description` is one pair, `NAME OF PROMOTER(S) OR PACS WITH HIM : <name>`. All 20 items use this same key; maximum length 111 characters (spec line 209). So "person category" exists only as this constant, and the promoter name is free text.
- No share count, no transaction value, no percentage of holding, no buy or sell flag, no event date. The parser (`scanner/home_events.py:722-729`) keeps none of these, and the feed has none to keep. The spec already lists `value_cr` and `pct_shares` as deferred (spec line 334).
- Filing date: `pubDate` only. It runs 21-Oct-2026 14:09 to 29-Oct-2026 11:13 (spec line 183; fixture agrees).
- 3 of 20 zip file names contain "Pledge" (`VMIPL_Pledge_...`, `Pledge_...`, `IntimationReleaseofPledge_...`). The other 17 have generic names.
- Mismatch to know about: `home-event-sources.md` line 160 describes the insider rule as "promoter open-market buys and sells above a threshold percentage". This feed has no buy or sell field. My understanding (not in the repo, please check) is that SAST Regulation 31 covers pledges of promoter shares, not open-market trades. The 3 "Pledge" file names fit that reading.
- Sample shape: 15 distinct companies; Billionbrains has 4 items, Themis Medicare 2, Vintage Coffee 2. 18 distinct (company, filing day) pairs.

## 2. Insider-trade threshold: candidate rules and the fixture result

| Rule | Kept of 20 | Dropped | Needs |
|---|---|---|---|
| A. No size threshold; keep every filing that resolves to a stock | 20 | 0 (10 more drop later on name match, spec line 375, 751 universe) | nothing |
| B. Keep only file names containing "Pledge" | 3 | 17 | string test on `link`; 17 real filings lost because their names are generic |
| C. Keep one filing per (company, filing day) | 18 | 2 (Billionbrains, 29-Oct and 28-Oct) | grouping step |
| D. Percentage or value above N | cannot be run | not computable | a size field the feed does not carry |

- Rule D is the one the overview describes (line 241, "percentage"). It cannot be applied to this feed. It would need either the zip contents or another source. What the zip holds is unknown; no zip is in the repo.
- The decided Home cap of 3 events per stock (`home-event-sources.md` line 164) already acts as a limiter. On the fixture it removes 1 item (Billionbrains has 4).

## 3. Age floor: what the spec decided, and candidates

Your reading is right on the main point. Filings spec line 371 says the ingest floor (`date_floor`, `ingest_floor_days`) and the future-date test are deferred (decided 2026-11-10), and adds that the floor "must be settled before the first run". Two corrections: it is one floor for all eight feeds, not a Sast31 value; and the sample argues for a floor, because Related_Party_Trans holds items up to 628 days old. Related decisions: RSS depth of about one year accepted (spec line 507); retention 3 years, purge deferred (line 503).

Counts on the fixtures, by age in days from 2026-11-13:

| Floor | Sast_Regulation31 kept of 20 | Related_Party_Trans kept of 20 | Sast_Regulation29 kept of 20 | Other four feeds (82 items) |
|---|---|---|---|---|
| 14 days | 0 | 0 | 12 | 82 kept |
| 30 days | 20 | 0 | 20 | 82 kept |
| 365 days | 20 | 10 | 20 | 82 kept |
| 730 days | 20 | 20 | 20 | 82 kept |

(Other four: Corporate_action 58, Integrated_Filing_Financials 20, Financial_Results 3, Shareholding_Pattern 1; all are 2 to 10 days old. Corporate_Governance has no items.)
Sast31 items are 15 to 23 days old, so any floor from 30 days up changes nothing for this feed. 21 days would keep 8 of 20.

## 4. Recommended pair

1. Threshold: no size threshold for Sast_Regulation31 in the MVP (rule A). Rely on the Home cap of 3 per stock.
2. Age floor: `ingest_floor_days = 365`, applied to all eight feeds at ingest.

Reasons:
- A size threshold cannot be written on fields that exist (section 1). Setting one now would be a number with nothing to compare it to.
- Rule A drops nothing real and the cap of 3 handles the repeat filings seen in the sample.
- 365 days matches the answer already given about RSS depth (spec line 507). It keeps all 20 Sast31 items and 10 of 20 Related_Party_Trans items, and it stops a wrongly dated old item from being stored for good (spec line 371 says rejected items are not recoverable, so a floor that is too tight loses data; 365 is loose).
- Risk: the 10 Related_Party_Trans items older than 365 days would not be stored. Use 730 if you want all 20.

## 5. Cost in code

- Threshold: none now. A real threshold later needs a new parsed field, the deferred columns (spec line 334) and a migration, plus a source for the size. Not sized here.
- Floor: `filter_items` (`scanner/home_events.py:145-168`) takes no time argument today. Add one small step before it in `run_cycle` (call site line 496, where `now` is available at line 410): drop items older than `now - ingest_floor_days` and count them as a new rejection reason `date_floor`. The reason list in spec line 366 names only `parse` and `universe`, so the spec and the run message wording change too. Config: one key in `_run_config` (spec section 7). About 15 to 25 lines of code and 3 to 4 tests. This is a planning estimate, not measured. Another session is editing `scanner/collect/` and `collect.py`; this change is in `home_events.py` only.

## 6. The question for the user

Approve `no size threshold for Sast_Regulation31 (Home cap of 3 per stock only)` and `ingest_floor_days = 365 for all eight feeds`? If not, give the number you want for the floor (30, 365 or 730 are the sensible options), and say whether a size rule must wait for a source that carries a percentage.

## 7. Unknown

- What the zip files contain (no size in the feed; zips are not in the repo).
- Whether Regulation 31 is the pledge disclosure (outside the repo; check against the NSE definition).
- Sast31 match count against the full NSE list (task NEW-SAST31-MEASURE, `t4f-mvp-plan.md` line 33); only the 751-universe figure of 10 of 20 is recorded.
- Whether Home should also show only recent filings (a display window); not decided anywhere I read.
