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
  eyeballed against actual filings. The category question is **closed, 2026-09-29:
  neither `Acquisition` nor `Diversification/Disinvestment` should be added.**
  Measured over the cached announcements:
  - `Acquisition` (2,602 rows) — **0%** of the metadata mentions capacity,
    tonnage, MW or a plant. Not because acquisitions are irrelevant to
    expansion, but because `attchmnt_text` is one-line boilerplate: 391,077
    rows, none empty, average 139 characters. Whatever an acquisition says
    about capacity is in the PDF, so this category cannot be decided from
    metadata at all and would need the filings stage pointed at it.
  - `Diversification/Disinvestment` (174 rows) — 0 mention capacity and **44
    mention divestment**, which is the *opposite* of expansion. Adding it
    would inject a contrary signal into the column.

  The 0% figure was checked before being believed: an empty-text bug would
  produce the same number, so the text column was counted first. It is
  populated and uninformative, which is a different and more useful answer
  than "no match".
- **Order-book *value* — BUILT AND MEASURED 2026-09-29 over 964 real PDFs.**
  The value is in the attached filing PDF, and SEBI LODR Schedule III Part A
  para 4 mandates a template whose field (g) is literally
  `Broad consideration or size of order(s)/contract(s) (in INR)`.
  `scanner/orderval.py` anchors on that label. **The measured yield is well
  below the pre-build prior** — the prior said 78% yield / 62.5% trusted
  anchor from a hand read of 40 filings; over the real corpus:

  | | order (222) | expansion (121) | guidance (621) | pooled (964) |
  |---|---|---|---|---|
  | trusted anchor | **36.5%** | 0.8% | 0.6% | **8.9%** |
  | `loose` (untrustworthy) | 11.3% | 59.5% | 51.7% | 43.4% |
  | `foreign-currency` | 33.8% | 2.5% | 18.2% | 19.8% |
  | `none` | 16.2% | 33.1% | 28.3% | 26.1% |
  | `withheld` | 2.3% | 4.1% | 1.1% | 1.8% |

  Only the **order** column is comparable to the prior, and 36.5% vs 62.5% is
  the honest gap. The 40-filing sample was hand-picked to look like order
  announcements; the 224 here come from a keyword classifier, so part of the
  gap is a wider, dirtier population and part is the parser. Broken down over
  the 222 order filings:
  - 36.5% anchored cleanly.
  - 26.6% carry **no value label at all** — a genuine floor for regex; this is
    the share that needs the LLM/Laya stage, not a better pattern.
  - 25.2% match the label but have no figure in the 240-char window. Not a
    window-width problem: the company answered the field with prose, a
    non-rupee unit (`300 MW at a tariff of Rs. 6.00 per kWh`), or a decline.
  - 11.7% use a label `_ANCHOR` does not cover — `worth` (9) is a real miss;
    `order book` (12) is correctly excluded, being cumulative, not one order.

  Three defects this measurement exposed, none of them known before:
  1. **`foreign-currency` swallows the rupee value the filing already states.**
     Step 3 of `parse_order_value` searches the *whole* document for a foreign
     marker and returns before the rupee fallback runs, so
     `USD 412.5 Million (~ ₹4,000 Crore)` reports "USD" with `rupees=None` and
     discards the company's own conversion sitting in the adjacent parens.
  2. **`_FOREIGN` fires on junk and on boilerplate.** 33 of 191 matches have no
     scale word at all (`$100`, `$5`, `$1`); `USD 30 billion` (21 docs) and
     `USD 32 billion` (17) are *market-size* sentences, the same class of error
     as WELCORP's Rs 45,000 cr — but labelled with false confidence.
  3. **`_SCALED` makes the rupee marker optional, so `loose` fabricates.** A
     bare `183 Million` became ₹18 cr for JSWINFRA and `1 billion` became
     ₹100 cr for ADANIPORTS — in both cases the mandated field said
     *Not Applicable* / *Not ascertainable*. Only 4 filings use that decline
     language and 2 were fabricated over, so this is small, but a fabricated
     number is worse than `none` because it looks like data.

  A **fourth** defect, worse than the other three and found the same way — by
  reading the first real report against the source PDFs rather than by running
  the tests: **`_best_order_for_symbol` ranked on `loose`.** It took the
  *largest* value for a symbol with no confidence gate at all, while
  `_orderbook_series` 240 lines away had been gating on the anchored tiers the
  whole time. Ten of twenty-four ranked rows came from `loose`, and they held
  the *top* of the ranking, because the enriched sheet sorts by significance
  descending and misreads are systematically larger than any single order:

  | symbol | `loose` read | what it actually was |
  |---|---|---|
  | PIRAMALFIN | ₹109,542 cr | post-merger net worth, from an NCLT appeal |
  | KPIL | ₹26,000 cr | cumulative order book, not one order |
  | CIPLA | ₹2,205 cr | unsecured creditors in a scheme of arrangement |
  | JSWINFRA | ₹97 cr | a GST demand the company is appealing |
  | ADANIPORTS | ₹100 cr | gross debt, off an investor deck |

  Four of six `TRANSFORMATIONAL` verdicts were wrong. A ranking key
  anti-correlated with correctness is the worst property such a key can have,
  and 433 passing tests could not have found it: `_best_order_for_symbol` had
  **zero** tests, and the defect lived in the output, not in a unit's contract.

  **All four are fixed, and the fix is measured.** `_SCALED` now captures the
  rupee marker instead of making it optional, and `_figure_candidates` takes
  `require_marker` — on for the unanchored path, off for the anchored one,
  because `(in INR)` in the mandated field label vouches for the unit and
  nothing vouches for a bare `1 billion` adrift in a deck. `_FOREIGN` requires
  a scale word. A new `_FX_INR_CONVERSION` keeps the issuer's own conversion,
  and `parse_order_value`'s steps are reordered so a bare foreign quote is the
  *last* resort rather than pre-empting the rupee fallback.
  `enrich._TRUSTED_TIERS` gates the ranking. 14 tests added (447 total); 3 of
  them were confirmed to fail when `_TRUSTED_TIERS` is widened to include
  `loose`, so they are load-bearing rather than decorative.

  `enrich.py --reparse` re-runs the regex over stored `docstore` text and
  downloads nothing, printing before/after tier counts. `orderval` was always
  pure and separable from fetching, but there had been no CLI path to exploit
  that: the only way to get a corrected parse onto stored rows was
  `--filings --refetch`, which re-downloads all 964 PDFs at a 1s courtesy
  sleep — sixteen minutes and ~1 GB of NSE's bandwidth to re-run a
  three-second regex.

  Measured over the same 964 documents after the fix: 160 changed,
  `foreign-currency` 191 → 80, `none` 252 → 287, `loose` 418 → 494,
  `anchor+scaled` unchanged at 86 — the anchored path was correct all along and
  the repairs land where they should, in the tiers nothing ranks on. The report
  fell from 24 ranked rows to **16, every one `anchor+scaled`**, and
  `TRANSFORMATIONAL` from 6 to 2. Six of the 16 were re-read against source
  text and all six answer the mandated field or an explicit "order value of"
  (WELENT ₹7,300 cr, ASTRAMICRO ₹2,205.23 cr, KPIL ₹4,000 cr, DATAPATTNS
  ₹585.76 cr, HFCL ₹2,666.09 cr, SAATVIKGL ₹1,041.63 cr). KPIL survives the
  cull on a *different* filing — a genuine ₹4,000 cr single order, not the
  cumulative book. The other ten were not read by hand at that point; all of
  them have been since — see the fifth block below, which supersedes these
  counts.

  A **fifth** round, 2026-09-29, and the same lesson twice more: *measure the
  output, not the code.* 466 then 470 tests passed throughout, and neither
  defect below was visible from a unit's contract.

  Four fixes, each measured on the 964 stored documents before being kept:

  1. **The window crossed a field boundary.** `_WINDOW` was a flat 240
     characters, so the anchored read could reach into the *next* mandated field
     and return paid-up capital (₹500 cr) or total debt (₹100 cr) as the order
     value — the `loose` fabrication again, but wearing the anchored tier's
     confidence, which is strictly worse. `_cut_at_next_field` ends the window
     at the following field instead. Chosen by measurement rather than by tuning
     a character count: over the 81 anchored order filings the word `whether`
     opens the next field in 57 of their windows and in **zero** does it precede
     the figure being read, so the cut discards only text that was never the
     answer. The enumerated markers add 15 and 4 more, also with 0 losses.
  2. **The FX conversion was on the wrong path.** `_FX_INR_CONVERSION` sat only
     in `parse_order_value`'s unanchored fallback, so the *anchored* path threw
     away `orders worth USD 85.86 million (approximately Rs. 819.94 crores)`.
     A rupee figure the company itself supplied, inside the field SEBI mandates,
     is as good as any direct answer. Moved into `_figure_candidates`, so both
     paths get it at the caller's confidence.
  3. **`unquantified`.** 25.2% of order filings match the label and hold no
     rupee figure in it — `190 MW ISTS connected wind solar`, `a tariff of
     Rs. 4.35 per unit`, `Not ascertainable`. That used to fall through to the
     largest-figure fallback, which answers a question the company did not
     answer; it is how JSWINFRA reported a GST demand and ADANIPORTS a debt
     slide. Once the mandated label is found, its answer is now the answer — the
     parse never falls back to scanning the rest of the document, because a
     document containing the field and no figure in it is telling you there is
     no figure, not inviting a search for the biggest number on the page.
     34 documents.
  4. **A `worth` label variant**, the one real miss the earlier measurement
     found (9 filings). Admitted only when a money token follows immediately and
     never after `net` or `book`, since `net worth` read as an order value is
     precisely the PIRAMALFIN misread.

  Fix 4 then **re-created the exact defect the confidence gate had just
  removed, at the trusted tier.** KPIL's `secured orders worth ₹13,219 crore so
  far in the current fiscal year (YTD FY27)` ranked as a single order at 56% of
  market cap. Caught by hand-verifying the regenerated report against stored
  source text — not by the suite, which was green. **Widening a pattern needs
  its own guard, measured on the same corpus.** Two guards resulted:

  - **`cumulative`** — a running total is not one order. An order book, a
     year-to-date inflow, a quarterly aggregate. The figure is real and worth
     keeping, being the best available read on order momentum, but never at a
     tier the ranking trusts. **15 documents, 12% of everything then trusted.**
     The framing usually *precedes* the number (`our order book stands at orders
     worth ₹26,000 crore`), which a window starting at the label cannot see, so
     `_read_window` takes a `context` argument — 160 characters of lookback.
     Verified not to over-fire on a delivery timeline: `₹640 crore, to be
     executed in FY27` stays trusted.
  - **`unquantified` for a classification legend** — a definition is never a
     disclosure. KPIL footnotes its own size buckets, `*Order Classification:
     Major indicates an order value estimated over ₹4,000 crore`, and that
     *threshold* ranked third in the report at 17% of market cap. It is the
     floor of a bucket the order falls into, so the true value is unstated and
     larger. Two conditions are required, because either alone is unsafe: a
     definition verb immediately before the label, **and** the answer opening
     with a bound rather than an amount. `Classification: Major order of Rs 500
     crore` keeps its figure, and so does `an order worth over Rs 500 crore`,
     where the bound is itself the disclosure. **1 document matched and 0
     correct readings were demoted** across the 107 anchored documents.

  Net: order-filing trusted yield **36.5% → 46.4%** against the 62.5%
  hand-measured prior, `anchor+scaled` 86 → **106** documents. Trusted readings
  deliberately *fell* from the intermediate 122 as the two guards landed — the
  useful direction, since each removal was a fabrication. The report holds
  **17 ranked rows, and all 17 were read against stored source text.** Every
  one is a genuine single award or one announcement of a batch from one
  counterparty. Two show the guards working on live data: MIDHANI takes its
  ₹158 cr order and not the ₹2,590 cr open position in the very next sentence,
  and WELENT takes its ₹7,300 cr project cost and not the ₹13,341 cr order book
  two sentences later.

  **Capacity context (2026-09-29).** Two new report columns, 88 in all:
  `order_capacity_plan` and `capacity_filing_date`. For each ranked order the
  label is `PLANNED` (a capacity filing on or before the order date), `CAPACITY_AFTER`
  (the first one came later -- the company saying the order outgrew its plant)
  or `UNPLANNED`. `UNPLANNED` means *no capacity expansion was filed*, not that
  no plan exists; the column points at the PDFs and does not conclude. It reads
  announcement *metadata* (28-month cache, no network) and not the fetched
  PDFs (6-month window), which would otherwise have fabricated `UNPLANNED` for
  a third of order winners. Result: UNPLANNED 11, PLANNED 5, CAPACITY_AFTER 1
  (STLTECH, verified). `capacity_change` is still empty -- it needs the
  never-run LLM stage.
  Verifying those labels exposed a defect in factor 4 itself: `margin expansion`
  matched the EXPANSION keyword (8 of 285 keyword hits) and gave AXISCADES a
  capacity plan. `_expansion_text` now strips margin/multiple-expansion phrases
  before matching, so a release that mentions both keeps its real capacity content.
  Categories `Acquisition` (2,602 rows) and `Diversification` (174) carry 0%
  capacity language, so no category widening is needed.

  Pooled tier counts after all of it (964 documents): `loose` 471, `none` 261,
  `anchor+scaled` 106, `foreign-currency` 60, `unquantified` 34, `withheld` 17,
  `cumulative` 15. Note that **pooled yield is not comparable to the prior** —
  the prior was measured on hand-picked order announcements, so the order column
  is the only honest comparison. Pooled trusted is 11%.

  Anchoring does work where it fires: the naive "largest money figure" gave
  WELCORP **Rs 45,000 cr** from a global-market-size sentence; the anchored
  parse gives Rs 4,000 cr, and the naive read survives only as `loose`.
  Prerequisites, both closed:
  1. ~~`factors.db` does not store `attchmntFile`~~ — schema 3 stores
     `seq_id`, `attchmnt_file` and `att_file_size`.
  2. ~~Indian digit grouping misses~~ — `Rs. 21,57,48,840/-` parses to
     ₹21.57 cr.

  A **third** prerequisite was missing and is now fixed (commit `c276562`): the
  trim in `factors.py` read NSE's `seq_id` as `seqId`, so the column was blank
  on all 391,074 cached rows and `--filings` dropped 100% of candidates while
  reporting that none carried a PDF URL — false, 162,387 did. A cache written
  before that commit needs `enrich.py --filings --refresh-factors` once; the
  upsert now backfills rather than `DO NOTHING`, so the repair is a re-run.
  Actual scope, from the completed run over the current 298 (superseding the
  earlier "274 PDFs across 42 symbols" estimate): **968 unique filings — 224
  order, 121 expansion, 623 guidance.** 964 fetched and text-extracted, 4 lost
  to `pypdf` `PdfReadError`, **0 skipped as oversized**. That last number is
  only meaningful because `att_file_size` now parses at all: NSE sends
  `"3.71 MB"`, `int(float(...))` raised on every row, so the `MAX_PDF_BYTES`
  guard had been silently dead. `pypdf` 6.19.0 is installed in `.venv`.
  `hasXbrl: True` on every announcement is announcement-type tagging only; the
  API exposes no XBRL payload and the order value is not in a tagged taxonomy.
- **`NEW_ATH_TODAY` bucket checked against a second source (2026-09-29) --
  closed.** All six names were compared with Screener's overview. Five of six
  scan LTPs equal Screener's `previous_close` to the paisa (QPOWER 1592.7,
  ENGINERSIN 313.9, WELCORP 2739.7, SHRIPISTON 4645.3, PGIL 1296.1);
  DYNAMATECH is 0.46% off (13200 vs 13139), consistent with BSE/NSE divergence
  in a thin name. ATH highs agree with Screener's 52-week high to rounding
  (ENGINERSIN 321.4/321, SHRIPISTON 4843/4843, PGIL 1357.9/1358, DYNAMATECH
  13500/13507, and APLAPOLLO 2301.4/2301 for an ATH dated months back). The two
  apparent gaps (QPOWER 1613 vs 1593.6, WELCORP 2870 vs 2838) are one session
  *later*: Screener answered intraday on 2026-09-29 against a 09-28 scan, and
  WELCORP was +4.6% that morning. The history cache confirms it -- QPOWER's
  newest cached candle is 09-25 with a highest-ever cached high of 1570, so
  the 09-28 print is a genuine new ATH. `5-15%` was not spot-checked.
  `output/ath_scan_2026-09-28.csv` predates an `as_of` column, so post-close
  finality is inferred from the exact close match rather than read from a field.
- **LTP cross-check is 3 symbols deep**, not 6: the Kite MCP session expired
  mid-session, so HDFCBANK/BSE/SWIGGY were not independently confirmed
  against a second broker. Re-login to Kite MCP and re-check if that matters.
  (The six `NEW_ATH_TODAY` names were since confirmed against Screener --
  see above -- so this now concerns the wider universe only.)
- **Sustained rate limits unmeasured beyond 30 requests.** 7.2 req/sec held
  over a short burst, but a per-30-minute account cap (if any) would only
  show up during a full run. The client honours `Retry-After` on 429 and
  backs off exponentially, so the failure mode is slowness, not data loss.

## Known limitations / deliberate design choices

- **`NEW_ATH_TODAY` means "printed a new ATH today", not "closed at it".**
  `classify_bucket` returns it *before* the `--max-dist` check, so a stock
  that spiked to a new high and faded is still in it: DYNAMATECH sits there
  at 2.22% while DIVISLAB at 1.95% sits in `0-5%`. That is deliberate, and
  the distance column shows the fade. Two consequences nobody has
  exercised: `NEW_ATH_TODAY` bypasses `--max-dist`, and a day-one listing is
  vacuously a new ATH (`is_new_ath_today` is true with no prior candles), so
  `recent_ipo` is the guard to read alongside it.
- **A mixed-currency order value keeps only its rupee leg.** LLOYDSENGG's
  mandated field reads `₹613 Crore + €18 Million`, and the parse reports
  ₹613 cr — understated by roughly ₹170 cr. Found by reading all 17 ranked
  rows against source text (2026-09-29). This is a *partial* read rather than
  a fabrication, so it errs toward under-ranking a real win, which is the safe
  direction; summing the legs would need a EUR rate this project does not
  carry, and the issuer offered no conversion of its own. Left alone
  deliberately. One row of 17.
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

## Docker, manual trigger, cross-check, portfolio (added 2026-09-29)

**Run it:** `./start.ps1` (scan -> enrich -> crosscheck -> portfolio), then
`./stop.ps1`. No scheduler; the 4 PM IST run was replaced by this manual
trigger on request. Flags: `-Symbols`, `-WithLlm`, `-WithLaya`, `-SkipEnrich`,
`-SkipCrosscheck`, `-SkipPortfolio`, `-Rebuild`. Credentials reach containers
only at runtime through compose `env_file: .env` (scanner, enrich, portfolio);
crosscheck, laya and llm get none. The scripts never open `.env`.

**Images (one per entrypoint):** `scanner`, `enrich`, `crosscheck`, `portfolio`
(light, non-root, `requirements.txt` only), plus optional `laya` (profile
`laya`) and `llm` (Ollama, profile `llm`). Components talk only through the
bind-mounted `data/`, `output/`, `logs/` (SQLite `history.db`/`factors.db`,
TinyDB `documents.json`, CSVs). The one container-to-container call is
enrich -> llm (`--llm-url http://llm:11434`). Laya and llm are published on
127.0.0.1 only. PowerShell 5.1 gotcha: judge docker success by `$LASTEXITCODE`,
not by stderr (`2>&1` plus `$ErrorActionPreference='Stop'` turns docker's
progress output into terminating errors).

**Market data stays Upstox.** NSE is only an independent check
(`crosscheck.py`, bhavcopy `sec_bhavdata_full_DDMMYYYY.csv`); Screener is the
documented manual fallback and is not implemented as a source. Verified on the
2026-09-28 scan: LTP 298/298 and ATH 298/298 agree with NSE, exit 0. Bhavcopy
facts that bit us: prices are raw (unadjusted), so the ATH window stops at a
day-to-day close ratio outside 0.6-1.6 (a split/bonus); `CLOSE_PRICE` is a
30-minute VWAP, so an LTP matching either close or `LAST_PRICE` is OK; series
`EQ` and `BE` are both accepted. Its first version passed tests while parsing
zero rows of the real file, which is why `tests/test_crosscheck_nse.py` uses a
verbatim padded real layout.

**Rate limits (Upstox docs: 50/s, 500/min, 2000/30 min).** `scanner/upstox.py`
enforces 80% of each: 40/s, 400/min, 1600/30 min, with 429 escalation and
`client.stats()`. A cold scan is ~2,252 requests (~42 min); an incremental one
~752 (~14 min). **Measured 2026-09-29 (cold cache, isolated data dir, Docker):**
1,969 requests, **0 HTTP 429s**, 1,664 s spent throttling by our own limiter, 0 skipped,
~30 min wall clock; the scan now prints these stats. Its 290 matches had `ath_high`
identical to the incremental run on all 290 (2 bucket changes = intraday LTP moved
between runs 30 min apart). Known small defects, not fixed: the limiter sleeps while
holding its lock, and `float(Retry-After)` fails on an HTTP-date value.

**Portfolio.** `portfolio.py` joins Kite holdings with the scan/enrichment
output (read-only). Live Kite login is interactive: supply `KITE_ACCESS_TOKEN`
or a `data/holdings.json`; exit 2 means no holdings source (start.ps1 treats it
as a warning).

**Seasonal forecast.** Runs from 13 months (`MIN_MONTHS_SEASONAL_UNVALIDATED`)
and is labelled "point forecast only (N points, need 25 for validated band)".
25 (`MIN_MONTHS`) is required only for the backtest-validated error band.

**Not wired / not done, by decision:**
- Laya is installed in the venv and containerised but is a classifier
  (`/v1/systemone`), not compatible with `enrich --llm`; it is not used in
  ranking and is unmeasured. First `-WithLaya` start downloads ~808 MB.
- `--llm` (which would fill `capacity_change`) and Neo4j need the Ollama
  profile (`-WithLlm`, multi-GB model). Neo4j itself is not built.
- TimesFM lives only in the separate `enrich-timesfm` image (see the section below).
- No scheduled task was created.

## TimesFM image and per-stock conclusions (added 2026-09-29)

Two more images, both optional compose profiles, both loopback-only, neither
gets `.env`:

- **`enrich-timesfm`** (`docker/timesfm/Dockerfile`, profile `timesfm`,
  `./start.ps1 -WithTimesfm`): CPU torch + `timesfm[torch]==3.0.2`, runs
  `enrich.py --report --timesfm`. Re-writes `output/ath_enriched_<date>.csv`
  with the TimesFM forecast columns. Checkpoint downloads on first run into the
  shared `huggingface_cache` volume. Kept out of the light `enrich` image so the
  everyday run does not carry ~2 GB of torch.
- **`vllm`** (`docker/vllm/Dockerfile`, profile `vllm`,
  `./start.ps1 -WithConclusions`): `vllm/vllm-openai:v0.30.0` serving
  `Qwen/Qwen3-4B-Instruct-2507` (Apache-2.0, ungated) as `qwen3-4b` on
  `127.0.0.1:8001` (`http://vllm:8000` inside compose). Needs an NVIDIA GPU and
  the NVIDIA container runtime. Tuning is by ENV in the Dockerfile
  (`MAX_MODEL_LEN`, `GPU_MEMORY_UTILIZATION`, `QUANTIZATION`, `KV_CACHE_DTYPE`,
  `EXTRA_ARGS`). **8 GB card note:** bf16 weights are ~8 GB and do not fit next
  to the desktop, so the defaults are `QUANTIZATION=mxfp4` (4-bit weights),
  `KV_CACHE_DTYPE=fp8` and `GPU_MEMORY_UTILIZATION=0.56` (~4.5 GB: weights
  2.8 GiB + KV 0.7 GiB). v0.30.0 with online FP8 weights fails on this card
  ("Available KV cache memory: -1.7 GiB"); FP8 weights only worked on the older
  v0.19.1 image. Set both to empty on a bigger card. Structured output uses
  xgrammar with `disable_any_whitespace` (see serve.sh): without it the 4-bit
  model ran into endless whitespace after the conclusion and ~70% of stocks
  failed as "not JSON".
- **Model bench**: `python bench_models.py` runs the fixed acceptance test in
  `scanner/modelcheck.py` (tests: `tests/test_modelcheck.py`) on each candidate,
  one throw-away vLLM container at a time (`ath-bench`, port 8003), same 4.5 GB
  budget and FP8 KV. Fixed budgets: 600 s to healthy, 420 s for the first 40
  stocks; ceilings on the share of stocks: 0% failed, 10% speculative, 10% empty
  (or missing the side its stance needs), 5% truncated, 15% unverified numbers.
  Results in `output/model_bench.csv`; failed startups keep `logs/bench_<key>.log`.
  AirLLM was tried and dropped (see below).
- **`conclude`** is the client, not a third image: `conclude.py` ships in the
  existing `ath-enrich` image and the compose service overrides the entrypoint.

**What `conclude.py` does.** For each stock in the newest
`ath_enriched_*.csv` it builds a flat `group.field` fact sheet (price/ATH
position and trend, fundamentals, order book, corporate signals, forecast
columns, plus up to 5 recent filings and any stored LLM extractions from the
TinyDB store). The stance (`CONSTRUCTIVE`/`MIXED`/`CAUTIOUS`) is **not** chosen
by the model: a fixed scorecard (`scorecard()` in `scanner/conclude.py`) sums six
pillars (trend/distance, growth, quality, valuation, forecast, orders), each
clipped to [-2,+2]; missing data scores 0 and fewer than 3 pillars with data is
MIXED; total >=3 is CONSTRUCTIVE, <=-2 CAUTIOUS. The model writes a
three-sentence conclusion plus positives and concerns citing fact-sheet keys and
is told the stance. Data gaps are computed, not asked of the model (the 4-bit
model invented them). Output: `output/ath_conclusions_<date>.csv` and a
`conclusions` collection in `data/documents.json` keyed by (symbol, as_of).
Re-runs skip stocks whose fact sheet, prompt version and model are unchanged
(`--force` overrides). Exit 1 server unreachable, 2 some failed.

**The model is not trusted.** Guards in `scanner/conclude.py`: an evidence key
that is not a real field of that stock's sheet drops the point
(`ungrounded_points`); every number in the prose is looked up in the sheet (sign
and ticker digits ignored) and unmatched ones are listed in `unverified_numbers`
(a smell test, not a proof); words like undervalued/overvalued/upside/opportunity
are listed in `speculative_phrases`. An answer that is speculative or cut off gets
one corrective retry naming the problem; the cleaner answer is kept. The
conclusion never changes the ranking and is not investment advice.

**Measured 2026-09-29 (RTX 4060 8 GB, 290 stocks, 8 workers).**
- Pinned `vllm/vllm-openai:v0.30.0` pulls and serves fine now; the earlier failure
  was low disk, not the image. With MXFP4 + FP8 KV: weights 2.77 GiB, KV cache
  2.28 GiB (37,246 tokens, 9x concurrency) at `GPU_MEMORY_UTILIZATION=0.80`
  (0.90 fails: the desktop holds ~0.9 GB). Healthy in ~2 min once cached.
- Throughput: all 290 in about 10 minutes at 8 workers (about 5-12 s per stock).
- Stance (scorecard): MIXED 140, CONSTRUCTIVE 107, CAUTIOUS 43. The positive skew
  is expected: the universe is ATH-filtered, i.e. already momentum-selected. The
  thresholds are a policy choice, not a finding. The earlier model-chosen stance
  gave CAUTIOUS 216 / MIXED 57 / CONSTRUCTIVE 15 and was dropped.
- Failures: 0 of 290 after the whitespace fix (207 of 300 before it).
- Guard counts on the final run: 25 stocks with an unverified number (37 before
  the corrective retry); 129 with speculative wording (178 before); 4
  conclusions cut off (63 before); 93 with no positives and 80 with no concerns
  because the 4-bit model returned an empty list. Earlier "45 flagged numbers"
  were guard false positives (31 sign flips, 1 ticker digit), 13 ratios the model
  computed itself, and 2 genuinely unsupported; none was a network or
  unreported-filing problem.
- Model quality caveat (4-bit Phi-4-mini MXFP4, the earlier default): it called a
  fall from the high "undervaluation" in a large share of stocks despite the
  prompt rule (129 of 290 speculative, 83 empty or stance-inconsistent). It was
  replaced by Qwen3-4B-Instruct-2507, below.
- **Qwen3-4B (current default), full run, 290 stocks (~10 min, 4 workers):** 0
  failed, 4 speculative, 10 unverified numbers, 0 truncated, 7 empty or
  stance-inconsistent (many stocks have no positives, almost all CAUTIOUS, which
  is consistent), stance MIXED 140 / CONSTRUCTIVE 107 / CAUTIOUS 43.
- **Disk:** the `kite-ath-scanner-vllm` image is the upstream vLLM image plus two
  thin layers, so the ~30.7 GB is paid once (the two tags share layers); there is
  no smaller vLLM image with CUDA. Trial models cache in the `huggingface_vllm`
  volume (Qwen3-4B ~8 GB, LFM2.5 ~2.4 GB kept); `docker builder prune -a` frees
  the build cache (was 22 GB).
- **Model comparison (`bench_models.py`, first 40 stocks, RTX 4060 8 GB, MXFP4/4-bit
  + FP8 KV in ~4.5 GB):**

  | model | result | run / startup | notes |
  |---|---|---|---|
  | Qwen3-4B-Instruct-2507 MXFP4 | **PASS** | 136 s / 157 s | 0 spec, 0 empty, 3 unverified; weights 2.81 GiB, KV 0.72 GiB |
  | LFM2.5-1.2B-Thinking (bf16, FP8 KV worked) | **PASS** | 196 s / 262 s | 0 spec, 0 empty, 1 unverified; weights 2.2 GiB, KV 1.85 GiB; slower and less proven |
  | Qwen3-1.7B GPTQ-Int4 | FAIL | 328 s / 233 s | 26 of 40 speculative (65%) |
  | Phi-4-mini GPTQ and AWQ (compressed-tensors; retried with auto-detect) | FAIL | | weights 2.73 GiB, then "Available KV cache memory: -0.72 GiB": does not fit 4.5 GB (200k-vocab logits buffers; it needed 0.80 utilisation, ~6.4 GB, earlier) |
  | DeepSeek-R1-Distill-Qwen-7B AWQ | FAIL | | engine did not start inside the 4.5 GB budget (expected: ~5.5 GB of weights) |

  Verdict: keep Qwen3-4B (fastest, passes, best-documented). LFM2.5-1.2B is the
  fallback if more headroom is needed.
- AirLLM (dropped, `docker/airllm` removed): `Qwen/Qwen1.5-MoE-A2.7B-Chat` 4-bit
  fit in 1.56 GB VRAM but decoded at ~13 s per token, i.e. ~2 weeks for 290
  stocks against ~10 minutes on vLLM. DeepSeekMoE-16B and Qwen1.5-MoE do not fit
  vLLM's 4.5 GB at 4-bit. AirLLM 4.0.0 also needs transformers 4.x for Qwen2-MoE.
- Docker daemon: no restarts since the disk was cleaned up (backend up, `ath-vllm`
  RestartCount 0). The earlier restarts coincided with the low-disk period.
- TimesFM stage: 5.6 min for 290 stocks in the `enrich-timesfm` image; loads
  `google/timesfm-2.5-200m-pytorch`. Run it before `conclude` so the forecast
  columns are in the fact sheet (`start.ps1` does).

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
# pytest is NOT installed in .venv -- use unittest, which needs no dependency
.venv\Scripts\python.exe -m unittest discover -s tests -t . -q    # 621 tests, 2 skipped
```

Set `PYTHONIOENCODING=utf-8` for anything that prints a rupee sign, and
`PYTHONPATH=.` for scratch scripts that import `scanner`.

**Heredoc escape gotcha.** Inside a `<<'PYEOF'` heredoc feeding Python, a
`\b` in a non-raw string literal becomes a literal *backspace* (`\x08`) and
lands silently in the written file -- a regex word boundary that never
matches. It cost a guard that silently did not fire (`_LEGEND_BOUND`,
diagnosed by printing `repr(pattern)`). Avoid escape sequences in transit;
build them with `chr(92) + "b"`. Also: `/tmp` in Git Bash is invisible to
Windows Python, and a `.venv` interpreter must be named explicitly.

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

- Cron/scheduled 4 PM IST run on trading days. Unblocked by the ~1-year token,
  but deliberately replaced by the manual `start.ps1`/`stop.ps1` for now.
- `scanner/ath.py` remains import-clean (no I/O, no broker dependency) and
  can be reused as-is as a pure ATH/bucketing library.
