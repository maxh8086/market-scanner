# Upstox as secondary fundamentals source

Status: approved 2026-11-10 (decisions below). Not built. Next step: EGM brainstorm review, then the build plan.
Related: `docs/designs/fundamentals-tables.md`, `scanner/fund_derive.py`, `scripts/fetch_upstox_sector.py`.

## Rule

1. Screener.in is the primary source for every fundamentals value it provides.
2. Upstox fills a field only when Screener has no value for that symbol and that field.
3. Upstox never overwrites a Screener value. When both sources have a value for the same field, both are stored and the reader sees both. No value is averaged or picked silently.
4. Every stored value records its source: `screener` or `upstox`.

## Why the rule is needed

- `fund_derive.py` currently derives market cap, P/E, book value, ROE, ROCE, dividend yield, EPS CAGR and PEG from Screener tables, so Upstox adds nothing to those today.
- Upstox P/E uses a basis we have not confirmed. TCS and Reliance P/E values do not match price / latest annual EPS. Upstox P/E must never be written into a column that holds Screener P/E.
- Upstox sector benchmark values (`sector_value`) include negative numbers for IT services. They are not used until checked.

## Candidate fields that Screener does not give us

| Field | Upstox endpoint | Use |
|---|---|---|
| ROA | `/v2/fundamentals/{isin}/key-ratios` (`name = ROA`) | New stored field, source `upstox` |
| EV/EBITDA | same, `name = EV/EBITDA` | New stored field, source `upstox` |
| Quick ratio | same, `name = Quick Ratio` | New stored field, source `upstox` |
| Last price | `/v2/market-quote/quotes` (`last_price`) | Only if the Screener price is missing |
| Company description | `/v2/fundamentals/{isin}/profile` (`company_profile`) | Display only |
| Corporate actions | `/v2/fundamentals/{isin}/corporate-actions` | Dividend history, when needed |

Not used for now: sector benchmark values (unverified), competitors, and Upstox P/E (basis unknown).

## Not covered by Upstox

Face value, share count and borrowings have no Upstox source. Screener stays the only source for them. Share count can be estimated as PAT / EPS, which is an estimate and must be labelled as one.

## Decisions

Approved 2026-11-10.

1. New stored fields are ROA, EV/EBITDA and Quick Ratio, sourced from Upstox. Last price, company description and corporate actions are not built now.
2. Upstox P/E is not used until its basis is known. Screener P/E is the only P/E.
3. The fallback applies to any field Upstox can supply, not only the table above. Exclusions still apply: Upstox P/E, and the unverified sector benchmark values. Face value, share count and borrowings stay empty when Screener is missing them, because Upstox has no source for them.

## Verification

- A saved Screener page and a saved Upstox response for the same symbol are used as fixtures.
- A test asserts that a Screener value is never replaced by an Upstox value.
- A test asserts that a symbol missing from Screener still gets the Upstox fields.
