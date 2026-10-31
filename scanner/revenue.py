"""Forward revenue: forecast the quarterly series, then check it against the order book.

Two independent estimates of where revenue is going, and the gap between them is
the point of the module.

  model    the quarterly series extrapolated (seasonal-naive baseline, and
           TimesFM when one is loaded). Sees the pattern. Cannot see a contract
           signed last week.
  orders   order-book value divided over its execution period. Sees contracted
           future revenue directly, which is what an order book *is*.

If the order-backed estimate is far above the extrapolation, the company has won
work that its own revenue history does not yet reflect -- the most actionable
state this project can detect. If the two agree, new orders are merely replacing
completed ones and the backlog is flat, whatever the filing count says.

Why this matters for scoring: `significance` compares an order against
*trailing* revenue. That answers "was this order big relative to what the
company used to do". `forward_revenue()` supplies the other denominator -- big
relative to what it is about to do -- and a 500cr order against 400cr trailing
but 900cr forward revenue is a different proposition from the same order against
a company whose revenue is flat.

Everything here is derived, never authoritative: it is filed numbers put through
arithmetic, and it stays out of the ranking for the same reason the price
forecast does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from scanner import forecast as fc
from scanner import indicators

# Quarterly data, so a year is 4 points.
SEASON_QUARTERS = 4

# Three quarters ahead. With the fourth being the latest actual, that completes
# a forward year -- which is what makes a TTM comparison possible without
# forecasting further than a 13-point series can support.
STEPS = 3

# A quarterly series shorter than this cannot produce a seasonal baseline (two
# full years are needed to measure year-on-year drift at all).
MIN_QUARTERS = 2 * SEASON_QUARTERS + 1

# Order value counts toward forward revenue only if the filing says how long
# execution takes. Without that, a 2000cr order might land over 6 months or 6
# years, and the difference is the whole calculation. This is the default used
# when a filing is silent, flagged on the result so it is never mistaken for a
# disclosed figure.
DEFAULT_EXECUTION_MONTHS = 24

# Thresholds for the reconciliation verdict, as a percentage by which the
# order-backed estimate exceeds the extrapolation.
GAP_STRONG = 25.0
GAP_MILD = 10.0

VERDICT_ORDERS_AHEAD = "ORDERS_AHEAD"        # backlog not yet in the revenue line
VERDICT_CONFIRMS = "CONFIRMS"                # both estimates agree
VERDICT_ORDERS_BEHIND = "ORDERS_BEHIND"      # extrapolation outruns the backlog
VERDICT_NO_ORDERS = "NO_ORDER_DATA"
VERDICT_NO_MODEL = "NO_REVENUE_DATA"


@dataclass
class QuarterOutlook:
    """One forecast quarter, with both growth framings a reader wants."""

    step: int = 1
    value: Optional[float] = None
    qoq_pct: Optional[float] = None    # vs the latest actual quarter
    yoy_pct: Optional[float] = None    # vs the same quarter a year earlier
    bad: Optional[float] = None
    very_good: Optional[float] = None
    # How far the forecasting rule has typically missed at this step on this
    # company's own past quarters, as a percentage. Survives on far steps where
    # the band does not, which is the point of carrying it separately.
    dev_pct: Optional[float] = None

    def summary(self) -> str:
        if self.value is None:
            return ""
        parts = [f"Q+{self.step} {self.value:,.0f}"]
        if self.qoq_pct is not None:
            parts.append(f"QoQ {self.qoq_pct:+.0f}%")
        if self.yoy_pct is not None:
            parts.append(f"YoY {self.yoy_pct:+.0f}%")
        if self.dev_pct is not None:
            parts.append(f"+-{self.dev_pct:.0f}%")
        return " ".join(parts)


@dataclass
class RevenueOutlook:
    """Forecast quarters plus the trailing-vs-forward year comparison."""

    backend: str = ""
    latest_actual: Optional[float] = None
    quarters: list[QuarterOutlook] = field(default_factory=list)
    trailing_ttm: Optional[float] = None
    forward_ttm: Optional[float] = None
    forward_ttm_bad: Optional[float] = None
    forward_ttm_very_good: Optional[float] = None
    ttm_growth_pct: Optional[float] = None
    growth_pct_bad: Optional[float] = None
    growth_pct_very_good: Optional[float] = None
    # Typical miss on the forward-year figure itself, as a percentage of it, and
    # the same number expressed in rupees crore. Measured on the summed path, not
    # built up from the per-quarter deviations -- see `SeriesForecast`.
    ttm_dev_pct: Optional[float] = None
    ttm_dev_cr: Optional[float] = None
    n_history: int = 0
    note: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        """Whether there are numbers to report. A `note` does not make it false.

        The distinction is load-bearing. "Point forecast only" means the scenario
        bands could not be computed because the history is too short to backtest,
        and it arrives with every other number intact -- the predicted quarters,
        the QoQ and YoY comparisons, the forward TTM. Filing that as an error
        threw all of them away over a missing pair of optional columns.
        """
        return not self.error and bool(self.quarters)

    @property
    def has_scenarios(self) -> bool:
        """Whether the bad / good / very good bands are populated."""
        return any(q.bad is not None and q.very_good is not None
                   for q in self.quarters)

    def summary(self) -> str:
        if not self.quarters:
            return ""
        return " | ".join(q.summary() for q in self.quarters if q.value)


@dataclass
class OrderBacked:
    """Forward revenue implied by the order book alone.

    One assumption to be clear about, because it is the weak point of the whole
    calculation: `implied_forward_ttm` is `trailing + annualised`, which treats
    newly won orders as adding on top of a revenue run-rate that holds. For a
    business whose revenue *is* order execution -- EPC, capital goods, defence --
    that double-counts, because part of trailing revenue is older backlog now
    completing and being replaced rather than supplemented.

    So this figure is an upper bound, not a point estimate, and `book_to_bill` is
    the more robust reading: above 1 the backlog is growing whatever the
    additivity question, below 1 it is shrinking. The reconciliation verdict is
    interpreted with that in mind -- ORDERS_AHEAD is strong evidence, while
    ORDERS_BEHIND on an upper bound is stronger still, since even the generous
    reading of the book fails to reach the extrapolation.
    """

    order_count: int = 0
    total_value: Optional[float] = None          # rupees, all counted orders
    annualised: Optional[float] = None           # rupees per year in execution
    implied_forward_ttm: Optional[float] = None  # trailing TTM + annualised
    implied_growth_pct: Optional[float] = None
    book_to_bill: Optional[float] = None         # inflow / trailing revenue
    assumed_execution: int = 0                   # orders using the default
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.annualised is not None


@dataclass
class Reconciliation:
    """The comparison this module exists for."""

    verdict: str = VERDICT_NO_MODEL
    model_forward_ttm: Optional[float] = None
    order_forward_ttm: Optional[float] = None
    gap_pct: Optional[float] = None
    note: str = ""


# --- Management guidance -----------------------------------------------------
#
# A third forward estimate, and the only one that is neither a pattern nor a
# contract: a company stating a revenue target has put its credibility on it.
# That is why the *direction* of a revision matters more than the level. A
# reaffirmed target is a company meeting its plan; a raised one is a company
# whose plan turned out conservative; a lowered one is the single most useful
# negative disclosure in the set, and it is usually buried in an investor
# presentation rather than headlined.

GUIDANCE_RAISED = "RAISED"
GUIDANCE_NEW = "NEW"
GUIDANCE_REAFFIRMED = "REAFFIRMED"
GUIDANCE_LOWERED = "LOWERED"
GUIDANCE_WITHDRAWN = "WITHDRAWN"
GUIDANCE_NONE = "NONE"

# Directions that argue for the company, and against it.
_POSITIVE_GUIDANCE = {GUIDANCE_RAISED, GUIDANCE_NEW, GUIDANCE_REAFFIRMED}
_NEGATIVE_GUIDANCE = {GUIDANCE_LOWERED, GUIDANCE_WITHDRAWN}


@dataclass
class Guidance:
    """A forward number management has publicly committed to."""

    direction: str = GUIDANCE_NONE
    target_inr: Optional[float] = None    # absolute rupees for the period
    growth_pct: Optional[float] = None    # when stated as growth, not a level
    period: str = ""                      # "FY27", "next 3 years", as filed
    source_date: str = ""
    verbatim: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return (not self.error and self.direction != GUIDANCE_NONE
                and (self.target_inr is not None
                     or self.growth_pct is not None))

    def implied_forward_ttm(self, trailing: Optional[float]) -> Optional[float]:
        """Guidance expressed as a forward-year revenue figure.

        An absolute target is used as filed. A growth percentage is applied to
        trailing revenue, which is what management themselves are growing from.
        """
        if self.target_inr is not None and self.target_inr > 0:
            return float(self.target_inr)
        if (self.growth_pct is not None and trailing and trailing > 0):
            return round(trailing * (1 + self.growth_pct / 100.0), 2)
        return None


# --- Confluence flag ---------------------------------------------------------
#
# Guidance on its own is a claim. Price action on its own is a chart. The
# interesting cases are where they agree, and -- just as informative -- where
# they do not: a company raising guidance while its stock sits below both
# averages is either mispriced or not believed, and either way it is worth a
# human look. So the flag is not a filter, it is a highlight, and like every
# other forward-looking column here it stays out of the ranking.

FLAG_GREEN = "GREEN"       # guidance and tape agree, upward
FLAG_AMBER = "AMBER"       # they disagree, in either direction
FLAG_RED = "RED"           # guidance and tape agree, downward
FLAG_NONE = ""

# Trend labels come from scanner.indicators rather than being repeated here.
# It is a pure module with no I/O, so the import costs nothing, and copying the
# strings would let the two drift apart silently -- a flag that stopped firing
# because a label was renamed would look exactly like a flag with nothing to say.
_TREND_UPTREND = indicators.TREND_UPTREND
_TREND_BELOW_BOTH = indicators.TREND_BELOW_BOTH


@dataclass
class ConfluenceFlag:
    """Guidance direction set against the trend, with the reasoning kept."""

    level: str = FLAG_NONE
    reasons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.level:
            return ""
        return f"{self.level}: " + "; ".join(self.reasons)


def confluence_flag(guidance: Guidance, trend: Optional[str],
                    reconciliation: Optional[Reconciliation] = None
                    ) -> ConfluenceFlag:
    """Combine management guidance, price action, and the order book.

    Green needs both halves: a company arguing its revenue is going up *and* a
    tape that already agrees. Either alone is amber, because a raised target
    that the market ignores and a strong chart with no forward number are
    different kinds of incomplete.
    """
    flag = ConfluenceFlag()
    if not guidance.ok:
        return flag

    positive = guidance.direction in _POSITIVE_GUIDANCE
    negative = guidance.direction in _NEGATIVE_GUIDANCE
    uptrend = trend == _TREND_UPTREND
    broken = trend == _TREND_BELOW_BOTH

    detail = f"guidance {guidance.direction.lower()}"
    if guidance.period:
        detail += f" for {guidance.period}"
    if guidance.growth_pct is not None:
        detail += f" ({guidance.growth_pct:+.0f}%)"

    if positive and uptrend:
        flag.level = FLAG_GREEN
        flag.reasons = [detail, "price above 50 EMA and 200 DMA"]
    elif negative and broken:
        flag.level = FLAG_RED
        flag.reasons = [detail, "price below both averages"]
    elif positive and broken:
        flag.level = FLAG_AMBER
        flag.reasons = [detail, "but price below both averages -- not believed, "
                                "or not yet"]
    elif negative and uptrend:
        flag.level = FLAG_AMBER
        flag.reasons = [detail, "yet price still above both averages -- the "
                                "downgrade may not be priced in"]
    else:
        flag.level = FLAG_AMBER
        flag.reasons = [detail, f"trend {trend or 'unknown'}"]

    # The order book either corroborates the guidance or does not, and a raised
    # target with contracted work behind it is a materially stronger case than
    # the same target with nothing behind it.
    if reconciliation is not None and flag.level == FLAG_GREEN:
        if reconciliation.verdict == VERDICT_ORDERS_AHEAD:
            flag.reasons.append("order book runs ahead of revenue history")
        elif reconciliation.verdict == VERDICT_ORDERS_BEHIND:
            flag.level = FLAG_AMBER
            flag.reasons.append("but the disclosed order book does not yet "
                                "support it")
    return flag


def consensus(model: RevenueOutlook, orders: OrderBacked, guidance: Guidance
              ) -> dict:
    """All three forward-revenue estimates side by side.

    Deliberately not averaged into one number. They are built from different
    evidence with different reliability, and collapsing them would destroy the
    disagreement that makes them worth computing.
    """
    trailing = model.trailing_ttm
    return {
        "trailing_ttm": trailing,
        "model_forward_ttm": model.forward_ttm if model.ok else None,
        "model_growth_pct": model.ttm_growth_pct if model.ok else None,
        "order_forward_ttm": orders.implied_forward_ttm if orders.ok else None,
        "order_growth_pct": orders.implied_growth_pct if orders.ok else None,
        "book_to_bill": orders.book_to_bill if orders.ok else None,
        "guidance_forward_ttm": guidance.implied_forward_ttm(trailing),
        "guidance_direction": (guidance.direction if guidance.ok
                               else GUIDANCE_NONE),
        "guidance_period": guidance.period if guidance.ok else "",
    }


def _clean(values: Sequence) -> list[float]:
    """Numeric quarters only, oldest first.

    screener publishes some quarters as blanks or dashes; a missing quarter is
    dropped rather than zero-filled, because a zero would read as a quarter with
    no revenue and poison both the seasonal baseline and the drift.
    """
    out = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f:      # NaN
            continue
        out.append(f)
    return out


def trailing_ttm(quarters: Sequence[float]) -> Optional[float]:
    """Sum of the last four quarters, or None if there are not four."""
    vals = _clean(quarters)
    if len(vals) < SEASON_QUARTERS:
        return None
    return float(sum(vals[-SEASON_QUARTERS:]))


def forward_revenue(quarters: Sequence[float], model=None,
                    steps: int = STEPS) -> RevenueOutlook:
    """Forecast the next `steps` quarters and frame them QoQ, YoY and TTM.

    QoQ is against the latest actual quarter -- the comparison a reader makes
    instinctively, and the one that shows momentum.

    YoY is against the same quarter one year earlier, which is the honest
    comparison for a seasonal business: a March quarter beating the previous
    December quarter may be pure seasonality, while beating the previous March
    is growth.

    On `model`: the pipeline passes None, and the reason is a measurement rather
    than a preference. Holding out real quarters across 252 symbols, TimesFM's
    median absolute error was worse than the seasonal baseline's at every step
    -- 7.8% vs 6.7% one quarter out, 11.9% vs 7.6% at two, 18.2% vs 8.7% at
    three -- and nearly double on the forward-year figure, 9.4% vs 4.9%. Its
    10-90 band contained the actual only 45.7% of the time against a nominal
    80%, so the band that made `fc.pick` prefer it was itself miscalibrated, and
    preferring a banded backend selected the worse forecast on every symbol.

    Thirteen quarterly points is why. A model with a 512-step context window has
    almost nothing to read here, and what it produced was a strong
    mean-reversion prior: a median forward-year growth of 5.7% across companies
    whose realized trailing growth was 19.1%. The parameter is kept because the
    function is a library one and a longer series may well reverse this, but the
    finding should not be rediscovered the hard way.
    """
    vals = _clean(quarters)
    out = RevenueOutlook(n_history=len(vals))
    if len(vals) < MIN_QUARTERS:
        out.error = (f"need {MIN_QUARTERS} quarters for a seasonal forecast, "
                     f"have {len(vals)}")
        return out

    both = fc.forecast_series(vals, steps, season=SEASON_QUARTERS, model=model,
                              label="quarterly_revenue")
    chosen = fc.pick(both)
    if not chosen.ok:
        out.error = chosen.error or "no forecast"
        return out

    out.backend = chosen.backend
    out.latest_actual = vals[-1]
    n = len(vals)
    for band in chosen.steps:
        q = QuarterOutlook(step=band.step, value=band.good, bad=band.bad,
                           very_good=band.very_good, dev_pct=band.dev_pct)
        if band.good is not None and vals[-1] > 0:
            q.qoq_pct = round((band.good - vals[-1]) / vals[-1] * 100.0, 1)
        # Same quarter one year earlier: step k is 4 - k positions back from the
        # end for k <= 4 (step 1 compares against the quarter 3 back, and so on).
        idx = n - SEASON_QUARTERS + band.step - 1
        if band.good is not None and 0 <= idx < n and vals[idx] > 0:
            q.yoy_pct = round((band.good - vals[idx]) / vals[idx] * 100.0, 1)
        out.quarters.append(q)

    out.trailing_ttm = trailing_ttm(vals)
    # The forward year in each scenario: the latest actual quarter plus the three
    # forecast ones. This is why `steps` is 3 -- it completes a year without
    # forecasting a fourth quarter the series cannot support. The bad and very
    # good totals are the three outcomes at the horizon a reader actually cares
    # about, and they stay None when the history was too short to band.
    for which, ttm_attr, growth_attr in (
            ("good", "forward_ttm", "ttm_growth_pct"),
            ("bad", "forward_ttm_bad", "growth_pct_bad"),
            ("very_good", "forward_ttm_very_good", "growth_pct_very_good")):
        total = chosen.total(which)
        if total is None:
            continue
        forward = round(vals[-1] + total, 4)
        setattr(out, ttm_attr, forward)
        if out.trailing_ttm and out.trailing_ttm > 0:
            setattr(out, growth_attr,
                    round((forward - out.trailing_ttm) / out.trailing_ttm
                          * 100.0, 1))
    # Deviation of the forward year. The measured percentage applies to the
    # forecast part of it only: three of these four quarters are predicted and the
    # fourth is an actual already on the books, which carries no error at all.
    # So the rupee miss is that percentage of the forecast three, and restating it
    # against the full-year figure gives a smaller percentage than the raw one --
    # correctly, because a quarter of the total is known. Applying the raw
    # percentage to the whole year would overstate the uncertainty by about a
    # third, which for a company whose latest quarter is unusually large is not a
    # rounding difference.
    if chosen.total_dev_pct is not None and out.forward_ttm:
        forecast_part = out.forward_ttm - vals[-1]
        dev_cr = abs(forecast_part) * chosen.total_dev_pct / 100.0
        out.ttm_dev_cr = round(dev_cr, 4)
        out.ttm_dev_pct = round(dev_cr / out.forward_ttm * 100.0, 2)
    # A caveat, not a failure: "point forecast only", when the history is too
    # short to backtest scenario bands. It arrives with every other number
    # intact, so it belongs in `note` -- recording it as `error` would make
    # `ok` false and discard a complete set of usable figures.
    out.note = chosen.note
    return out


def order_backed(orders: Sequence[dict], trailing: Optional[float],
                 default_months: int = DEFAULT_EXECUTION_MONTHS) -> OrderBacked:
    """Forward revenue implied by won orders spread over their execution period.

    `orders` are dicts with `value` in rupees and optionally `execution_months`
    -- the shape `scanner.llm`'s order extraction already produces, so no
    re-running of inference is needed to get this.

    An order contributes `value / (execution_months / 12)` per year. A 2000cr
    order over 24 months is 1000cr a year, and a 2000cr order over 6 months is
    4000cr a year: the same headline number meaning very different things, which
    is exactly why filings are required to state the period and why a silent one
    is flagged rather than quietly assumed away.
    """
    out = OrderBacked()
    counted = 0
    total = 0.0
    annual = 0.0
    for o in orders or []:
        value = o.get("value")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        months = o.get("execution_months")
        try:
            months = int(months)
        except (TypeError, ValueError):
            months = 0
        if months <= 0:
            months = default_months
            out.assumed_execution += 1
        counted += 1
        total += value
        annual += value / (months / 12.0)

    out.order_count = counted
    if not counted:
        out.error = "no order values available"
        return out
    out.total_value = round(total, 2)
    out.annualised = round(annual, 2)
    if trailing and trailing > 0:
        out.implied_forward_ttm = round(trailing + annual, 2)
        out.implied_growth_pct = round(annual / trailing * 100.0, 1)
        # Book-to-bill above 1 means the company is winning work faster than it
        # is billing it -- a growing backlog, which is the standard reading.
        out.book_to_bill = round(total / trailing, 2)
    else:
        out.error = "no trailing revenue to compare against"
    return out


def reconcile(model: RevenueOutlook, orders: OrderBacked) -> Reconciliation:
    """Does the order book support the extrapolation, outrun it, or lag it?"""
    rec = Reconciliation()
    if not model.ok or model.forward_ttm is None:
        rec.verdict = VERDICT_NO_MODEL
        rec.note = model.error or "no revenue forecast"
        return rec
    rec.model_forward_ttm = model.forward_ttm
    if not orders.ok or orders.implied_forward_ttm is None:
        rec.verdict = VERDICT_NO_ORDERS
        rec.note = orders.error or "no order-backed estimate"
        return rec
    rec.order_forward_ttm = orders.implied_forward_ttm
    rec.gap_pct = round(
        (orders.implied_forward_ttm - model.forward_ttm)
        / model.forward_ttm * 100.0, 1)

    if rec.gap_pct >= GAP_STRONG:
        rec.verdict = VERDICT_ORDERS_AHEAD
        rec.note = ("order book implies revenue well above what the history "
                    "extrapolates; the wins are not in the revenue line yet")
    elif rec.gap_pct <= -GAP_STRONG:
        rec.verdict = VERDICT_ORDERS_BEHIND
        rec.note = ("extrapolation outruns the disclosed order book; growth is "
                    "assumed rather than contracted")
    elif abs(rec.gap_pct) <= GAP_MILD:
        rec.verdict = VERDICT_CONFIRMS
        rec.note = "order book and history agree on forward revenue"
    else:
        rec.verdict = (VERDICT_ORDERS_AHEAD if rec.gap_pct > 0
                       else VERDICT_ORDERS_BEHIND)
        rec.note = "mild divergence"
    if orders.assumed_execution:
        rec.note += (f" ({orders.assumed_execution} order(s) used the "
                     f"{DEFAULT_EXECUTION_MONTHS}-month default period)")
    return rec
