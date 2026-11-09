# Upstox as secondary fundamentals source

Status: decisions approved 2026-11-10 and amended after the EGM review. Not built. Pre-build checks are listed under "Open before build".
Related: `docs/designs/fundamentals-tables.md`, `docs/designs/secrets-and-roles.md`, `scanner/fund_derive.py`, `scanner/upstox.py`, `scripts/fetch_upstox_sector.py`.

Terms used here: **Screener** means screener.in, the primary fundamentals source. **Upstox** means the Upstox broker API, the secondary source. **ISIN** is the international security ID that Upstox keys its endpoints on. **P/E** is price divided by earnings per share (EPS). **ROA** is return on assets. **ROE** is return on equity. **ROCE** is return on capital employed. **EV/EBITDA** is enterprise value divided by earnings before interest, tax, depreciation and amortisation. **Basis** means whether a figure is consolidated or standalone, and which entity it describes.

## Rules

1. Screener is the primary source for every fundamentals field it provides for a stock.
2. Upstox fills a field only when Screener has no usable value for that stock and that field (see Fallback triggers).
3. Every Upstox key-ratio value is stored, including P/E and sector values. The reader uses the Screener value when one exists. The stored Upstox value is used only when Screener has none. Values are never averaged, and no Upstox value overwrites a Screener value.
4. Every stored value records its source (`screener` or `upstox`), its basis, and an as-of date.

## Why the rule is needed

- `scanner/fund_derive.py` derives market cap, P/E, book value, ROE, ROCE, dividend yield, EPS CAGR and PEG from Screener data, so Upstox adds nothing to those today.
- Upstox P/E has a basis we have not confirmed. For TCS, Upstox P/E is 17.41, while price over basic EPS gives 18.20. For Reliance, Upstox gives 18.72, while price over basic EPS gives 22.19. Upstox P/E is therefore stored but never used.
- Upstox sector benchmark values are unreliable. For example, the Upstox sector EV/EBITDA for the TCS sector is -199.08, and the sector P/E is -9.5.

## Candidate fields that Screener does not give us

| Field | Upstox endpoint and name | Use |
|---|---|---|
| ROA | `/v2/fundamentals/{isin}/key-ratios`, `name = "ROA"` | New stored field, used by fallback |
| EV/EBITDA | same, `name = "EV/EBITDA"` | New stored field, used by fallback |
| Quick Ratio | same, `name = "Quick Ratio"` | New stored field, used by fallback |
| Last price | `/v2/market-quote/quotes` (`last_price`) | Not built now |
| Company description | `/v2/fundamentals/{isin}/profile` (`company_profile`) | Not built now |
| Corporate actions | `/v2/fundamentals/{isin}/corporate-actions` | Not built now |

Verified 2026-11-10 against TCS (ISIN `INE467B01029`). The key-ratios response has the names above, with `company_value` and `sector_value` as strings. ROA and the sector values are percent strings such as `27.18%`. The saved response is `tests/fixtures/upstox/key_ratios_tcs_INE467B01029.json`.

The other key-ratio names in the same response are P/B, ROE and ROCE. Screener already provides ROE and ROCE, so they are covered by the fallback rule, not by the new-field list.

Stored but never used by the fallback: Upstox P/E and all sector benchmark values.

Not fetched for now: competitors.

## Not covered by Upstox

Face value, share count and borrowings have no Upstox source. Screener stays the only source for them. No share count is estimated from PAT / EPS, because net profit includes minority interest, and `fund_derive.py` already rejects that method.

## Fallback triggers

The fallback uses an Upstox value for a field only when one of these holds:

- (a) Screener has no data for the stock at all. This covers a stock that Screener does not fetch or cannot find.
- (b) Screener has data for the stock but does not provide that field.

Proposed, needs your OK: a field that Screener returns as "not applicable" is not a trigger. Example: bank ROCE is `None` by design in `fund_derive.py`, so Upstox does not fill it.

## Definition of "Screener has a value" (proposed, needs your OK)

- ROE: the Screener value is the top-ratios `ROE %` (`roe_pct`). If that is missing, the value derived in `fund_derive.py` counts as the Screener value. Upstox ROE is used only when both are missing.
- ROCE: the same rule, with the top-ratios `ROCE %` and the derived ROCE.
- A value counts as present when it is non-null and not marked "not applicable".

## Decisions

Approved 2026-11-10, amended after the EGM review.

1. The fields used from Upstox are ROA, EV/EBITDA and Quick Ratio, plus any other field Upstox can supply when Screener does not provide it (decision 2 below). Last price, company description and corporate actions are not built now.
2. The fallback applies to any field Upstox can supply. Upstox P/E and sector benchmark values are stored but never used by the fallback.
3. Every Upstox key-ratio value is stored. The fallback decides which value is used (Rule 3).
4. Fallback triggers are (a) and (b) above.
5. Storage target is Postgres. Mongo stays for unstructured data: announcements, order book, concall and annual report data. The Mongo fundamentals plan was dropped.
6. Upstox token: revised 2026-11-10. The fundamentals feed uses the Upstox analytics token: generated once by hand, valid for 1 year, read-only, no daily approval and no refresh. The refresh flow is for order management and is not used. The app stores no Upstox login credentials. Details are in [secrets-and-roles.md](secrets-and-roles.md).
7. Basis: each stored value records its basis. For Screener that is consolidated or standalone. For Upstox it is the entity Upstox reports.
8. Source order is fixed: Screener first, Upstox for gaps. This matches Rule 1 and rule 8 of `secrets-and-roles.md`.
9. Share count is not estimated.
10. Minimum scope (one endpoint, three fields, no merge logic) is not adopted, because decision 2 keeps the fallback open to any field Upstox can supply.
11. Screener is read from public pages only. The collector does not log in. The Excel export is not used for the fundamentals feed, because it has a daily limit. Logged-in ratio tables are therefore not needed for the build. The login code in `scanner/screener.py` stays optional and is not relied on.

## Review items closed in this revision

From the EGM brainstorm review (`concepts_brief.md`):

- **Rules 2 and 3 contradicted each other.** Resolved by Rule 3. Upstox values are always stored, and the reader picks one value per field.
- **Storage schema could not hold source `upstox`.** Resolved by decision 5. The Postgres schema must allow `upstox` in the source column. Migration 027 is not applied, so this is a change to that unapplied migration.
- **Target store was undecided.** Resolved by decision 5.
- **Token conflict.** Resolved by decision 6. The Upstox endpoints for the request and refresh flows are still open (see below).
- **No acceptance fixture.** Partly resolved. The Upstox response is saved. The Screener page fixture is still open.
- **ISIN source was unnamed.** Resolved: `symbol_sector.isin` is the source. Checked 2026-11-10: 751 symbols, all with an ISIN. Symbols without an ISIN are counted and reported each run, not skipped silently.
- **"Any field" scope had no list.** Resolved by decision 2 and the exclusions. P/E and sector values are stored but not used by the fallback.
- **"Has a value" was undefined.** Resolved by the proposed definition above, which needs your OK.
- **Entity basis was not stored.** Resolved by decision 7.
- **Primary-source policy contradicted itself.** Resolved by decision 8. `secrets-and-roles.md` has been updated to match.
- **Share-count estimate conflicted with code.** Resolved by removing it.
- **Reuse was missed.** Design direction: add the fundamentals call to the existing `UpstoxClient` in `scanner/upstox.py`. It already has bearer auth, a rate limiter and 429 handling. Do not write a third copy of the auth and retry code.
- **Ratio premise was unchecked.** Partly checked. The Screener parser (`scanner/screener.py`, `scanner/fund_derive.py`) has no ROA, Quick Ratio or EV/EBITDA field. The live Screener pages were not checked, because no saved Screener page exists yet.
- **P/E exclusion was not enforced.** Design direction: the field mapping is an allowlist, so P/E is never mapped to a Screener column. A test fails if P/E is mapped.
- **Response shape was unverified.** Resolved for TCS. The three names are confirmed.
- **Existing Screener values had no source tag.** Proposed: backfill existing Screener values with source `screener` when the schema is applied.

## Checks run 2026-11-10 (findings)

Sources: the official Upstox pages named below, and one live call with the analytics token from the collector container (`market-scanner-collector-1`). The token was not printed or pasted.

1. **Rate limits (official page `https://upstox.com/developer/api-documentation/rate-limiting/`).** Fundamentals falls under "Other Standard APIs": 50 requests per second, 500 per minute and 2000 per 30 minutes. Limits are enforced per API and per user. The page lists no daily limit. A web search gave 25 / 250 / 1000 per second, minute and 30 minutes. The official page contradicts that, so those figures are not used.
2. **Live call.** One request to `/v2/fundamentals/INE467B01029/key-ratios` returned `status: success`. The values match the saved fixture exactly. No 429 responses and no waiting were recorded. This does not measure the daily limit or the limit under load.
3. **Quick Ratio is missing from the Upstox docs.** The get-key-ratios page lists the names P/E, P/B, ROA, ROE, ROCE and EV/EBITDA only. The live response also contains `Quick Ratio` (TCS: 2.23). The docs are incomplete. The field is accepted because the live response returns it. Its name must be checked on every run, because the docs do not promise it.
4. **ROE and ROCE do not match Screener for TCS.** Screener shows ROE 51.8% and ROCE 63.0%. Upstox shows ROE 43.37% and ROCE 53.06%. The Upstox docs define ROCE as EBIT divided by capital employed, and `fund_derive.py` uses (PBT + interest) / (net worth + borrowings). The two sources also do not say whether they use the same period. Rule 1 keeps Screener as the stored value, so the output is unchanged. The Upstox ROE and ROCE values must not be treated as a cross-check of Screener until the basis is confirmed.
5. **The Upstox docs give no formulas for ROA, ROE, ROCE or EV/EBITDA**, and no period definition for `company_value` or `sector_value`. The docs describe ROA as net income over total assets, ROE as net income over shareholders' equity, ROCE as EBIT over capital employed and EV/EBITDA as enterprise value over EBITDA. No formulas are given.
6. **A plain Python `urllib` request to the same endpoint returned HTTP 403** (Cloudflare error 1010, blocked by its default user agent). The project's `UpstoxClient` works only because it uses `requests` and sends its own headers. That is luck, not a supported path. **Revised:** fetches use the official Upstox SDK, not hand-built HTTP. The Python SDK `upstox-python-sdk` is pinned at 2.30.0 (PyPI, published 2026-09-07, source at `github.com/upstox/upstox-python`). It is installed in the project `.venv` only. It is not yet in the collector image or any requirements file. Adding it to the image is a separate step to confirm.
7. **The Fundamentals section has more endpoints than this doc uses.** The Upstox sidebar lists Company Profile, Balance Sheet, Cash Flow, Income Statement, Share Holdings, Key Ratios, Corporate Actions and Competitors. Balance sheet and income statement are the source for the ROA basis check below. They are not yet mapped to any stored field.
8. **ROA basis check, run 2026-11-10 (SDK).** ROA here is net profit divided by year-end total assets, from Upstox's own statements, consolidated, in crore.

   | Stock | Period | Net profit | Total assets | Computed ROA | Upstox key-ratios ROA |
   |---|---|---|---|---|---|
   | TCS | Mar 2026 | 49,454 | 182,372 | 27.12% | 27.18% |
   | Reliance | Mar 2026 | 95,610 | 2,178,140 | 4.39% | 4.18% |
   | Bharti Airtel | Mar 2026 | 33,823 | 552,152 | 6.13% | 6.77% |
   | HDFC Bank | Mar 2026 | 79,219 | 4,908,041 | 1.61% | 1.94% |

   - TCS matches within rounding. Average total assets give 28.9%, so for TCS the Upstox figure uses year-end assets.
   - Reliance, Airtel and HDFC Bank do not match. Gaps: Reliance -0.21, Airtel +0.64, HDFC Bank -0.33 points. The gaps change sign, so no single rule explains them.
   - Attributable-to-owners profit was tested as the explanation and does not hold. For HDFC Bank, Upstox's ROA implies about 95,200 crore of profit, more than the reported net profit of 79,219 crore. Attributable profit cannot exceed the consolidated figure, so this rules it out for HDFC Bank. The Airtel figure also points the wrong way.
   - Average assets and prior-year assets were also tried. They do not explain all three gaps (Reliance's implied denominator is above its current year-end assets).
   - Conclusion: the ROA basis check **fails for three of four stocks**. The Upstox ROA definition is unknown, so ROA is not approved for use. The definition must come from Upstox.
   - Quick Ratio cannot be checked: the balance sheet response has `full_statement: null`, so current assets and current liabilities are not returned. EV/EBITDA cannot be checked without a price and share count, which this doc does not yet source.

Effect on the open checks below:
- The ROA basis check was run in item 8 and **fails for Reliance**. Total assets are available from Upstox's balance sheet endpoint, so the check no longer needs Screener's page. Quick Ratio is still unchecked (no current assets or liabilities in the response).
- The live analytics-token call is **done** (item 2).
- The daily-limit check is **partly done**: the official limit is recorded, but the daily cap is not measured.

## Failure states

Each run reports these counts separately, so they are not mistaken for "no data":

- Upstox request failed (network or HTTP error).
- Token expired or rejected (HTTP 401 or 403). Reported as a failure. No refresh is attempted, because the analytics token has no refresh flow (decision 6).
- No Upstox data for the stock.
- Symbol has no ISIN.

Each Upstox value stores an as-of date. Fundamentals change quarterly, so the collector caches Upstox values, and the cache lifetime is a build decision.

## Open before build

- **Basis check.** ROA: run for TCS, Reliance, Bharti Airtel and HDFC Bank (see "Checks run" item 8). Only TCS matches. The attributable-profit explanation is ruled out for HDFC Bank. Ask Upstox for the ROA definition before ROA is used. Quick Ratio: needs a source for current assets and liabilities. EV/EBITDA: define the EV and EBITDA inputs first. Do not use these three fields until each passes.
- **Screener premise check (partly done 2026-11-10).** One public Screener page per sector (12 sectors, consolidated pages). The default page has the same eight top ratios on every sector sample: Book Value, Current Price, Dividend Yield, Face Value, Market Cap, ROCE, ROE, Stock P/E. No page has ROA or "Return on Assets". Two signs need follow-up:
  - Quick Ratio appears in an "Add ratio to table" feature (Screener's ratio-table editor). The values are not in the public page, so the premise is not proven either way.
  - "EV / EBITDA" appears only as a chart metric label, not as a value.
  Decision 11 drops the logged-in check. Public pages are the only Screener source, so ROA, Quick Ratio and EV/EBITDA come from Upstox for every stock. The check on TCS and Reliance pages saved from the browser (`tests/fixtures/screener/`) showed no ROA or Quick Ratio row, logged in or not.
- **Screener fixture.** Save one Screener page for the same stock as the Upstox fixture.
- **Upstox analytics token (checked 2026-11-10).** Documented as 1 year, read-only, Fundamentals supported, no static IP. Live fundamentals call done 2026-11-10 (see "Checks run" above). Expiry date still to be recorded (see secrets-and-roles.md, "Open items").
- **No Upstox login credentials (decided 2026-11-10).** The app stores and uses no Upstox user ID, password, PIN or TOTP secret.
- **Quota.** The official per-second, per-minute and per-30-minute limits are recorded (see "Checks run"). Measure the daily limit before the collector is scheduled, because the docs state none.
- **ROE and ROCE basis.** Confirm whether Upstox ROE and ROCE use the same period and formula as Screener, using a second stock (Reliance) for comparison. Until then Upstox ROE and ROCE are not used as a cross-check.
- **Quick Ratio name.** Confirm the exact name and meaning with Upstox support, because the official docs omit it.
- **Rollback.** The migration grants SELECT, INSERT and UPDATE only, with no DELETE. Decide how bad Upstox rows are removed, and who runs that step.
- **Proposed, needs your OK:** the "not applicable" rule and the ROE/ROCE definition above.

## Verification

- A test asserts that a Screener value is never replaced by an Upstox value.
- A test asserts that a stock missing from Screener gets the Upstox fields.
- A test asserts that a stock where Screener lacks only one field gets only that field from Upstox.
- A test asserts that P/E and sector benchmark values are stored but never used by the fallback.
- A test asserts that P/E is never mapped to a Screener column.
- A test asserts that every stored value has a source tag, a basis and an as-of date.
- A test asserts that an expired token is reported as a failure, not as no data.
- A test asserts that a symbol with no ISIN is counted and reported in each run.
- Offline test command: `.venv\Scripts\python.exe -m unittest discover -s tests -t . -q`.

## Risks

- Upstox ratio values may not match the basis of Screener values, even after the basis check.
- If the token failure path is not built, the feed can go silently empty.
- Stocks without an ISIN get no fallback. Coverage is unknown until counted.
- The Upstox P/E basis may stay unknown, so P/E remains Screener-only.

## Analytics token expiry alert (proposed 2026-11-10, needs your OK)

Purpose: tell the user before the Upstox analytics token expires, in the same Telegram group the news-link bot reads from (section 4.2 of `home-event-sources.md`).

- **Expiry date:** stored in `app_secret` with the token. The admin enters the token, its created date and its expiry date on the configuration screen (see secrets-and-roles.md, decision 4), and can update any of the three. The token lasts 1 year, and only one analytics token exists per account (Upstox docs, checked 2026-11-10).
- **Current token (from the Developer Apps page, screenshot 2026-11-10):** created 2026-05-18, expires 2027-05-18. Alert dates: 2027-04-18 (30 days), 2027-05-11 (7 days), 2027-05-17 (1 day), and 2027-05-18 (expiry day).
- **Scheduled alerts:** a daily check sends one Telegram message at 30 days, 7 days and 1 day before expiry, and once on the expiry day. Each alert is sent once and recorded, so reruns do not repeat it.
- **Failure alert:** if a fundamentals call returns an authorisation error (HTTP 401 or 403), send one alert at once. This covers early revocation, for example if the token is regenerated elsewhere.
- **Message content:** the token name and expiry date only. The token value is never included.
- **Sending:** Telegram Bot API `sendMessage` with the bot token and the group chat ID. Both are stored encrypted in `app_secret`, not in the code or chat. The bot must be a member of the group. Sending needs no bot polling, so this check does not depend on the news-link bot being built.
- **Failure of the alert itself:** logged in the run report. It does not block the fundamentals run.

Open for you:
1. Confirm the alert days (30, 7, 1 and the expiry day).
2. Provide the bot token and group chat ID through the admin screen once it exists, or tell me to add them to `app_secret` directly. Do not paste them in chat.
3. Confirm this is built through the EGM process, since it touches config, a scheduled job and an external call.
