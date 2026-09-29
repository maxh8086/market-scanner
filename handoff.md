# Handoff — ATH Scanner

Status: **running end-to-end against live market data.** The data source is
**Upstox** (not Kite); portfolio stays on Kite. A 6-symbol live run completed
with 0 skipped, and the corporate-action, instrument-resolution and
history-depth questions that blocked earlier sessions are all closed.

## Architecture (settled 2026-09-28)

**Upstox for market data, Kite for portfolio.** Upstox issues a long-lived
(~1 year) analytics token, so there is no daily interactive login — which is
what makes the deferred 4 PM IST cron actually feasible. That token is
data-only and cannot place orders. The Kite side is read through the Kite MCP
connector, not by this script.

Credentials live in `.env` (gitignored) as `UPSTOX_ANALYTICS_ACCESS_TOKEN`.
**Not** in `.env.example` — that is the committed template and holds
placeholders only.

## What's done

- Full project per the original spec: `ath_scan.py` CLI + `scanner/` package.
- `tests/test_ath.py` — 26 unit tests, all passing.
- `scanner/upstox.py` — the market-data provider. Returns Kite-shaped candle
  rows so `scanner/history.py` stayed provider-agnostic: it now accepts any
  object with `daily_candles(key, from_date, to_date)`.
- 750 constituents load clean (755 raw − 5 `DUMMY*` rows).
- **FULL 750-SYMBOL RUN COMPLETED 2026-09-28, 4.45 minutes.**
  750/750 resolved, **0 skipped**, 298 matches, 13 columns, zero nulls.
  Buckets: `NEW_ATH_TODAY` 6 · `0-5%` 19 · `5-15%` 122 · `15-26%` 151.
  Distance ranges are contiguous and non-overlapping (0-5% spans 1.38–4.78,
  5-15% spans 5.09–15.00, 15-26% spans 15.07–25.95), so bucketing is sound
  on real data. Oldest `ath_date` 2008-01-07 (6,839 days below its peak);
  22 rows flagged `recent_ipo`, minimum `listed_days` 283.
- **CORPORATE-EVENT FACTORS ADDED AND VERIFIED 2026-09-28.** `scanner/factors.py`
  enriches the 298 matches with 5 more columns (18 total): `bonus_issue`,
  `demerger`, `orderbook_signal`, `expansion_signal`, `factors_matched`.
  104 / 298 carry at least one factor (83 one, 20 two, 1 three — STLTECH).
  Coverage: bonus 13 · demerger 21 · orderbook 42 · expansion 50.
  Source is NSE's public JSON (no auth), joined on ISIN: one
  `corporates-corporateActions` request for 24 months back plus 12 forward
  (4,036 rows) and 13 monthly `corporate-announcements` requests for 12 months
  (165,881 rows, ~70s). Cached in `data/factors.db`, schema 2.

- **MOVING-AVERAGE TREND ADDED 2026-09-28.** `scanner/indicators.py` (pure, no
  I/O, like `scanner/ath.py`) adds 5 columns → **23 total**: `ema50`, `sma200`,
  `above_ema50`, `above_sma200`, `trend`. Costs **zero extra API requests** —
  the 2.6M cached candles already hold everything. Today's live LTP is appended
  as today's close, since `history.py` never caches the forming candle.
  Verified bit-exact against pandas `ewm(span=50, adjust=False)` / `rolling(200)`
  on RELIANCE/INFY/TCS/LT/BEL (diff 0.00e+00). Distribution over the 298:
  UPTREND 124 · ABOVE_200_ONLY 105 · BELOW_BOTH 61 · ABOVE_50_ONLY 3 ·
  INSUFFICIENT_HISTORY 5. **39 rows are UPTREND *and* carry ≥1 corporate factor**
  — that intersection is the actual shortlist.
  Structural sanity: all `NEW_ATH_TODAY` and all `0-5%` are UPTREND (a stock at
  its ATH cannot sit below its averages), and `BELOW_BOTH` concentrates in
  `15-26%`. EMA is SMA-seeded on the oldest 50 and walked forward, so with years
  of candles the seed is irrelevant (verified <0.001 divergence).
- **`trend` uses `INSUFFICIENT_HISTORY`, never `"n/a"`.** `"n/a"` is in pandas'
  default `na_values`, so a CSV round-trip silently turned the label into NaN
  and erased the difference between "recent IPO, no 200-SMA" and "column
  absent". Regression-tested.
- **The Excel writer now survives a locked workbook.** A full run spends
  minutes fetching before it reaches the writer; a workbook open in Excel used
  to raise `PermissionError` and destroy that work. It now falls back to
  `ath_scan_<date>_<HHMMSS>.xlsx` and says so.

## Questions closed this session

1. **Split/bonus adjustment — ADJUSTED.** Verified on two stocks and two
   separate actions. RELIANCE (1:1, ex-date 2024-10-28): 2024-10-25 high
   returns 1,344.35 against an actual traded ~₹2,690, continuous across the
   ex-date — and **identical to Kite's value to the paise**, so this is
   cross-broker agreement rather than one source's word. HDFCBANK (1:1,
   2025) independently confirms it: `ath_high` 1,020.50, on the post-bonus
   scale, not the ~₹2,000 pre-bonus era. Live LTPs also matched Kite exactly
   on RELIANCE/INFY/TCS.
2. **Instrument resolution — retired, not just answered.** Upstox keys on
   `NSE_EQ|{ISIN}` and the constituents CSV already carries `ISIN Code`, so
   resolution is string construction. No instrument dump, no numeric token,
   no tradingsymbol matching. The old open question — whether Kite's public
   `GET /instruments` CSV exposes `isin` — no longer affects anything.
3. **First-run timing — ~5 minutes, measured.** Upstox serves ~a decade of
   daily candles per request, so a full 26-year history is **3 requests**
   (RELIANCE: 6,648 candles in 3 calls, 0.4s). Sustained 7.2 req/sec over 30
   sequential requests with no 429s. Projected 2,250-request full run: 5.2
   min, versus the 10–15 min the Kite design predicted.
4. **History depth.** Daily candles begin **2000-01-03** — exactly the
   spec's floor, so nothing is being missed. Requests are capped near a
   decade: 3,653 days succeeds, 2000→2026 is rejected `UDAPI1148 Invalid
   date range`. `MAX_DAYS_PER_CALL` is 3,650.
5. **Quote-response key trap — handled.** The OHLC endpoint keys its
   response `EXCHANGE:TRADINGSYMBOL`, *not* by the `instrument_key` sent;
   the sent key comes back inside the payload as `instrument_token`. Mapping
   on the response key alone would have matched nothing and reported a
   silent zero-result scan. 200/200 mapped correctly via `instrument_token`.

## Factor design notes (read before touching `scanner/factors.py`)

- **NSE's announcement `desc` is a controlled vocabulary** — 132 fixed
  dropdown values over 165,881 filings, not free text. Classifiers match the
  exact category for high-confidence signals and fall back to keywords over
  `attchmntText` only, labelled `text-match only` in the output so the two
  tiers stay distinguishable. Never keyword-match against `desc`: "WIN" hits
  `Trading Window`, bare "CAPACITY" hits "in his capacity as".
- **`Action(s) taken or orders passed` (1,053 filings) and `Action(s)
  initiated or orders passed` (568) are regulatory enforcement**, the opposite
  of an order win. They are excluded explicitly in `ORDERBOOK_DESC_EXCLUDE`.
- **`Scheme of Arrangement` is not a confirmed demerger** — it also covers
  mergers, amalgamations and capital reductions. Reported as
  `Scheme of Arrangement <date> (demerger unconfirmed)`. Of 21 demerger hits
  in the output, 15 are this weaker tier; only 1 is an executed `Demerger ex`.
- **Dates are stored ISO in `factors.db`.** NSE's wire format
  (`08-Oct-2024`) breaks SQL `>=` range filters lexicographically and silently
  returns zero rows. `PRAGMA user_version` gates a drop-and-refetch if schema-1
  rows are ever seen.
- **Trust order:** bonus and demerger come from the structured CA feed and are
  high-confidence. Orderbook is good where category-backed (30 of 42 in the
  current output). Expansion is the weakest — 38 of 50 category-backed, and the
  attachment snippets it keyword-matches average only 141 characters.
- **Forward visibility is ~1 month, not 12.** `DEMERGER_FORWARD_MONTHS` is 12
  but NSE's furthest published ex-date is about a month out, so "about to
  happen" means weeks. The 2 upcoming demergers in the whole feed (KMSUGAR,
  VERANDA) are **not** Nifty Total Market constituents, which is why the output
  shows 0 upcoming — correctly, not as a missed match.

## Still open

- **Expansion (factor 4) is the least trustworthy column** and has not been
  eyeballed against actual filings. `Capacity addition` and `Commencement of
  commercial production/operations` are the only two categories backing it;
  worth checking whether `Acquisition` (1,213 filings) or
  `Diversification/Disinvestment` (72) should count as expansion.
- **Order-book *value* — MEASURED AS FEASIBLE 2026-09-28, not yet built.**
  The earlier claim that "no free API publishes one" was too pessimistic. The
  value is in the attached filing PDF, and SEBI LODR Schedule III Part A para 4
  mandates a template whose field (g) is literally
  `Broad consideration or size of order(s)/contract(s) (in INR)`. Anchoring on
  that label and parsing the number after it, measured over 40 real filings:
  **78% yield a value, 62.5% from the trusted anchor**, 1 explicitly withheld
  by the company, 20% need AI or manual reading. Anchoring matters: the naive
  "largest money figure in the document" gave WELCORP **Rs 45,000 cr** (it had
  picked up a global-market-size sentence); the anchored parse gives Rs 4,000 cr.
  Two gaps to close before building:
  1. `factors.db` **does not store `attchmntFile`** (the PDF URL) or
     `attFileSize`. Needs schema 3. NSE returns both.
  2. Indian digit grouping (`Rs. 21,57,48,840/-`) has no scale word, so a
     scale-word-only regex misses it — that alone made RAILTEL a false negative.
  Scope for the current 298: **274 PDFs across 42 symbols** (plus 176 expansion
  PDFs across 60), 1–4 pages each, all digital text — `pypdf` extracted 40/40
  with zero errors. `pypdf` 6.19.0 is now installed in `.venv`.
  `hasXbrl: True` on every announcement is announcement-type tagging only; the
  API exposes no XBRL payload and the order value is not in a tagged taxonomy.
- **`NEW_ATH_TODAY` and `5-15%` buckets are now populated but not yet
  eyeballed against a chart.** The full run finally put names in them
  (QPOWER 0.06%, DYNAMATIC 2.22%, and 122 names in `5-15%`), so this is
  actionable for the first time — it is the last unverified path through
  `scanner/ath.py` on real data.
- **LTP cross-check is 3 symbols deep**, not 6: the Kite MCP session expired
  mid-session, so HDFCBANK/BSE/SWIGGY were not independently confirmed
  against a second broker. Re-login to Kite MCP and re-check if that matters.
- **Sustained rate limits unmeasured beyond 30 requests.** 7.2 req/sec held
  over a short burst, but a per-30-minute account cap (if any) would only
  show up during a full run. The client honours `Retry-After` on 429 and
  backs off exponentially, so the failure mode is slowness, not data loss.

## Known limitations / deliberate design choices

- **`--symbols` only works for index members now.** A ticker outside the
  constituents CSV has no ISIN, so no instrument key can be built; it is
  skipped with "no ISIN available". Previously Kite's dump could resolve such
  a symbol by name. If this matters, add Upstox's instrument master as a
  tradingsymbol→key fallback.
- **Today's candle is never cached.** History is fetched only through
  *yesterday*; today's high/LTP come from the live quote and are merged
  in-memory by `scanner/ath.py::scan_symbol`. Avoids double-counting a
  forming intraday candle; the DB catches up on tomorrow's run.
- **`--max-dist` changes bucket boundaries dynamically**, not just the
  cutoff — `--max-dist 10` yields `0-5%`/`5-10%`, not a nonsensical `15-26%`.
  Covered by `test_custom_max_dist_below_15`.
- **`recent_ipo`** is a flat 365 calendar days from the earliest cached
  candle, not a listed-trading-days count.
- **`scanner/auth.py` and `scanner/instruments.py` are no longer used by the
  scan.** Retained for the Kite portfolio side. Don't delete them assuming
  they're dead — but don't expect the scan to touch them either.

## Possible improvement spotted, not implemented

Upstox supports `weeks` as a candle unit, and a weekly candle's high is the
max of its daily highs — so **weekly data yields a bit-identical `ath_high`
at ~1/5 the payload**. Verified: RELIANCE's max high over 2016–2026 is
1,611.80 from both daily (2,478 candles) and weekly (522 candles). The cost
is `ath_date` precision, which degrades from the exact day to the week. Worth
it only if payload size ever becomes the bottleneck; request count, not
bytes, is what the 5-minute run time is bound by.

## How to pick this up

**Use the project venv (`.venv`, Python 3.13). Do not `pip install` into a
system Python.** On the dev machine a bare `python` on PATH is 3.10, which
is not the pinned interpreter.

```bash
py -3.13 -m venv .venv                                               # one-time
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt      # one-time
cp .env.example .env
# set UPSTOX_ANALYTICS_ACCESS_TOKEN in .env  (NOT in .env.example)
.venv\Scripts\python.exe ath_scan.py --symbols RELIANCE,INFY,TCS --verbose
```

Smoke-check the environment *before* a full scan -- a full run spends
~5 minutes fetching and enriching before it ever reaches the Excel writer,
so an environment gap otherwise costs you that time twice:

```bash
.venv\Scripts\python.exe ath_scan.py --help
.venv\Scripts\python.exe -m pytest tests -q          # 49 tests
```

### Environment history (resolved 2026-09-28)

Deps were previously split across three system Pythons, which produced two
distinct failures:

| Interpreter | pandas | openpyxl | pytest | Symptom |
|---|---|---|---|---|
| 3.10 (bare `python`) | yes | yes | **no** | `python -m pytest tests` -> `No module named pytest` |
| 3.13 | yes | **was missing** | yes | full scan died at the Excel write step *after* ~5 min of work |
| 3.11 | no | no | no | unusable |

`.venv` on Python 3.13.7 now holds all of them. `pytest` is declared in
`requirements-dev.txt` (it was previously undeclared despite 49 tests
depending on a runner); `requirements.lock.txt` is a `pip freeze` of the
verified install.

Note that `requirements.txt` pins only `pandas>=2.0.0`, so a fresh install
now resolves **pandas 3.0.6** (a major-version bump from the 2.x the
project originally ran on). The suite and the Excel writer were both
verified against 3.0.6; add an upper bound if that ever needs freezing.

## Not done (explicitly deferred per spec's "Later" section)

- Cron/scheduled 4 PM IST run on trading days. Now genuinely unblocked: the
  ~1-year token means no interactive login stands in the way.
- `scanner/ath.py` remains import-clean (no I/O, no broker dependency) and
  can be reused as-is as a pure ATH/bucketing library.
