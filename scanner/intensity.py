"""Market-wide order-award intensity: how many order wins the whole market is filing.

The rest of this project looks at one company at a time, which cannot answer the
question that decides what a single order win is worth: is this a market in a
capex upcycle, or three companies having a good quarter? A stock winning orders
while market-wide order flow is rolling over is a very different position from
the same stock in a rising tide.

The data is already local. `factors.db` holds every announcement fetched for the
scan, so collapsing it to a monthly count is free -- no API calls, no rate limits,
no new credentials.

Two properties make this the series a sequence model is actually suited to:

  aggregation  summing across ~750 companies cancels idiosyncratic noise and
               leaves the cycle, where a single company's filings are lumpy.
  seasonality  Indian order flow has a hard fiscal calendar. March quarter
               awards spike as government and PSU budgets are spent before the
               year closes, and April is quiet. That is a repeating annual
               pattern, which is exactly what a seasonal model exploits.

Two cautions kept in the code, because both would otherwise be invisible.

First, this series measures *filings*, not rupees, until the LLM stage has
populated values. A month with more but smaller orders looks identical to a month
with fewer but larger ones. `monthly_value()` exists for when values are
available, and the count series is the fallback, not the goal.

Second, the series is only comparable across months where NSE was publishing the
order-win announcement subjects, which began in September 2024.
`_trim_pre_taxonomy` removes the earlier months, where a level break would
otherwise be read as trend. What it cannot remove is the possibility that filers
adopted the new subject codes gradually over the months that follow -- adoption
drift and genuine growth in order flow look identical from here, and both would
push the year-on-year reading up. So treat a rising label as "order filings under
the new taxonomy are rising", which is weaker than "the market is winning more
orders" and is the most this data supports.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Sequence

from scanner import factors
from scanner import forecast as fc

# Monthly series, so an annual cycle is 12 points.
SEASON_MONTHS = 12

# Three months ahead, matching the horizon used elsewhere in the project so the
# market read and the per-stock read cover the same period.
STEPS = 3

# Three thresholds, because the two halves of this module need different amounts of
# history and conflating them threw away the useful half.
#
# A year and a month is enough to compare this month against the same month last
# year, which is the measurement that actually changes a reading of a single
# stock's order win. One season (12 months) is what a *seasonal* forecast needs to
# produce a point estimate from the value at t-12, but without a backtest to
# validate the error band. Two years and a month is what a *validated seasonal*
# model needs, so that a repeating annual pattern can be separated from a trend
# and the error band can be backtested.
#
# The scan's own announcement cache only reaches back ORDERBOOK_LOOKBACK_MONTHS,
# so in practice the trend is available from the existing cache and the forecast
# needs a deliberate backfill. Reporting nothing until the backfill exists would
# hide a number that is already there.
MIN_MONTHS_TREND = SEASON_MONTHS + 1
MIN_MONTHS_SEASONAL_UNVALIDATED = SEASON_MONTHS + 1  # 13: one season for t-12 lookback
MIN_MONTHS = 2 * SEASON_MONTHS + 1  # 25: two seasons for backtest validation

# The current month is excluded from the series. It is incomplete by definition,
# and a part-month count read as a full one looks like a collapse in order flow
# every single month.
DROP_CURRENT_MONTH = True

# The oldest month is excluded for the same reason at the other end. The
# announcement cache begins at "today minus N months", which lands mid-month, so
# its first month holds only the days after that date and is undercounted by
# however far into the month the fetch started.
#
# That matters more than one month of lost history: an undercounted month becomes
# the denominator of exactly one year-on-year comparison, and the "same month a
# year ago" value for one seasonal prediction. Both would read as growth that did
# not happen. One month is a cheap price for not inventing it.
DROP_FIRST_MONTH = True

# How many months a backfill should fetch to leave MIN_MONTHS usable ones.
#
# Two are lost, one at each end: the fetch starts mid-month so its first month is
# partial and dropped, and the current month is incomplete and dropped. A third
# is added as headroom, because the dense range ends at the newest *filing* and
# not at today -- a cache that is a few weeks stale loses another month, and
# discovering that after a 26-request fetch is a poor trade against one more
# request.
BACKFILL_MONTHS = MIN_MONTHS + 3

TREND_RISING = "RISING"
TREND_FLAT = "FLAT"
TREND_FALLING = "FALLING"
TREND_UNKNOWN = "UNKNOWN"

# Year-on-year change bands for the trend label.
RISING_PCT = 15.0
FALLING_PCT = -15.0


@dataclass
class MarketIntensity:
    """The market-level order-flow read. One row per run, not per stock."""

    months: list[str] = field(default_factory=list)      # "2026-08", oldest first
    counts: list[int] = field(default_factory=list)
    latest_month: str = ""
    latest_count: Optional[int] = None
    yoy_pct: Optional[float] = None
    trend: str = TREND_UNKNOWN
    forecast: list[Optional[float]] = field(default_factory=list)
    forecast_total: Optional[float] = None
    backend: str = ""
    agreement: str = ""
    n_filings: int = 0
    note: str = ""
    error: str = ""
    band_validated: bool = True  # False if seasonal forecast with unvalidated band

    @property
    def ok(self) -> bool:
        """Enough history for the year-on-year measurement and the trend label."""
        return not self.error and len(self.counts) >= MIN_MONTHS_TREND

    @property
    def can_forecast(self) -> bool:
        """Enough history for a *seasonal* forecast (unvalidated from 13 months,
        validated from 25)."""
        return not self.error and len(self.counts) >= MIN_MONTHS_SEASONAL_UNVALIDATED

    def summary(self) -> str:
        if not self.ok:
            return self.error
        bits = [f"{self.latest_month}: {self.latest_count} order filings"]
        if self.yoy_pct is not None:
            bits.append(f"YoY {self.yoy_pct:+.0f}%")
        bits.append(self.trend.lower())
        if self.forecast_total is not None:
            bits.append(f"next {STEPS}m ~{self.forecast_total:.0f}")
        return ", ".join(bits)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_range(first: str, last: str) -> list[str]:
    """Every month from `first` to `last` inclusive.

    Built explicitly rather than taken from the keys present in the data: a month
    in which no company filed an order win is a zero, and skipping it would
    compress the calendar and destroy the seasonality the model is here to read.

    Note the deliberate asymmetry at the ends. The range spans the first and last
    filing, so interior gaps are zero-filled but months after the last filing are
    absent rather than zero. An interior gap is genuinely a quiet month; a gap at
    the end is far more likely a cache that has not been refreshed, and filling
    it with zeros would report a market-wide collapse that never happened.
    """
    fy, fm = (int(x) for x in first.split("-"))
    ly, lm = (int(x) for x in last.split("-"))
    out = []
    y, m = fy, fm
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def monthly_counts(rows: Iterable[dict], today: Optional[date] = None
                   ) -> tuple[list[str], list[int]]:
    """Collapse order-win announcements into a dense monthly count series.

    `rows` are announcement dicts with a date field, as `factors` caches them.
    Only rows whose description matches the order-win rule are counted, using
    `factors`' own keyword set so the market series and the per-stock factor
    never diverge on what an order win is.
    """
    months, counts, _ = _series(rows, today=today)
    return months, counts


def _series(rows: Iterable[dict], today: Optional[date] = None
            ) -> tuple[list[str], list[int], bool]:
    """`monthly_counts`, plus whether the start was cut at the taxonomy boundary.

    The flag decides what advice to give a caller who wants a forecast and does
    not have enough history. "Backfill the cache further" is right when the cache
    is simply short, and wrong when the series already starts where NSE began
    publishing the field -- there is nothing earlier to fetch, and the only
    remedy is calendar time.
    """
    today = today or date.today()
    buckets: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    any_filing: Counter[str] = Counter()
    for row in rows:
        d = _row_date(row)
        if d is None:
            continue
        key = _month_key(d)
        any_filing[key] += 1
        matched, is_category = factors.matches_orderbook(row)
        if not matched:
            continue
        buckets[key] += 1
        if is_category:
            by_category[key] += 1
    if not buckets:
        return [], [], False
    months = _month_range(min(buckets), max(buckets))
    trimmed = _trim_pre_taxonomy(months, by_category, any_filing)
    at_taxonomy_start = len(trimmed) < len(months)
    months = trimmed
    if DROP_FIRST_MONTH and len(months) > 1:
        months = months[1:]
    if DROP_CURRENT_MONTH:
        current = _month_key(today)
        months = [m for m in months if m < current]
    return months, [buckets.get(m, 0) for m in months], at_taxonomy_start


def _trim_pre_taxonomy(months: list[str], by_category: Counter,
                       any_filing: Counter) -> list[str]:
    """Drop the leading months from before NSE's order-win categories existed.

    NSE introduced the structured announcement subjects -- "BAGGING/RECEIVING OF
    ORDERS/CONTRACTS" and the rest of `ORDERBOOK_DESC_CATEGORIES` -- in
    September 2024. Before that, the only order wins this rule can see are the
    ones whose attachment text happens to carry a keyword, which is roughly a
    fifth of them. A cache fetched further back therefore does not begin with
    quiet months; it begins with a *step* in the level of the series.

    That is the worst possible defect for this particular feature. A seasonal
    model fitted across a level break reads the break as trend and extrapolates
    market-wide growth of tens of percent a year that is entirely an artifact of
    when a field started being published -- and it would do so confidently,
    because the series really does rise.

    Detected rather than hardcoded to a date, because the rule is what matters:
    a month carrying thousands of announcements and not one row in the order
    category taxonomy did not have the taxonomy. Only a *leading* run is
    trimmed; a later month with no category matches is a data problem worth
    seeing, not a regime, and trimming the middle would silently reshape the
    series.
    """
    cut = 0
    for i, m in enumerate(months):
        # A month with no filings at all is a gap in the cache, not evidence
        # either way -- leave the decision to the months around it.
        if not any_filing.get(m):
            continue
        if by_category.get(m):
            break
        cut = i + 1
    return months[cut:] if cut < len(months) else months[-1:]


def _row_date(row: dict) -> Optional[date]:
    """Filing date, tolerating both the parsed and the stored spellings."""
    for key in ("an_date", "an_dt", "sort_date"):
        value = row.get(key)
        if isinstance(value, date):
            return value
        if value:
            parsed = factors._parse_date_str(str(value))
            if parsed:
                return parsed
    return None


def load_announcements(db_path: Optional[Path] = None) -> list[dict]:
    """Every cached announcement, straight from factors.db.

    Read-only and read directly rather than through `fetch_announcements`,
    because this needs the whole history that is already stored and must never
    trigger a network fetch of its own.
    """
    path = db_path or factors.DB_PATH
    if not Path(path).exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT symbol, desc, attchmnt_text, an_dt, sort_date "
            "FROM announcements")
        # Renamed to the keys `factors.matches_orderbook` expects, so the shared
        # rule sees the same field spellings it does everywhere else.
        return [{"symbol": r[0], "desc": r[1], "attchmntText": r[2],
                 "an_dt": r[3], "sort_date": r[4]} for r in cur.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def market_intensity(rows: Optional[Iterable[dict]] = None, model=None,
                     today: Optional[date] = None) -> MarketIntensity:
    """The full market-level read, forecast included when a model is loaded."""
    out = MarketIntensity()
    rows = list(rows) if rows is not None else load_announcements()
    if not rows:
        out.error = "no cached announcements (run the scan's factor stage first)"
        return out

    months, counts, at_taxonomy_start = _series(rows, today=today)
    out.months, out.counts = months, counts
    out.n_filings = sum(counts)
    if len(counts) < MIN_MONTHS_TREND:
        out.error = (f"need {MIN_MONTHS_TREND} complete months to compare "
                     f"year on year, have {len(counts)}")
        return out

    out.latest_month = months[-1]
    out.latest_count = counts[-1]
    year_ago = counts[-1 - SEASON_MONTHS] if len(counts) > SEASON_MONTHS else None
    if year_ago:
        out.yoy_pct = round((counts[-1] - year_ago) / year_ago * 100.0, 1)
    out.trend = _classify(out.yoy_pct)

    if not out.can_forecast:
        short = MIN_MONTHS_SEASONAL_UNVALIDATED - len(counts)
        if at_taxonomy_start:
            # Nothing to fetch: the series already starts where NSE began
            # publishing the order-win subject categories. Saying "backfill
            # further" here would send a reader after data that does not exist.
            out.note = (
                f"trend only: a seasonal forecast needs {MIN_MONTHS_SEASONAL_UNVALIDATED} "
                f"months and there are {len(counts)}. The series starts at {months[0]} "
                f"because NSE's order-win announcement categories begin there -- "
                f"earlier months cannot be counted the same way, so this is "
                f"{short} month(s) of waiting, not of backfilling.")
        else:
            out.note = (f"trend only: a seasonal forecast needs {MIN_MONTHS_SEASONAL_UNVALIDATED} "
                        f"months and there are {len(counts)}. Backfill the "
                        f"announcement cache further to get one.")
        return out

    # Determine if the error band will be validated by backtest
    band_validated = len(counts) >= MIN_MONTHS
    out.band_validated = band_validated

    both = fc.forecast_series([float(c) for c in counts], STEPS,
                              season=SEASON_MONTHS, model=model,
                              label="order_filings_per_month")
    chosen = fc.pick(both)
    if chosen.ok:
        out.backend = chosen.backend
        out.forecast = chosen.good_path
        out.forecast_total = chosen.total("good")
        # For unvalidated forecasts, enhance the note with waiting time if applicable
        if not band_validated and not chosen.note:
            short_validated = MIN_MONTHS - len(counts)
            if at_taxonomy_start:
                out.note = (
                    f"seasonal (unvalidated band, {len(counts)} months): "
                    f"validated band needs {MIN_MONTHS} months "
                    f"({short_validated} month(s) of waiting)")
            else:
                out.note = (
                    f"seasonal (unvalidated band, {len(counts)} months): "
                    f"validated band needs {MIN_MONTHS} months")
        elif chosen.note:
            out.note = chosen.note
    if fc.BACKEND_TIMESFM in both:
        out.agreement = fc.level_agreement(both[fc.BACKEND_NAIVE],
                                           both[fc.BACKEND_TIMESFM])
    return out


def _classify(yoy_pct: Optional[float]) -> str:
    if yoy_pct is None:
        return TREND_UNKNOWN
    if yoy_pct >= RISING_PCT:
        return TREND_RISING
    if yoy_pct <= FALLING_PCT:
        return TREND_FALLING
    return TREND_FLAT


def context_note(intensity: MarketIntensity) -> str:
    """One line putting a single stock's order win in market context.

    The whole reason the series is computed: the same filing means something
    different depending on which of these three states the market is in.
    """
    if not intensity.ok:
        return ""
    if intensity.trend == TREND_RISING:
        return ("market-wide order flow is rising -- individual wins are part "
                "of a broad upcycle")
    if intensity.trend == TREND_FALLING:
        return ("market-wide order flow is falling -- a win here is against "
                "the tide, which makes it more company-specific, not less")
    return "market-wide order flow is flat"
