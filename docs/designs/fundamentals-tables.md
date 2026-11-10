# Fundamentals tables and summary (stock page, Option D)

Status: draft, awaiting approval. No code changed. Date: 2026-11-09.
Related: `docs/designs/ui-redesign-directions.md` (Option D), `docs/designs/concall-summary-template.md`.

## What exists today

The collector keeps only a small subset of one screener.in page per company. Stored in MongoDB (`scanner/docstore.py`, `DOCSTORE_BACKEND` defaults to `mongo`), one document per symbol, in `scanner/fundamentals.py` `Fundamentals`:

| Stored field | Source on the page |
|---|---|
| `mcap_cr`, `pe`, `roce`, `roe` | `#top-ratios` list |
| `debt_to_equity` | Derived from `#balance-sheet` (borrowings / equity + reserves) |
| `pledged_pct` | Text in `#analysis` ("promoters have pledged X%") |
| `promoter_holding_pct` | `#shareholding`, Promoters row, latest quarter |
| `quarterly_sales`, `annual_sales` | `#quarters` and `#profit-loss`, "Sales" row only |

The parsers `parse_profit_loss`, `parse_balance_sheet`, `parse_quarterly_results`, and `parse_shareholding` in `scanner/screener.py` already read the full tables. Fundamentals keeps only the sales row from them. The rest is discarded.

Not parsed at all: cash flow, the ratios table (debtor days, inventory days, cash conversion cycle), and the compounded growth table.

Two facts shape the design:
1. **Storage is split.** The UI reads Postgres. Fundamentals are in MongoDB. The stock page cannot read them without a new path.
2. **The source is unreviewed.** Full tables mean more of the same screener.in content. See "Open risks".

## Target: the tables on the stock page

Section ids and row labels below are verified against three saved screener.in pages you supplied (`C:\Users\vaibh\OneDrive\Desktop\screener`): TCS, Sterlite Technologies, and Fredun Pharmaceuticals. Each section's labels, as extracted from those pages, are listed in "Verified row labels" below. The fourth saved file in that folder is a concall.in page, used later in the concall step.

## Implementation status (2026-11-09)

- **Derived ratios** (`scanner/fund_derive.py`, `key_ratios`): market cap, P/E, book value, ROE, ROCE, dividend yield, 5-year EPS CAGR and PEG. Each has a stated basis. Face value is now an input from the #top-ratios row.
- **Bank rule:** `is_bank` detects a bank from its own balance-sheet "Deposits" row, not a name list. ROCE is not applicable to banks. PEG applies to banks and non-banks alike.
- **Daily series:** `quarterly_eps` gives effective dates as quarter end plus 45 days. This is an assumption, and the real result date should come from the announcements table once it is stored.
- **Not done:** the long-format table migration (next number 027), the writer that loads quarterly, annual and daily EOD series, and the 52-week high/low wiring. Validation against the saved pages is still to do.

| Section | Periods | Rows (from the page) | Stored today |
|---|---|---|---|
| Key ratios | Current | Market cap, current price, high/low, stock P/E, book value, dividend yield, ROCE, ROE, face value | Partly. Face value is now read from the #top-ratios "Face Value" row (`fund_derive.face_value_from_overview`) and drives share count, market cap and book value in `key_ratios`. High/low is still not wired. |
| Quarterly results | Last 12 quarters + trend | Sales, expenses, operating profit, OPM %, other income, interest, depreciation, profit before tax, tax %, net profit, EPS | Sales only |
| Profit and loss | Last 10 years + TTM | Sales, expenses, operating profit, OPM %, other income, interest, depreciation, profit before tax, tax %, net profit, EPS, dividend payout % | Sales only |
| Balance sheet | Last 10 years | Equity capital, reserves, borrowings, other liabilities, total liabilities, fixed assets, CWIP, investments, other assets, total assets | D/E only |
| Cash flows | Last 10 years | Cash from operations, investing, financing, net cash flow | No |
| Ratios | Last 10 years | Debtor days, inventory days, days payable, cash conversion cycle, working capital days, ROCE % | No |
| Growth | Compounded 10y, 5y, 3y, TTM | Sales growth, profit growth, stock price CAGR, ROE | No |
| Shareholding | Last 12 quarters | Promoters, FIIs, DIIs, government, public, number of shareholders | Promoters only |
| Pledge | Latest | % of promoter holding pledged | Yes |

Each table keeps the page's column order. A table with no data says "not on the page for this company", not blank.

## Summary

A short block at the top of the Fundamentals section. It is built by code from the tables, not written by the LLM, so every sentence can be checked against a number.

Rules, one sentence each, shown only when the inputs exist:
- Sales: latest annual value, and the 5-year compounded growth from the Growth table.
- Profit: latest net profit, and 5-year profit growth.
- Margin: latest OPM % and the change over 5 years, in percentage points.
- Return: ROCE and ROE latest, against their 5-year averages.
- Balance sheet: borrowings and D/E latest, and the change in borrowings over 5 years.
- Cash: cash from operations latest, and whether it was positive in each of the last 5 years.
- Shareholding: promoter holding latest, change over the last 4 quarters, and pledge %.
- Valuation: P/E against the industry median from the scan cohort (existing `industry_pe` in `scanner/fundamentals.py`).

No sentence says good, bad, cheap, or expensive. Each sentence cites its table. The reading guide from the concall template applies here too: each indicator has a fixed "what it measures and how to read a rise or fall" note.

## Storage (decided 2026-11-09: Postgres)

Fundamentals are structured, period-keyed numbers, so they move to Postgres. MongoDB stays for unstructured records: announcements, concall text and summaries, order book items.

Why fundamentals ended up in Mongo: `scanner/docstore.py` defaults to Mongo when `DOCSTORE_BACKEND` is unset, and `scanner/fundamentals.py` wrote through that generic document store. Nobody chose Mongo for fundamentals. It was the default path.

Tables (new migration under `db/migrations/`, next free number). Row sets differ by company, so the schema is long format: one row per (company, section, period, label), not one column per label.

| Table | Key | Holds |
|---|---|---|
| `fund_line` | `symbol, section, period, label` | One value per row: `section` (quarters, profit_loss, balance_sheet, cash_flow, ratios, shareholding), `period` (e.g. `Mar 2025`, `TTM`, `Sep 2025`), `label` as shown on the page (footnote `+` stripped), `value` numeric, `raw` text as shown, `source` (`screener` or later `nse`) |
| `fund_row_map` | `section, label` | Maps a label to a canonical field (e.g. `Sales+` and `Revenue` to `sales`). A label with no mapping stays in `fund_line` and shows under its own name. Unmapped labels are listed, not dropped. |
| `fund_snapshot` | `symbol` | Key ratios (current), pledge %, promoter holding (latest), fetched_at |
| `fund_growth` | `symbol, horizon` | Compounded growth: 10y, 5y, 3y, TTM |

The UI renders each section from `fund_line` in the order the page uses. A company's template decides which rows appear. Screener-specific labels are handled by `fund_row_map`, not by code branches.

Migration path (needs your yes before the destructive step):
1. Add the tables and a writer in the collector. Write to Postgres alongside the Mongo write.
2. Point `enrich.py` and `scanner/conclude.py` reads at Postgres. Keep the same field names through a mapping so scoring output is unchanged.
3. After the acceptance checks pass, stop the Mongo write for fundamentals. Delete the old Mongo fundamentals documents only on your confirmation.

The screener fetch itself is unchanged.

## Verified row labels (from the saved pages)

- `#quarters`: Sales+, YoY Sales growth, Expenses+, Operating Profit, OPM %, Other Income+, Interest, Depreciation, Profit before tax, Tax %, Net Profit+, EPS in Rs, Raw PDF (a link row, not data; excluded)
- `#profit-loss`: Sales+, Sales growth, Expenses+, Operating Profit, OPM %, Other Income+, Interest, Depreciation, Profit before tax, Tax %, Net Profit+, EPS in Rs, Dividend Payout %
- `#balance-sheet`: Equity Capital, Reserves, Borrowings+, Other Liabilities+, Total Liabilities, Fixed Assets+, CWIP, Investments, Other Assets+, Total Assets
- `#cash-flow`: Cash from Operating Activity+, Cash from Investing Activity+, Cash from Financing Activity+, Net Cash Flow, Free Cash Flow, CFO/EBITDA. The cell text also carries a tooltip sentence. The parser must read only the label text, not the whole cell.
- `#ratios`: Debtor Days, Inventory Days, Days Payable, Cash Conversion Cycle, Working Capital Days, ROCE %
- `#shareholding`: Promoters+, FIIs+, DIIs+, Public+, No. of Shareholders. TCS also has **Government+**. Fredun and Sterlite do not. This is the template variation in practice.
- Column count: 13 to 14 per table in all three pages.

## Parser work

- Add `parse_cash_flow` and `parse_ratios`. Section ids are now confirmed.
- Strip the `+` footnote marker from labels. Read only the label text from the cell.
- Skip rows that are links or notes (`Raw PDF`).
- Extend `parse_page` to return all tables, not only the sales row. Existing fields and the scoring use stay the same, so the order-value factor is unaffected.
- Test: a saved page as the fixture (extend `tests/test_screener.py`; `tests/test_fundamentals.py` already covers `industry_pe`). Assert every expected row label and value type. A missing section must produce "not on page", not zero.

## Open risks

- **Source terms.** Full tables increase reliance on screener.in. `scanner/screener.py` already fetches this page each day, and its terms are unreviewed. You chose to leave it as is until the review. Extending it now would make the review more urgent.
- **Alternative source.** Quarterly results and shareholding are also filed on NSE and BSE as structured XBRL. That source would avoid the terms question for P&L and shareholding. Cash flow and the ratios table are not in those filings in the same form, so those would still need a derivation or a licensed source.
- **Label drift.** screener.in can rename or reorder rows. The parser keys on labels, so a change would drop a row silently. The test fixture catches this only after it happens.

## Acceptance

1. Each table matches the page's rows for a fixture company, in order.
2. Summary sentences are generated from the stored values only. A test checks that every number in a sentence appears in its source table.
3. A company with missing sections shows "not on page" for each one.
4. Existing scan and scoring outputs are unchanged on the test fixture.

## Scope

First version: all nine sections in the table above, plus the summary.

## Source variation across companies (decision input)

Every company does not use the same template, and this applies to NSE/BSE filings as well as screener.in:
- The same screener section gives different rows per company (TCS has Government shareholding; Fredun and Sterlite do not).
- Filings under SEBI LODR are in a standard XBRL format, but companies can add their own line items, and labels differ. Banks, NBFCs, and insurers use separate formats (for example, interest income rather than sales). I have not checked a bank's filing here; that needs a sample.
- So NSE/BSE data needs the same `fund_row_map` layer as screener, not fixed field names.

Recommendation: keep screener.in as the source for now, since you have saved pages for it and no fetch is needed. Add NSE/BSE later as a second source for checking figures, using the same tables. Screener's varying labels are handled the same way as a filing's would be.

## Decisions recorded (2026-11-09)

- Storage: Postgres for fundamentals; Mongo stays for announcements, concalls, order book. Approved.
- Mongo cutover approved, including deleting the old Mongo fundamentals documents. Deletion runs only after the acceptance checks pass.
- Scope: all nine sections plus the summary.
- Source: screener.in for now, with saved pages as input. NSE/BSE is a later check.

## Open questions

1. Banks, NBFCs, and insurers: do you hold any in the watchlist? If so, a saved page for one is needed to define their rows.
2. Confirm the summary wording: is the same rule set used for every company, including those with different templates?

## Approval (2026-11-10)
- Approved by the user. The six-lens review was not run before approval, by the user's decision. Status: approved, build not started.
