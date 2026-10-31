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

## Priority next (recorded 2026-10-30, before the ruflo cleanup was finished)

1. **Ruflo cleanup in this project: unfinished.** Remove the untracked `package.json`, `package-lock.json`, `.agents/`, `.claude-flow/` and the ruflo and claude-flow packages in `node_modules/` (`ruflo`, `@claude-flow`). Strip ruflo and claude-flow entries from `.claude/settings.json` (the `ruflo-*@ruflo` mod flags, the `CLAUDE_FLOW_*` env vars, the `claude-flow` permissions and the `ruflo` marketplace block) and from `.claude/settings.local.json`. Remove the claude-flow command, agent and skill files under `.claude/`, keeping any file the user still uses. Drop `ruvector.db` and the ruflo header lines from `.gitignore`. Check the `.claude/settings.json.bak-ruflo-mods-*` backup before deleting it.
2. **Ruflo mods at user scope need a decision from the user.** The mods `ruflo-mods`, `ruflo-swarm` and `ruflo-console` were loaded with trust grants that let them write files, run host commands, rewrite prompts and answer tool-permission verdicts. That registration is outside this project, so it is not removed here. Confirm before anything is changed there.
3. **Verify the `market_scanner` Mongo database through an authenticated query.** The store contains it (see What's done), but the `market_scanner` login in the secrets file does not authenticate against the copy. Check whether the password changed after the store user was created. Until this is settled, the scanner's ath_scanner data is the only part read and written through this container.


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

- **Expansion category question: closed 2026-09-29.** Neither `Acquisition` nor `Diversification/Disinvestment` is added to the column.
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

- **Rate limits verified 2026-09-29 (closed by measurement).** The cold scan made 1,969 requests with 0 HTTP 429s in about 30 minutes, under the 80%-of-limit windows in `scanner/upstox.py` (40/s, 400/min, 1600/30min). The 30-minute window has been exercised, so the earlier "unmeasured" note is resolved.

- **Scanner Mongo store copied from the infra, 2026-10-30.** `data/mongo/` (bind-mounted into `market-scanner-mongo`) holds the same files as `Shared-Market-Research-Infra/data/mongo`, which contains two databases: `ath_scanner` (filings 968, extractions 868, conclusions 586, fundamentals 298) and `market_scanner` (filings 968, extractions 868, conclusions 586, fundamentals 1048). The file lists match exactly. The copy is verified by file set; an authenticated count of `market_scanner` is still open (see Priority next).

- **Retry-After parsing fixed 2026-10-30.** `_parse_retry_after` in `scanner/upstox.py` accepts delta-seconds or an HTTP-date (past dates give 0). Covered by two tests in `tests/test_upstox.py`. Full offline suite: 848 tests, OK (46 skipped).

- **Limiter sleep moved outside its lock, 2026-10-30.** `_RateLimiter.wait` in `scanner/upstox.py` reserves the send slot under the lock and sleeps after releasing it, so other threads are no longer blocked during a wait. Covered by `test_sleep_runs_outside_lock_and_reserves_slot` in `tests/test_upstox.py`. Full offline suite: 849 tests, OK (46 skipped).

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

- **Expansion (factor 4) is the least trustworthy column.** Spot-check run 2026-10-30 on the
  12 candidates (15 stored `kind: expansion` filings, text from `ath_scanner.filings.raw_text`,
  matched with `_expansion_text` and `EXPANSION_KEYWORDS`). Result: 14 filings have a keyword
  hit. 12 read as real capacity or commercial-production news (WELSPUNLIV, AARTIPHARM,
  ASKAUTOLTD x2, SHYAMMETL x3, TI, ADANIPORTS, INDHOTEL, POWERINDIA, AMBER). Weak: COALINDIA
  (quarterly capex result, not a new project) and RELIANCE (brand portfolio expansion, generic
  keyword). AXISCADES' one filing has no keyword hit in stored text, so the candidate list's
  "text-match" label does not hold for it. Verdict:
  keep the column; precision looks acceptable on this sample of 12, recall is unmeasured.
  Also note: `select_expansion_filings` cannot run on stored docs as-is (they have no `sm_isin`,
  `attchmntText` or `an_dt`), so any scoring must match on `raw_text` and `desc`.
  Still open: confirm the keep decision and close this item.
  **Was blocked 2026-10-29 (see below for the fix):** the stored filing text was not in this checkout. `data/factors.db`
  is absent here, the copies in `app/data/` and the worktrees are empty, and the MongoDB on
  `localhost:27017` has an empty `ath_scanner` database. The infra env file points at host
  `mongo`, which does not resolve from this machine. Candidates (the 12 text-match-only rows
  in `output/ath_enriched_2026-09-28.csv`): AXISCADES, COALINDIA, WELSPUNLIV, AARTIPHARM,
  ASKAUTOLTD, SHYAMMETL, TI, ADANIPORTS, INDHOTEL, POWERINDIA, AMBER, RELIANCE.
  **Unblocked 2026-10-29.** MongoDB now runs in a container, `market-scanner-mongo` (`mongo:7`),
  with `data/mongo` under this project mounted as `/data/db`. The container is published on
  `127.0.0.1:27018`, because `27017` belongs to the tokenfrugal project's own Mongo container.
  The store was copied from `Shared-Market-Research-Infra\data\mongo`, not moved. `ath_scanner`
  holds `filings` 968, `extractions` 868, `conclusions` 586 and `fundamentals` 298. The 968
  count matches the 968 unique filings recorded in the handoff's scope. Not yet checked: that
  the expansion filings' text is present in `filings`. The spot-check can now run.
  The container is now a `scanner-mongo` service in `docker-compose.yml` (started with `--auth`, as
  `mri-mongo` is), and the `ath_scanner` login from the infra secrets works against it.
  **Still open:** the scanner reads the infra's `mongo` host (from `ath_scanner.env`), so new writes
  still land in `mri-mongo`. The benchmark and the 2026-09-29/30 conclusions used that store. The
  infra copy `Shared-Market-Research-Infra\data\mongo` is still mounted by `mri-mongo`, so it is kept
  until its owner agrees to retire it.
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
- **`5-15%` bucket not spot-checked against a second source.** The `NEW_ATH_TODAY` bucket was checked against Screener on 2026-09-29 and is closed (see What's done).
- **LTP cross-check is 3 symbols deep**, not 6: the Kite MCP session expired
  mid-session, so HDFCBANK/BSE/SWIGGY were not independently confirmed
  against a second broker. Re-login to Kite MCP and re-check if that matters.
  (The six `NEW_ATH_TODAY` names were since confirmed against Screener --
  see above -- so this now concerns the wider universe only.)


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

**Run it:** `./start.ps1` (full pipeline, no switches; see the 2026-09-30 section below), then
`./stop.ps1`. No scheduler; the 4 PM IST run was replaced by this manual
trigger on request. Flags: `-Symbols`, `-WithLaya`, `-SkipEnrich`,
`-SkipCrosscheck`, `-SkipPortfolio`, `-Rebuild` (the `-WithLlm/-WithTimesfm/-WithConclusions` switches were removed on 2026-09-30). Credentials reach containers
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
- (Superseded 2026-09-30: extraction now runs on vLLM/Qwen3-4B and Neo4j is built.)
- TimesFM lives only in the separate `enrich-timesfm` image (see the section below).
- No scheduled task was created.

## TimesFM image and per-stock conclusions (added 2026-09-29)

Two more images, both optional compose profiles, both loopback-only, neither
gets `.env`:

- **`enrich-timesfm`** (`docker/timesfm/Dockerfile`, profile `timesfm`,
  `./start.ps1 -WithTimesfm`): CPU torch + `timesfm[torch]==3.0.2`, runs
  `enrich.py --report --timesfm`. Re-writes `output/ath_enriched_<date>.csv`
  with the TimesFM forecast columns. Checkpoint is read from the project folder
  `./data/huggingface` (bind mount, not the shared infra models folder). Downloaded
  2026-10-30 into that folder (`google/timesfm-2.5-200m-pytorch`, 883 MB, snapshot
  `1d952420fba87f3c6dee4f240de0f1a0fbc790e3`) and verified loadable offline. Kept
  out of the light `enrich` image so the everyday run does not carry ~2 GB of torch.
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

## Neo4j, vLLM extraction, retention, one-command run (added 2026-09-30)

Architecture rule from the owner: every component is a container under the single
`docker-compose.yml`; only `start.ps1`/`stop.ps1` live on the host.

- **`start.ps1` (no switches)**: preflight (docker, `.env` exists, generate
  `.env.neo4j` if missing) -> build -> `up -d neo4j vllm` -> scan -> wait for vLLM
  -> `enrich --all --llm-url http://vllm:8000 --llm-model qwen3-4b --llm-api openai
  --llm-workers 4` -> `enrich-timesfm` -> `graph load` + `graph facts` -> `conclude`
  -> `graph conclusions` + `graph purge` -> stop vllm/neo4j -> `report` (xlsx) ->
  crosscheck -> portfolio. Graph steps are warnings if Neo4j is down (exit 3).
  Kept switches: `-Symbols -WithLaya -SkipEnrich -SkipCrosscheck -SkipPortfolio -Rebuild`.
  Ollama service, `ollama_models` volume and the `llm/timesfm/vllm` profiles are gone.
- **Extraction on vLLM**: Qwen3-4B-Instruct-2507 with strict JSON schemas
  (`scanner/llm.py` `SCHEMAS`). The model copies figure + scale word, code converts
  (`to_rupees`, `add_rupees`) because the 4-bit 4B model was 10x off doing crore
  arithmetic. Acceptance test `python bench_extract.py` (`scanner/extractcheck.py`):
  PASS 38/40 = 95% agreement with the regex (threshold 90%), 0 failed. The two
  disagreements (MTARTECH, ATLANTAELE) are not resolved; the regex is the reference
  only where it is anchored to the mandated field.
- **Graph** (`scanner/graph.py`, `graph_sync.py`, service `graph`, image `ath-enrich`):
  nodes Company, Filing(text, processed), Extraction, Counterparty, Conclusion,
  Fundamentals; all values go in as query parameters. `graph facts` writes
  `data/graph_facts.json` (distinct_customers, repeat_customers, peers_sharing_customer),
  which `conclude.py` turns into `graph.*` fact-sheet keys (counts only, only when a
  named customer exists). TinyDB is still the system of record; the graph can be
  rebuilt from it. `stop.ps1 -PurgeGraph` drops the volume (use it if `.env.neo4j` was
  deleted and the password no longer matches). Cypher was verified against a live
  neo4j:5-community (load, facts, purge) with synthetic data.
- **Retention** (`scanner/retention.py`, `config/retention.json`): `expires_at` =
  record date + `years` (3), stamped by `docstore.put_*` and on graph nodes. Purge
  deletes only expired AND processed records (filing processed = has an extraction).
  `"purge": false` disables deletion; env `RETENTION_YEARS`/`RETENTION_PURGE` override.
  `python graph_sync.py purge --dry-run`.
- **Final workbook** (`final_report.py`, `scanner/workbook.py`): sheet `Stocks` = all
  stocks and every column with filters, sheet `Summary` = counts/stance/industry/data quality.
- Secrets: `.env` never read by scripts; `.env.neo4j` is generated (random, git-ignored,
  `.dockerignore`d); neo4j and graph get only that file.
- Tests: 675 pass (2 skipped). Git Bash heredocs unescape `\n`; write Python with
  `chr(92)` or the Write tool when a patch needs a literal backslash.

## Not done (explicitly deferred per spec's "Later" section)

- Cron/scheduled 4 PM IST run on trading days. Unblocked by the ~1-year token,
  but deliberately replaced by the manual `start.ps1`/`stop.ps1` for now.
- `scanner/ath.py` remains import-clean (no I/O, no broker dependency) and
  can be reused as-is as a pure ATH/bucketing library.

## Shared infrastructure (added 2026-09-30, supersedes the neo4j/vllm details above)

Postgres, MongoDB, Neo4j, the vLLM server and the model weights moved out of this project into
`C:\Users\vaibh\Downloads\Projects\Shared-Market-Research-Infra` (see its README) so other projects
can share them. This project keeps only the analytical engine (scanner/enrich/graph/conclude/report
containers) and, next, the UI.

- `docker-compose.yml` no longer has `vllm`, `neo4j` or the `huggingface_vllm`/`neo4j_data` volumes;
  `docker/vllm/` was removed (now `Shared-Market-Research-Infra/vllm/`). Containers join the external
  network `market-infra` and reach `http://vllm:8000` and `bolt://neo4j:7687` by name.
- `start.ps1` runs `Shared-Market-Research-Infra\up.ps1 -Project ath_scanner -Llm -NoWait` (creates the
  project's databases, writes `secrets\ath_scanner.env`), waits on `mri-vllm`, and after conclusions runs
  `down.ps1 -Llm` to free the GPU (the databases keep running). `.env.neo4j` and `stop.ps1 -PurgeGraph`
  are gone; the graph login comes from `secrets\ath_scanner.env`. `MARKET_INFRA_DIR` overrides the location.
- Weights are the Hugging Face cache layout in `Shared-Market-Research-Infra\models\huggingface`; the
  imported copies have no blobs, so vllm and `enrich-timesfm` run with `HF_HUB_OFFLINE=1`.
  `bench_models.py` mounts the same folder.
- Still TinyDB (`data/documents.json`) + SQLite (`data/candles`, `factors.db`) as the stores; Postgres
  and Mongo are provisioned and empty for this project. Next: move the run/stock/timeline schema and the
  docstore there, then the UI and cost metrics.
- Old Docker leftovers that can be removed once nothing needs them: volumes
  `kite-ath-scanner_huggingface_vllm`, `kite-ath-scanner_neo4j_data`, image `kite-ath-scanner-vllm`.

## Postgres, UI, collector and cost metrics (added 2026-09-30, supersedes "Still TinyDB/SQLite" above)

State at the end of 2026-09-30: committed and pushed (`d5f885f` and later docs). Run A (3 stocks) and
run B (full, 291 scanned, 11 at ATH, Postgres run `61b38ae4-1e25-4be8-85bd-9b39930866de`) are
complete and verified. The old volumes `kite-ath-scanner_huggingface_vllm`,
`kite-ath-scanner_neo4j_data` and image `kite-ath-scanner-vllm` have been removed; keep
`kite-ath-scanner_huggingface_cache` (not used by compose now; compose volume is `market-scanner_huggingface_cache`, empty, re-downloads weights).

**What exists.**
- Storage split: Postgres (runs, snapshots, changes, `llm_calls`, collector tables, candles,
  announcements, corporate actions, coverage, listing), MongoDB (filings, extractions, conclusions,
  fundamentals), Neo4j (relationships, filings pushed after extraction). Full description in
  `ui/SCHEMA.md`; migrations in `db/migrations/`. Backend switches: `MARKETDATA_BACKEND`,
  `DOCSTORE_BACKEND`.
- `start.ps1` stages: ensure-infra, scan, `record_run.py --begin` (full runs only) plus a GPU power
  sampler, wait for vLLM, enrich, timesfm, graph load and facts, conclude, graph conclusions and
  purge, free the GPU, report, crosscheck, portfolio, `record_run.py` and
  `scanner.metrics finalize`, then UI and collector. Helpers: `ensure-infra.ps1`, `stop.ps1`
  (asks about the infra), `stop-infra.ps1`.
- UI (`ui/app/`, FastAPI, static HTML/JS, port 8080) and collector (`collect.py serve`, settings
  from the UI's Master configuration). Wireframe: `ui/wireframes/index.html`; design notes in
  `ui/DESIGN.md`, build plan in `ui/BUILD_PLAN.md`.
- Cost center is metrics only (tokens, calls, seconds, GPU energy). No prices are stored.
- `CLAUDE.md` points agents at the codebase-memory graph; the architecture decision record lives in
  the graph database (read it with `manage_adr`), not in a repo file.

**Measured baselines (run B).** scan 113 s, enrich 1620 s, timesfm 816 s, conclude 868 s; the full
pipeline is about 30 minutes.

**Gotchas.**
- Postgres returns NUMERIC as `Decimal`. The read boundary in
  `scanner/marketdata/postgres_backend.py` converts to float. The offline tests use
  sqlite/tinydb and cannot catch this class of bug.
- The infra's `up.ps1` and `down.ps1` change the caller's working directory; `start.ps1` wraps them
  in Push/Pop-Location.
- The pipeline picks its input as the newest `output/` file by name. Never rename an output with a
  suffix (a `_runA` suffix sorted after the new file and made run B enrich the wrong scan). Move old
  files into a subfolder instead.
- Container stdout is not captured in `logs/*.log` (`Invoke-Docker` pipes to `Out-Host`); only
  stderr is. Use `docker logs` or the run's Postgres row to debug.
- Windows PowerShell 5.1 drops quotes inside native arguments; the timings JSON is escaped for that.
- A scan with zero stocks in range writes a header-only CSV. Fixed: `enrich.py` exits with "nothing
  to enrich", `record_run.py` records a `complete` run with no snapshots (every previous member is
  logged once as `left_range`), and `start.ps1` skips the GPU, enrich, graph, conclude, crosscheck and
  portfolio stages. `compute_changes` also ignores previous `left_range` marker rows, so a stock that
  left is reported once, not on every later run.

**Open items.**
1. Replace the `output/` CSV hand-offs with database reads keyed by `run_id` (files only as a manual
   export). Affected: `enrich.py`, `conclude.py`, `final_report.py`, `crosscheck.py`, `portfolio.py`,
   `bench_models.py`, `record_run.py`, `scanner/collect/sources.py`, and `start.ps1`'s "newest file".
2. Confirm the final Cost center and Master configuration wireframes with the user.
3. `git init` in `Shared-Market-Research-Infra`; test `stop.ps1` end to end; decide how the home
   table's "scanned" count is shown; stop `mongo._ensure_indexes` swallowing auth failures; surface
   container stdout in the run logs.

## Report and UI review round (2026-09-30, after commit 3d4bfca)

Nothing in this section is implemented. It records the user's review of `output/ath_report_2026-09-30.xlsx`
(291 stocks), the decisions taken, the evidence behind them and the order of work. Commit `3d4bfca` is
pushed and the tree was clean; 838 tests, all passing.

### Standing instructions from the user (apply to every item below)

- Fix both the Excel workbook and the UI. The UI needs a **tooltip on every title that is complicated or
  confusing**. Build one glossary (column, plain-language meaning, how it is derived) and feed it to the
  Excel cell comments, the UI tooltips and the model prompt, so the three cannot drift apart.
- **Do not show the data source of the Screener fundamentals in the UI** (keep it secret). Code, README and
  schema docs may still name it. If the UI is ever shared or published, check the provider's terms first.
- Where a column is technical or means nothing to a reader, **keep it in the backend and hide it from Excel and UI**.
- Where a value is simply not reported, **leave the cell blank, not "UNKNOWN"**.
- Wireframe first, get sign-off, then code (the standing rule for UI work).

### Column decisions

| Column | Decision |
|---|---|
| `ath_high` | Add `low_since_ath` (lowest low since the ATH date) with its date, and `max_drawdown_pct` (ATH to that low). The user confirmed: "LL since ATH, max_drawdown_pct - perfect." Optional flag when the drawdown went beyond 26% and the stock has since recovered into range. Source: `candles` in Postgres, no download. |
| `above_ema50`, `above_sma200` | Drop from Excel and UI; `trend` already encodes them. Also drop from the model's input (`scanner/conclude.py` packet, ~line 50) because the model cites them in many conclusions. Keep in the backend only if something still needs them. |
| `bonus_issue`, `demerger`, `orderbook_signal`, `expansion_signal` | Add `acquisition_signal` beside them. **Match NSE's real announcement categories (controlled vocabulary, 132 categories); never guess the wording** (see the NSE `desc` memory note). Keep the "text-match only" qualifier the other signals carry. |
| `stance` | Needs a plain-language reading so a user concludes quickly (see "Stance clarity"). The stance is deterministic, set by the scorecard in `scanner/conclude.py`, not by the model. |
| `stance_score` | Sum of six pillars (trend, growth, quality, valuation, forecast, orders), each clamped to -2..+2. CONSTRUCTIVE at >= 3, CAUTIOUS at <= -2, else MIXED; MIXED when fewer than 3 pillars have data (`CONSTRUCTIVE_AT`, `CAUTIOUS_AT`, `MIN_PILLARS`). Put this in the tooltip and cell comment. **The scoring is about to be redesigned (see "Scoring: parked")**, so do not polish it yet. |
| `mcap_cr` | Put latest sales (`ttm_sales_cr`, else last annual) directly beside it, then `order_pct_of_mcap`, then `order_pct_of_sales`. Only 24 of 291 stocks have an order value, so those columns are often blank. |
| `order_value_source` | Reword for end users and add a comment. Proposal (user to confirm wording): `anchor+scaled` = "Filed figure"; `anchor+bare` = "Filed figure (unit inferred)"; `llm` = "AI-read"; `loose` = "Approximate"; `cumulative` = "Period total, not one order"; `withheld` = "Not disclosed"; `foreign-currency` = "Quoted in foreign currency". Consider renaming the column to `order_value_basis`. |
| `order_significance` | Blank when unknown (267 of 291 today). Comment: the larger of the order's share of market cap and of sales, banded NEGLIGIBLE, MODEST, MATERIAL, LARGE, TRANSFORMATIONAL. Not every company reports orders; blank is fine. |
| `rev_forward_ttm_bad_cr`, `rev_forward_ttm_good_cr`, `rev_growth_pct_bad`, `rev_growth_pct_very_good`, `rev_ttm_dev_*` | Hide from Excel. Keep `rev_forward_ttm_cr` and `rev_ttm_growth_pct` visible. They are the 12-month revenue forecast range (10th, 50th and 90th percentile of backtested forecast errors) and are NOT reflected in `order_significance`. In the UI show a **flag or chip in the style of the pros and cons on screener.in**, e.g. "Forecast uncertain" when `rev_ttm_dev_pct` is high (the scorecard already penalises it), with the range in a tooltip or on the stock page. |
| `rev_note` | Backend only. 244 of 264 rows carry the same 180-character note about band width; it tells a reader nothing. |
| `stance_rules` | Backend only. Audit trail of the rules that fired. In the UI it feeds an expandable "why this stance" breakdown. |
| `vol_vs_baseline` | Backend only. |

### Volatility columns (these are NOT volume)

`vol_*` come from `scanner/volatility.py` and measure **price volatility from daily closes**. The model read
"vol" as volume: **98 of 291 conclusions (34%) say "volume"**, e.g. "stable volume regime" as a positive. That is
wrong. Rename the user-facing labels as the user specified:

| Old | New label | Meaning |
|---|---|---|
| `vol_pct` | `HV` (Historical Volatility) | annualised standard deviation of daily log returns over the last 21 trading days |
| `vol_baseline_pct` | `HV_PCT` | median of the same stock's own HV history |
| `vol_vs_baseline` | (backend only) | HV divided by baseline |
| `vol_percentile` | `HV Percentile` | where today's HV sits in the stock's own history, 0 to 100 |
| `vol_regime` | `HV Regime` | EXPANDING at 1.30x baseline or more, CONTRACTING at 0.77x or less, STABLE between |
| `vol_forecast_pct` | `HV Forecast` | TimesFM forecast of HV for the next 21 days. The user finds it useful for hedging, so keep it visible. |

Rename in the workbook, UI, the model packet keys (`price.vol_*`) and the prompt glossary. Internal Python names can
stay if renaming them is too invasive, but the packet keys the model sees must not contain "vol".

### `breakout_quality` (how it is determined)

`scanner/volatility.py: breakout_quality`:
- blank unless `trend` is UPTREND;
- **HOT** if the HV regime is EXPANDING or HV percentile >= 80;
- **ORDERLY** if the regime is CONTRACTING or HV percentile <= 20;
- otherwise **NORMAL**.

It describes volatility, not a true breakout: no volume confirmation and no base or consolidation check. Once volume
data is in (below), redefine it to combine price near the ATH, a volume spike and delivery %, and document the rule
in the tooltip.

### Volume (traded and delivery), minimum effort

The user asked to consider trading and delivery volume from NSE and BSE ("bhavcopy or something else, or daily
tracking ... minimum efforts"). Findings:
- `candles` (Postgres, 2,630,987 rows, 2000-01-03 to 2026-09-29) **already stores `volume` on every row**. Traded
  volume, spikes and averages need **no new data**. Verify whether the candle source volume is NSE-only or
  consolidated before relying on absolute numbers.
- **Delivery quantity and delivery %** are in NSE's security-wise bhavcopy. `data/_bhav_probe.csv` shows the columns
  `TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER`. `scanner/crosscheck.py` already downloads the
  daily file and keeps only the price columns (`data/bhavcopy/bhavcopy_<date>.csv`, 33 files).
- BSE has its own bhavcopy and delivery file, but it is more work and adds little for NSE-listed names.

Plan:
1. New Postgres table `daily_volume (symbol, date, traded_qty, delivery_qty, delivery_pct, trades, turnover)`, primary
   key `(symbol, date)`, `ON CONFLICT DO NOTHING`, plus `feed_coverage` so only missing dates are fetched. Reuse the
   NSE bhavcopy fetch from crosscheck and stop discarding the delivery columns.
2. Backfill from NSE's archive of the same file (about 250 files per year); never re-download dates already held.
3. Derived columns: `volume_spike_x` (today's volume over the 20-day average, from `candles`), `delivery_pct`, and a
   delivery-% average or percentile. A spike at or near the ATH is a scoring positive (see below).
4. BSE: later, only if wanted.
5. Daily tracking: add it as a collector source, same pattern as the existing five in `collector_settings`.

### Stance clarity (so a user concludes quickly)

The user asked for better understanding at a glance (#4). Proposal: show stance as a badge plus a one-line,
**deterministic** reason built from the scorecard, not the model, e.g. "Uptrend, 35% growth | Stretched PE". In the UI
add a six-pillar mini-bar (trend, growth, quality, valuation, forecast, orders) and an expandable list of the rules
that fired (from `stance_rules`). In Excel add `stance_why` (the one-liner). The final form depends on the scoring
redesign.

### Scoring: parked (core of the strategy; the user will return with a major update)

Do **not** implement before the user returns. The user's wishlist, recorded so nothing is lost:
- Add **PEG** and use it in ranking.
- A factor concluded as positive and impactful should act as a **tailwind**; work out how to derive that.
- A **sudden volume spike at or near the ATH** is a positive factor.
- **QoQ and YoY growth forecast** should add points.
- **Two ranking constraints** (the user will specify).
- **Red flags** give negative marks.
- Also weigh, with positive or negative marks: `order_significance`, `capacity_change` and its significance,
  `breakout_quality`, `rev_ttm_growth_pct`, `rev_ttm_dev_pct`.

Weaknesses in the current scorecard the redesign should address: distance from the ATH is both the screen and a score
input, so it double counts (38 of 47 CAUTIOUS stocks sit in the 15-26% bucket); 10 stocks have an industry PE exactly
equal to their own PE, which gives a fake "0.0% in line" reading (Titan, AIIL, Adani Power, JSW Infra, WABAG,
Lotus Dev, PFOCUS, INDHOTEL and others). That looks like a fallback, so blank it and flag it.

### Findings from the 60-row read (evidence for the prompt changes)

Sample of 60 (22 CONSTRUCTIVE, 22 MIXED, 16 CAUTIOUS, `random_state` 7). Counts are across all 291 rows.
- Raw field names leak into the text: conclusion 194 rows (67%), concerns 81 (28%), positives 33 (11%).
- "No order data" listed as a concern in 143 rows (49%); most stocks simply have no order flow.
- "Distance from ATH" listed as a concern in 177 rows (61%), though the whole list is chosen by ATH proximity.
- Positives empty in 67 rows (23%), all MIXED or CAUTIOUS.
- Backwards or invented statements: MRF "-48% of industry PE ... valuation pressure" (a discount is cheap); KRN PE
  60% above industry "not a concern"; "No recent IPO" as a concern; "Unplanned order significance"; "Lack of
  breakout quality".
- Conclusions average 581 characters and restate numbers instead of giving a thesis.
- `data_gaps` says "no recent filings stored" for 83 rows (29%); that is an internal storage note, not a data gap.

Prompt changes to make (`scanner/conclude.py`):
- Give the model a plain-language glossary (the shared glossary file).
- Forbid field names such as `price.distance_pct` in any output field.
- Do not list missing order data as a concern unless the stock has a real order signal.
- Do not list distance from the ATH as a concern (the screen already implies it).
- Require at least one positive or an explicit "none identified".
- Write the conclusion as a thesis: what is working, what is at risk, what to watch.
- Make `data_gaps` list real gaps only.

### UI direction (decided, not started)

- The UI moves to **Node.js** with an **AI chat** over the stored data, and intuitive graphs and views. This
  supersedes the FastAPI plan; update the ADR (`manage_adr`) when it starts.
- **TradingView Lightweight Charts** for per-stock price charts and technical indicators, with an ATH line.
- The per-stock page also shows the Screener fundamentals, with no source label (see standing instructions).
- Open questions for the user before building:
  1. Node's role. Recommendation: keep Python for the data and analytics API and build Node on top of it.
  2. Which model answers the chat: the local Qwen3-4B on vLLM (free, private, weaker, needs the GPU) or the Claude
     API (stronger, costs money, sends data out).
  3. Grounding. Recommendation: read-only tools over timelines, candles, filings, conclusions and fundamentals;
     every answer cites its record; no free-form SQL.
- Indicators are best computed in Python and returned as series.

### Suggested order of work

1. Shared glossary file (column, label, meaning, derivation) used by Excel, UI and prompt.
2. Workbook changes: column order, hidden and renamed columns, blanks instead of UNKNOWN, cell comments,
   `low_since_ath`, `max_drawdown_pct`, acquisition signal, HV renames.
3. Prompt fixes and model packet cleanup; re-run a sample and re-read 50 rows to confirm the defects are gone.
4. Volume pipeline: `daily_volume`, NSE delivery, derived spike and delivery columns, redefine `breakout_quality`.
5. Wait for the user's scoring update; only then redesign the scorecard and the stance explanation.
6. UI wireframe (charts, chat, tooltips, stock page, flags), user sign-off, then the Node build.

## Pilot: surface container stdout in run logs (parked, 2026-10-27)

Parked until the tokenfrugal changes are finished. Nothing in this repo has changed for this item.

**Why this item.** It is the pilot for the EGM planning workflow. The `_create_index` auth fix that was also on the list is already in the uncommitted `scanner/mongo.py`, so it was not used.

**State.** `start.ps1` starts Docker containers, such as `mri-vllm`, and logs only its own steps. When a container fails, the cause is visible only through `docker logs`, which is not written to `logs/`.

**Work plan once resumed.** Use a git worktree from committed HEAD `fe4d56b`, so the uncommitted changes stay untouched. Run `egm:egm-brainstorm` (the plugin is now installed and registered), then write the design, then have the local builder do the tasks.

**Open questions for the user (answer in chat, one at a time):**
1. When a container fails, what must the log show: its stdout only, or also start time and exit code?
2. Should every container that `start.ps1` launches be captured, or only the ones the pipeline waits on, such as `mri-vllm`?
3. vLLM output can be long. Should the run log keep everything, or only the tail when a container fails?
4. How will you know the pilot worked?
5. Brainstorm reviewers (decided 2026-10-27): use the EGM default, six Goldfish lenses plus the synthesizer. The user may reduce this later to two lenses plus one synthesizer. The CLAUDE.md section now says the same.

## Tokenfrugal test items (moved from tokenfrugal handoff, 2026-10-27)

These two checks belong to the tokenfrugal repo (`C:\Users\vaibh\Downloads\Projects\tokenfrugal`; the branch was merged as PR #43, and the cap change is commit `13cbe7b`). They were moved here to be tested. Nothing in this repo has changed for them.

1. **Automatic coding path on a real bench run.** Open.
   - Done: a temp-copy check (`scratchpad/coding_path_check.py`) ran `suite_detail` → `publish_detail` → `summarize` → `upsert_summary` on a copy of `Benchmark/results`. The summary row picked up the new `datetime_coding`, the older live rows were marked superseded, and the real CSVs were byte-identical afterwards. The source was a legacy coding JSON relabelled to another model, so this tests the plumbing only.
   - Not done: a real `run_benchmark.py --role coding` run with a model, the Docker suite and the endpoint.

2. **Live `dispatch_task` check after the docstring change.** Open, not run.
   - Change: the `dispatch_task` docstring in `router/server.py` now says "up to 5000 tokens" (the cap was raised from 300 on `main` in `ba98023`). Tokenfrugal's CLAUDE.md says a docstring change alters local-model delegation behaviour.
   - Not run: a live call through the tokenfrugal MCP. The tokenfrugal repo's memory rule says to use Haiku subagents there, not that MCP, so this needs an explicit decision before it runs.

**How to pick this up.** Run item 1 from the tokenfrugal repo with a real model. Run item 2 with one routine task, then compare the summary length and quality with the previous behaviour.
