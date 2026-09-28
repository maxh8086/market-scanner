# ATH Scanner — Nifty Total Market

Finds every stock in the Nifty Total Market index (~750 names) that's at its
all-time high, or within a configurable percentage of it.

## Architecture: Upstox for data, Kite for portfolio

**Market data comes from Upstox; holdings stay on Kite.** The split is
deliberate:

- **Upstox** issues a long-lived (~1 year) *analytics* access token, so the
  scanner needs no daily interactive login. That is what makes an
  unattended scheduled run practical — Kite Connect tokens expire every
  morning around 6 AM IST and require pasting a fresh `request_token` by
  hand. Upstox also addresses instruments by ISIN and allows ~a decade of
  daily candles per request.
- **Kite** is where the actual portfolio lives, and that side is read
  conversationally through the Kite MCP connector rather than by this
  script.

The Upstox analytics token is **data-only** — it cannot place orders. That
is a feature here, not a limitation: nothing in this repo can trade.

## Setup

**Use the project virtualenv. Do not install into a system Python.**

This project pins **Python 3.13** (see `.python-version`). Three Python
versions are installed on the original dev machine and a bare `python` on
PATH resolves to 3.10, which is *not* the pinned one -- so always call the
venv interpreter explicitly, or activate the venv first.

```bash
# One-time: create the venv with the pinned interpreter
py -3.13 -m venv .venv

# One-time: install runtime + test deps (requirements-dev.txt pulls in
# requirements.txt via a -r line, so this single command covers both)
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

cp .env.example .env
# edit .env and set UPSTOX_ANALYTICS_ACCESS_TOKEN
```

Activate it (optional, but then plain `python` is the right one):

```bash
.venv\Scripts\Activate.ps1     # PowerShell
source .venv/Scripts/activate   # Git Bash
```

Verify the environment before a real run -- both of these must succeed:

```bash
.venv\Scripts\python.exe ath_scan.py --help
.venv\Scripts\python.exe -m pytest tests -q
```

> **Why this matters.** Dependencies used to be spread across three system
> Pythons: 3.10 had pandas + openpyxl but no pytest, 3.13 had pytest +
> pandas but no openpyxl, 3.11 had neither. The 3.13 gap was the expensive
> one -- a full scan spends ~5 minutes fetching data and enriching factors
> *before* it reaches the Excel-writing step, so a missing `openpyxl`
> surfaced as a `ModuleNotFoundError` only after all that work was done.
> The venv exists to make that class of failure impossible.

`requirements.lock.txt` is a `pip freeze` snapshot of a known-good install
(Python 3.13.7, pandas 3.0.6, openpyxl 3.1.5) for reproducing this exact
environment. `requirements.txt` keeps the looser `>=` ranges.

Generate the token from the [Upstox developer
portal](https://account.upstox.com/developer/apps).

> **Put real credentials in `.env`, never in `.env.example`.** `.env` is
> gitignored; `.env.example` is a committed template and is meant to hold
> placeholders only.

## First run

```bash
.venv\Scripts\python.exe ath_scan.py
```

No login prompt — the token in `.env` is used directly.

## Usage

```bash
# With the venv activated, plain `python` is correct. Unactivated, use
# .venv\Scripts\python.exe in place of `python` below.
python ath_scan.py                  # full scan, 26% cutoff
python ath_scan.py --max-dist 10    # tighter cutoff
python ath_scan.py --symbols INFY,TCS --verbose
python ath_scan.py --rebuild        # re-download constituents and ALL history
python ath_scan.py --refresh-history RELIANCE,TCS   # re-download history for just these symbols
```

First run: ~750 stocks × ~3 history calls each (Upstox serves ~a decade of
daily candles per request, so a full 26-year history is 3 requests, not
13). Measured at ~7 req/sec sustained ⇒ **roughly 5 minutes**. Later runs
only fetch days after the last cached date per symbol, so they finish in
seconds.

## Output

`output/ath_scan_YYYY-MM-DD.xlsx` (one sheet per bucket + a `Summary`
sheet with counts by bucket and industry) and a matching `.csv`, both
sorted by bucket then by distance from ATH. Columns:

```
symbol, company, industry, ltp, today_high, ath_high, ath_date, ath_close,
distance_pct, bucket, days_since_ath, listed_days, recent_ipo
```

Symbols that couldn't be scanned (missing ISIN, failed quote/history fetch,
suspended, etc.) are logged to `logs/skipped.csv` with a reason instead of
crashing the run.

## Caching

- `data/ind_niftytotalmarket_list.csv` — the NSE constituent list (re-downloaded on `--rebuild` or if missing). This is also the instrument source: its `ISIN Code` column becomes the Upstox `instrument_key`, so there is no separate broker instrument dump to download or keep fresh.
- `data/history.db` — SQLite, one `candles` row per symbol/day plus a `symbol_stats` table caching each symbol's `ath_high`/`ath_date`/`ath_close`/`first_date`/`last_date` so repeat runs only fetch new days.

Today's own candle is **never** written into `history.db` mid-day — the
scanner always fetches history only up through *yesterday*, and combines
that with today's live quote (`last_price`, `live_ohlc.high`) at scan time.
That way a forming intraday candle never gets double-counted, and once
that day is over, the next run's incremental fetch picks it up as a
normal historical row.

## Correctness notes

**Split/bonus adjustment — verified on live Upstox data.** Daily candles
are adjusted for splits and bonus issues, so a stock that has had a
corporate action does **not** show a phantom pre-split spike in its
`ath_high`. Confirmed 2026-09-28 on two different stocks and two different
actions:

> **RELIANCE** (1:1 bonus, ex-date 2024-10-28). The last cum-bonus session
> (2024-10-25) returned a high of 1,344.35 and the ex-bonus session
> (2024-10-28) returned 1,353.00 — a continuous series, no ~50% cliff.
> RELIANCE actually traded near ₹2,690 on 2024-10-25, so every pre-bonus
> candle had been retroactively halved. **This matches Kite's own value for
> the same session to the paise** (1,344.35 from both), which is a
> cross-broker agreement, not a single source's word.
>
> Adjustment also holds all the way down the series: the earliest candle
> available, 2000-01-03, comes back at a scale consistent with *both* the
> 2017 and 2024 1:1 bonuses having been applied.
>
> **HDFCBANK** (1:1 bonus, 2025) independently confirms it: its `ath_high`
> is **1,020.50**, on the post-bonus scale. Unadjusted data would have put
> the ATH near ₹2,000 from the pre-bonus era.

Live LTPs also agree across brokers: RELIANCE 1,197.60 / INFY 1,003.20 /
TCS 2,070.70 were identical from Upstox and from Kite.

To repeat this check on another corporate action, pull daily candles for a
window spanning the ex-date and look for a discontinuity. If a stock ever
does turn out *not* to be adjusted, re-run with
`--refresh-history <SYMBOL>`, or `--rebuild` to force a clean re-fetch.

**Instrument resolution — ISIN-native, no token lookup.** Upstox addresses
instruments as `NSE_EQ|{ISIN}`, and the constituents CSV already carries an
`ISIN Code` column, so a symbol maps to its instrument key by string
construction. There is no instrument dump to download, no numeric token to
resolve, and a tradingsymbol rename cannot break a lookup. This retires an
open question from the Kite design, where matching went through
`tradingsymbol` with ISIN only as a *fallback* that depended on whether
Kite's public `GET /instruments` CSV exposed an `isin` column — something
that was never confirmed. It no longer matters.

**Quote response mapping — a real trap, handled.** The OHLC quote endpoint
does **not** key its response by the `instrument_key` you send. It returns
entries keyed `EXCHANGE:TRADINGSYMBOL` (e.g. `NSE_EQ:RELIANCE`), with the
key you sent echoed in each payload's `instrument_token`. Mapping results
back by the response key alone would silently match **nothing** — a
750-symbol scan would report zero results with no error. `scanner/upstox.py`
maps via `instrument_token`, with the tradingsymbol as a fallback, and
returns any unmappable keys to the caller rather than dropping them. A
200-symbol batch mapped 200/200 with zero misses.

**History depth.** Daily candles start at **2000-01-03**; asking for
anything earlier returns nothing rather than an error. Requests are capped
at roughly a decade — a 3,653-day window succeeds, while
2000-01-01→2026-09-28 is rejected with `UDAPI1148 Invalid date range` — so
`scanner/history.py` walks back in 3,650-day chunks.

**Recent IPOs.** Any symbol with less than 365 days of price history gets
`recent_ipo = True` — its "ATH" is only as meaningful as a few months of
trading.

**Intraday vs. final.** Before 3:30 PM IST the terminal summary and output
are labeled as intraday (today's high/LTP are still moving); after that,
the day's candle is treated as final.

## Spot-checking

Pick 3 stocks and compare against a chart by hand:
- One that should be at/near its ATH today (bucket `NEW_ATH_TODAY`)
- One roughly 10% below ATH (bucket `5-15%`)
- One recent IPO (`recent_ipo = True`)

Their `ath_high` / `ath_date` should match the chart's "all-time" view.

Checked so far (2026-09-28): `RELIANCE` ATH 1,611.80 on 2026-01-05, LTP
1,197.60, 25.70% below — just inside the 26% cutoff. `HDFCBANK` 29.54%,
`BSE` 30.34%, `INFY` 50.00%, `TCS` 54.91%, `SWIGGY` 58.53% (all outside the
cutoff and correctly excluded from a default run). The `NEW_ATH_TODAY` and
`5-15%` buckets have not yet been eyeballed against a chart — do that on a
day when a name actually lands in them.

## Project layout

```
ath_scan.py             # CLI entry point
scanner/
  upstox.py             # Upstox client: auth, instrument keys, quotes, candles
  constituents.py       # NSE list download/cache/clean (also the ISIN source)
  history.py            # chunked, cached history fetch (provider-agnostic)
  ath.py                # ATH + distance + bucketing (pure functions, no I/O)
  report.py             # Excel/CSV/terminal output
  auth.py               # Kite login + token cache -- NOT used by the scan;
  instruments.py        # Kite token resolution -- NOT used by the scan;
                        #   both retained for the Kite portfolio side
tests/test_ath.py       # unit tests for ath.py with synthetic candles
tests/test_factors.py   # unit tests for corporate-factors enrichment
.python-version         # pinned interpreter (3.13)
requirements.txt        # runtime deps
requirements-dev.txt    # test deps (includes requirements.txt via -r)
requirements.lock.txt   # pip freeze snapshot of a known-good install
```

`scanner/history.py` takes any object exposing
`daily_candles(key, from_date, to_date)`, so swapping the data provider
again means writing one class, not touching the caching or scan logic.

## Tests

Run the whole suite with pytest from the venv (**49 tests**):

```bash
.venv\Scripts\python.exe -m pytest tests -q
```

`pytest` is declared in `requirements-dev.txt`, not `requirements.txt` --
it is a test-only dependency.

> The older documented command, `python -m unittest tests.test_ath -v`,
> still passes but runs only the 26 tests in `test_ath.py` and silently
> skips the 23 in `test_factors.py`. Prefer the pytest command above.
> (`python -m unittest discover tests` also finds all 49.)

## Later

- Cron/scheduled run at 4 PM IST on trading days.
- `scanner/ath.py` has no I/O and can be imported directly by other tools
  (e.g. an equity-agent platform) as a pure ATH/bucketing library.
