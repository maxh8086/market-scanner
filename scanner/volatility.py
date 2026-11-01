"""Realized volatility and its regime, from closes already in the cache.

Why this and not price direction: daily returns are close to unforecastable, but
their *magnitude* is not. Volatility clusters -- a violent week is followed by a
violent week far more often than chance allows -- and that autocorrelation is
real, measurable, and exactly what a sequence model can exploit. So the same
machinery that says nothing useful about tomorrow's price says something useful
about tomorrow's turbulence.

What it is for, concretely. Every stock in this scan is at or near an all-time
high, and that happens in two very different ways: a steady grind up in a calm
tape, or a vertical move in a violent one. The first tends to persist, the second
tends to resolve sharply in whichever direction. Same distance-from-ATH, entirely
different risk, and nothing else in the pipeline distinguishes them.

The regime label is about the *change* in volatility, not its level. A stock that
is always volatile is not news; a normally quiet stock whose volatility has
doubled is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from scanner import forecast as fc
from scanner import indicators

# 21 trading days ~ one month. Short enough to react to a regime change, long
# enough that a single gap day does not dominate the estimate.
VOL_WINDOW = 21

# Annualisation factor for daily volatility: ~252 NSE trading days a year.
TRADING_DAYS_YEAR = 252

# Forecast one window ahead. Further out adds nothing -- volatility mean-reverts,
# so a 6-month volatility forecast converges on the long-run average and stops
# being a statement about this stock.
STEPS = 1

# Enough closes for a stable series of rolling estimates plus a backtest of the
# baseline: roughly a year of windows.
MIN_CLOSES = VOL_WINDOW + 60

# Regime thresholds, as a ratio of recent volatility to its own longer-run level.
EXPANDING = 1.30
CONTRACTING = 0.77      # ~1/1.30, so the two are symmetric in log terms

# Annualised volatility below this is treated as immeasurable rather than small.
# A perfectly smooth series has a variance of pure floating-point noise -- around
# 1e-15 once annualised -- and dividing one noise value by another produces a
# ratio that looks like a regime change and means nothing. Real equity
# volatility never approaches this floor, so nothing genuine is discarded.
VOL_FLOOR = 0.01

REGIME_EXPANDING = "EXPANDING"
REGIME_STABLE = "STABLE"
REGIME_CONTRACTING = "CONTRACTING"
REGIME_UNKNOWN = "UNKNOWN"

# Percentile of the stock's own volatility history that counts as unusually high
# or low. Compared against itself, never against another stock -- a 60% vol is
# ordinary for a smallcap and an emergency for a large one.
HIGH_PERCENTILE = 80.0
LOW_PERCENTILE = 20.0

# Relative tolerance for calling two volatility readings equal when ranking.
# Loose enough to absorb float noise, far tighter than any difference a reader
# would notice: 1e-9 on a 30% volatility is 3e-8 of a percentage point.
_TIE_TOL = 1e-9


@dataclass
class VolState:
    """Current volatility, where it sits in this stock's own history, and next."""

    current: Optional[float] = None         # annualised %, last full window
    baseline: Optional[float] = None        # median of the whole vol series
    ratio: Optional[float] = None           # current / baseline
    percentile: Optional[float] = None      # of current within its own history
    regime: str = REGIME_UNKNOWN
    forecast: Optional[float] = None        # next window, central
    forecast_bad: Optional[float] = None    # high-volatility scenario
    forecast_low: Optional[float] = None
    backend: str = ""
    n_observations: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.current is not None

    @property
    def unusually_high(self) -> Optional[bool]:
        if self.percentile is None:
            return None
        return self.percentile >= HIGH_PERCENTILE

    @property
    def unusually_low(self) -> Optional[bool]:
        if self.percentile is None:
            return None
        return self.percentile <= LOW_PERCENTILE

    def summary(self) -> str:
        if not self.ok:
            return ""
        bits = [f"{self.current:.0f}% vol"]
        if self.ratio is not None:
            bits.append(f"{self.ratio:.2f}x baseline")
        bits.append(self.regime.lower())
        if self.forecast is not None:
            bits.append(f"-> {self.forecast:.0f}%")
        return ", ".join(bits)


def log_returns(closes: Sequence[float]) -> list[float]:
    """Daily log returns, skipping non-positive or missing closes.

    Log rather than simple returns because they are additive across days, which
    is what makes the square-root-of-time annualisation below correct.
    """
    vals = [float(c) for c in closes if c is not None and float(c) > 0]
    return [math.log(vals[i + 1] / vals[i]) for i in range(len(vals) - 1)]


def realized_vol_series(closes: Sequence[float], window: int = VOL_WINDOW
                        ) -> list[float]:
    """Rolling annualised realized volatility, as a percentage.

    Standard deviation of daily log returns over `window` days, scaled by
    sqrt(252). Returns one value per complete window, oldest first.
    """
    rets = log_returns(closes)
    if len(rets) < window:
        return []
    scale = math.sqrt(TRADING_DAYS_YEAR) * 100.0
    out = []
    for i in range(window, len(rets) + 1):
        chunk = rets[i - window:i]
        # Population stdev: this is a realized measure over a fixed window, not
        # an inference about a wider sample.
        mean = sum(chunk) / window
        var = sum((r - mean) ** 2 for r in chunk) / window
        out.append(math.sqrt(var) * scale)
    return out


def _percentile_of(values: Sequence[float], target: float) -> float:
    """Where `target` sits within `values`, as a percentage.

    Midpoint rank -- ties count half -- rather than "fraction at or below". The
    naive version counts the current value as below itself, so a stock whose
    volatility never changes would report the 100th percentile and read as
    extreme when it is exactly typical. Midpoint rank gives it 50, which is the
    truthful answer.

    Ties are compared with a tolerance rather than `==`, for the same reason.
    Volatilities that are equal by construction still differ in the last float
    bits once compounding and a square root have been applied, so exact equality
    finds no ties at all and a genuinely flat series reports the 84th percentile
    instead of the 50th -- the bug this function was written to avoid, reached by
    a different route.
    """
    if not values:
        return 0.0
    below = sum(1 for v in values
                if v < target and not math.isclose(v, target, rel_tol=_TIE_TOL))
    equal = sum(1 for v in values
                if math.isclose(v, target, rel_tol=_TIE_TOL))
    return round((below + 0.5 * equal) / len(values) * 100.0, 1)


def classify_regime(ratio: Optional[float]) -> str:
    if ratio is None:
        return REGIME_UNKNOWN
    if ratio >= EXPANDING:
        return REGIME_EXPANDING
    if ratio <= CONTRACTING:
        return REGIME_CONTRACTING
    return REGIME_STABLE


def vol_state(closes: Sequence[float], model=None, window: int = VOL_WINDOW
              ) -> VolState:
    """Full volatility read for one symbol, forecast included when a model is on.

    The forecast is deliberately secondary. Even without any model, `regime` and
    `percentile` carry most of the value here, because they are measurements
    rather than predictions.
    """
    state = VolState()
    vals = [float(c) for c in closes if c is not None and float(c) > 0]
    if len(vals) < MIN_CLOSES:
        state.error = f"need {MIN_CLOSES} closes, have {len(vals)}"
        return state

    series = realized_vol_series(vals, window)
    if not series:
        state.error = "no volatility observations"
        return state

    # Raw values for the arithmetic, rounded ones only for display. Rounding the
    # baseline first and then dividing by it turned a 1e-15 median into 0.00 and
    # sent a perfectly smooth series down the "volatility appeared" branch.
    raw_current = series[-1]
    raw_baseline = _median(series)
    state.n_observations = len(series)
    state.current = round(raw_current, 2)
    state.baseline = round(raw_baseline, 2)

    if raw_baseline > VOL_FLOOR:
        state.ratio = round(raw_current / raw_baseline, 2)
        state.regime = classify_regime(state.ratio)
    elif raw_current > VOL_FLOOR:
        # The stock had no measurable volatility and now has some. The ratio is
        # undefined, but the direction is not, and UNKNOWN here would hide the
        # clearest expansion there is.
        state.regime = REGIME_EXPANDING
    else:
        # Both below the floor: nothing measurable is happening either way.
        state.regime = REGIME_STABLE
    state.percentile = _percentile_of(series, raw_current)

    if model is not None:
        # This is the one series here a model measurably improves, and the reason
        # is the one the module docstring gives: volatility clusters, so its
        # magnitude really is autocorrelated. Held out one window ahead at three
        # origins over 273 symbols, TimesFM's median absolute error was 1.5%
        # against the baseline's 2.7%, and it won at the mean (3.2 vs 4.2) and the
        # 90th percentile (8.1 vs 9.7) too, on 814 observations.
        #
        # The contrast with quarterly revenue is the useful part: there the same
        # model lost at every step, and the difference is context. This series
        # hands it 200-plus rolling observations; that one hands it 13 points
        # against a 512-step window. So `--timesfm` is worth its runtime here and
        # is deliberately not used there -- see `revenue.forward_revenue`.
        # Monthly order intensity sits between the two and has not been measured.
        #
        # No season: volatility has no calendar cycle worth modelling at a daily
        # frequency, so the baseline here is persistence with drift -- which is
        # the classic hard-to-beat volatility benchmark, not a soft target.
        both = fc.forecast_series(series, STEPS, season=None, model=model,
                                  label="realized_vol")
        chosen = fc.pick(both)
        if chosen.ok and chosen.steps:
            band = chosen.steps[0]
            state.backend = chosen.backend
            state.forecast = round(band.good, 2) if band.good else None
            # For volatility the *high* scenario is the bad one, so the naming
            # is inverted relative to a price band on purpose.
            state.forecast_bad = (round(band.very_good, 2)
                                  if band.very_good is not None else None)
            state.forecast_low = (round(band.bad, 2)
                                  if band.bad is not None else None)
    return state


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def breakout_quality(state: VolState, trend: Optional[str]) -> str:
    """How a move to an all-time high is happening, not just that it happened.

    A contracting or stable volatility regime in an uptrend is the textbook
    orderly breakout. An expanding one at the same price is a move that is
    running hot, which may continue but carries a much wider range of outcomes.
    This is a description, not a prediction, and it is the honest use of a
    volatility estimate.
    """
    if not state.ok or trend is None:
        return ""
    if trend != indicators.TREND_UPTREND:
        return ""
    if state.regime == REGIME_EXPANDING or state.unusually_high:
        return "HOT"
    if state.regime == REGIME_CONTRACTING or state.unusually_low:
        return "ORDERLY"
    return "NORMAL"
