"""Three-scenario outlook over a ~3-month horizon: bad / good / very good.

Presented as quantiles of a predictive distribution rather than a single number,
because a point forecast of a stock price hides exactly the thing that matters.
p10 is the bad case, p50 the central one, p90 the good one.

Two backends, and the honest reason for both:

  empirical  the distribution of this stock's own past `horizon`-day returns.
             No model, no dependency, no training data. It is what the stock has
             actually done.
  timesfm    Google's time-series foundation model, via its quantile heads.

`scenarios()` can run both. If TimesFM's band matches the empirical one it is
adding nothing, and that is worth knowing before trusting it; if it differs, the
difference is its actual contribution. Reporting only the model would make that
impossible to tell.

A caveat that belongs in the code and not just in conversation: daily equity
closes over ~63 trading days are close to a random walk. Both backends will
centre near the current price, and the informative output is the **width** of
the band, which is a volatility estimate, not a direction call. Nothing here
feeds the ranking -- `significance` ranks on filed numbers, and a forecast
column that moved the ranking would be worse than no column.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional, Sequence

# Horizons in NSE *trading* days, ~21 per month. 63 trading days is ~3 calendar
# months (~90 calendar days), 126 is ~6 months. Nothing here prefers one: the
# horizon is a parameter, and `multi_horizon()` runs several, because how the
# band widens with horizon says more than any single band.
HORIZON_1M = 21
HORIZON_3M = 63
HORIZON_6M = 126
HORIZON_DAYS = HORIZON_3M          # default
HORIZONS = (HORIZON_1M, HORIZON_3M, HORIZON_6M)

# Quantiles behind the three labels.
Q_BAD = 0.10
Q_GOOD = 0.50
Q_VERY_GOOD = 0.90

BACKEND_EMPIRICAL = "empirical"
BACKEND_TIMESFM = "timesfm"

# Overlapping windows are the trap in this method. 750 closes give 624
# overlapping 126-day returns but only 5 non-overlapping ones, so a p10 computed
# from them rests on 5 real observations however many samples the count claims.
# This is the floor on *independent* windows, and `independent_windows` on the
# result reports the actual number so a thin estimate is visible rather than
# implied.
MIN_INDEPENDENT_WINDOWS = 8


def min_history(horizon: int = HORIZON_DAYS) -> int:
    """Closes needed for a defensible estimate at this horizon.

    Scales with the horizon: a 6-month band needs roughly twice the history a
    3-month band does, for the same statistical weight.
    """
    return MIN_INDEPENDENT_WINDOWS * horizon + 1


# Kept as a module constant for the default horizon, since callers reference it.
MIN_HISTORY = min_history(HORIZON_DAYS)


@dataclass
class Outlook:
    """Three scenarios as percentage changes from the current price."""

    backend: str = ""
    horizon: int = HORIZON_DAYS
    bad_pct: Optional[float] = None
    good_pct: Optional[float] = None
    very_good_pct: Optional[float] = None
    independent_windows: Optional[int] = None
    note: str = ""
    error: str = ""

    @property
    def band_width_pct(self) -> Optional[float]:
        """p90 - p10. The volatility estimate, and the only part of a ~63-day
        equity forecast that carries much information."""
        if self.bad_pct is None or self.very_good_pct is None:
            return None
        return self.very_good_pct - self.bad_pct

    @property
    def has_band(self) -> bool:
        """Whether the bad / very good scenarios are populated, not just the
        central one. `ok` says there is something to report; this says how much
        of it there is."""
        return self.bad_pct is not None and self.very_good_pct is not None

    @property
    def ok(self) -> bool:
        """Whether there is a number to report. A `note` does not make it false.

        `error` means nothing came back. `note` means something optional did
        not -- a central estimate with no interval around it. Those need
        separate fields because callers gate on `ok`, and filing a caveat as an
        error throws away the central estimate along with the missing band.
        """
        return not self.error and self.good_pct is not None

    @property
    def months(self) -> float:
        """Horizon in calendar months, at ~21 trading days each -- so a reader
        is never left converting 63 into 3 in their head."""
        return round(self.horizon / 21.0, 1)

    def summary(self) -> str:
        if not self.ok:
            return ""
        # `ok` without `has_band` is now reachable -- a point forecast whose
        # quantiles were unusable. Formatting None with :+.0f would raise, and
        # the honest rendering is the one number there is.
        if not self.has_band:
            return f"{self.good_pct:+.0f}% (no band)"
        return (f"{self.bad_pct:+.0f}% / {self.good_pct:+.0f}% / "
                f"{self.very_good_pct:+.0f}%")


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile. Written out rather than pulled from numpy
    so this module stays importable with no dependencies."""
    if not sorted_values:
        raise ValueError("no values")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return float(sorted_values[low] * (1 - frac) + sorted_values[high] * frac)


def _from_quantile_grid(levels: Sequence[float], q: float) -> float:
    """Read quantile `q` off a model's quantile *grid*.

    `levels` are already quantile forecasts, not samples, so `_quantile` is the
    wrong tool for them -- it would treat q10..q90 as nine observations and
    return roughly q18 when asked for p10. TimesFM emits n levels at
    q_i = (i+1)/(n+1), which for its documented n=9 is exactly 0.1..0.9, so p10
    is levels[0] and p90 is levels[8].

    Outside the grid this clamps rather than extrapolating: a model that only
    published q25..q75 cannot tell us its p10, and returning its q25 understates
    the tail, where an extrapolated value would be invented. The caller can see
    this happened because the requested q lies outside the grid it was given.
    """
    values = sorted(float(x) for x in levels)
    n = len(values)
    if n == 0:
        raise ValueError("no quantile levels")
    if n == 1:
        return values[0]
    grid = [(i + 1) / (n + 1) for i in range(n)]
    if q <= grid[0]:
        return values[0]
    if q >= grid[-1]:
        return values[-1]
    for i in range(n - 1):
        if grid[i] <= q <= grid[i + 1]:
            span = grid[i + 1] - grid[i]
            frac = (q - grid[i]) / span if span else 0.0
            return values[i] * (1 - frac) + values[i + 1] * frac
    return values[-1]


def horizon_returns(closes: Sequence[float], horizon: int = HORIZON_DAYS
                    ) -> list[float]:
    """Every overlapping `horizon`-day percentage return in the series.

    Overlapping windows are correlated, so these are not independent samples --
    fine for describing the shape of past outcomes, not for a significance test.
    """
    values = [float(c) for c in closes if c is not None and float(c) > 0]
    if len(values) < horizon + 1:
        return []
    return [(values[i + horizon] - values[i]) / values[i] * 100.0
            for i in range(len(values) - horizon)]


def empirical_outlook(closes: Sequence[float], horizon: int = HORIZON_DAYS
                      ) -> Outlook:
    """Scenarios from the stock's own history. No model involved."""
    out = Outlook(backend=BACKEND_EMPIRICAL, horizon=horizon)
    needed = min_history(horizon)
    if len(closes) < needed:
        out.independent_windows = len(closes) // horizon if horizon else 0
        out.error = (f"need {needed} closes for a {horizon}-day horizon "
                     f"({MIN_INDEPENDENT_WINDOWS} independent windows), "
                     f"have {len(closes)}")
        return out
    returns = sorted(horizon_returns(closes, horizon))
    if not returns:
        out.error = "no usable returns"
        return out
    out.independent_windows = len(closes) // horizon
    out.bad_pct = round(_quantile(returns, Q_BAD), 1)
    out.good_pct = round(_quantile(returns, Q_GOOD), 1)
    out.very_good_pct = round(_quantile(returns, Q_VERY_GOOD), 1)
    return out


def multi_horizon(closes: Sequence[float], horizons: Sequence[int] = HORIZONS
                  ) -> dict[int, Outlook]:
    """Empirical scenarios at several horizons over the same series.

    Free to compute, and the comparison is the point: a band that widens roughly
    with the square root of the horizon is behaving like a random walk, which is
    the null hypothesis worth seeing stated. One that widens much faster is a
    stock whose longer-term outcomes are genuinely more dispersed.
    """
    return {h: empirical_outlook(closes, h) for h in horizons}


def timesfm_outlook(closes: Sequence[float], horizon: int = HORIZON_DAYS,
                    model=None) -> Outlook:
    """Scenarios from TimesFM's quantile heads.

    `model` is a loaded TimesFM instance -- loading it per symbol would dominate
    the runtime, so the caller loads once via `load_timesfm()` and passes it in.

    TimesFM's API has changed across releases and its quantile output is
    explicitly experimental, so the extraction is defensive: any shape it does
    not recognise becomes an error on the result rather than an exception that
    kills a 300-symbol run.
    """
    out = Outlook(backend=BACKEND_TIMESFM, horizon=horizon)
    if model is None:
        out.error = "no model passed (call load_timesfm first)"
        return out
    values = [float(c) for c in closes if c is not None and float(c) > 0]
    if len(values) < min_history(horizon):
        out.error = (f"need {min_history(horizon)} closes for a "
                     f"{horizon}-day horizon, have {len(values)}")
        return out

    last = values[-1]
    try:
        point, quantiles = model.forecast(horizon=horizon, inputs=[values])
    except Exception as e:  # noqa: BLE001
        out.error = f"forecast failed: {type(e).__name__}: {e}"
        return out

    try:
        # Expected shape (1, horizon, 1 + n_quantiles): index 0 is the mean,
        # then the quantiles in ascending order (q10..q90 for 9 of them).
        series = quantiles[0]
        final = series[min(horizon, len(series)) - 1]
        levels = list(final)[1:]
        if len(levels) < 3:
            raise ValueError(f"only {len(levels)} quantile levels")
        picks = [_from_quantile_grid(levels, q)
                 for q in (Q_BAD, Q_GOOD, Q_VERY_GOOD)]
    except Exception as e:  # noqa: BLE001
        # Fall back to the point forecast: a central scenario with no band is
        # still truthful, where a fabricated band would not be.
        try:
            centre = float(point[0][min(horizon, len(point[0])) - 1])
        except Exception:  # noqa: BLE001
            out.error = f"unrecognised output shape: {type(e).__name__}: {e}"
            return out
        out.good_pct = round((centre - last) / last * 100.0, 1)
        # A note, not an error: the comment above says the central scenario is
        # still truthful, and `error` would make `ok` false and discard it.
        out.note = f"no quantiles ({e}); point forecast only"
        return out

    out.bad_pct = round((picks[0] - last) / last * 100.0, 1)
    out.good_pct = round((picks[1] - last) / last * 100.0, 1)
    out.very_good_pct = round((picks[2] - last) / last * 100.0, 1)
    return out


def load_timesfm(horizon: int = HORIZON_DAYS):
    """Load and compile TimesFM once for a whole run, or return (None, reason).

    Imported lazily and never at module scope: everything else here works with
    no dependencies, and an optional forecast must not make the scanner
    unimportable on a machine without torch.

    One compiled model serves every caller here, which is why `max_horizon`
    covers the longest horizon rather than the one being asked for now -- the
    daily outlook wants 63 steps and the quarterly and monthly series want 3,
    and compiling per caller would pay the setup cost several times over for
    nothing. Asking a compiled model for fewer steps than `max_horizon` is
    fine; asking for more is not, hence the floor.

    The three flags are not defaults and each one earns its place:
    `normalize_inputs` because these series run from a Rs 200 cr quarter to a
    Rs 67,000 cr one and the config's own docs warn about magnitude;
    `use_continuous_quantile_head` because collapsed quantiles are a band of
    zero width reported as if it were a real one; and `fix_quantile_crossing`
    because a band that crosses puts the pessimistic case above the optimistic
    one, which `LevelBand` has no way to represent honestly.
    """
    try:
        import timesfm
    except ImportError as e:
        return None, (f"timesfm not installed ({e}). "
                      f"pip install timesfm[torch] -- CPU is fine, the "
                      f"200M checkpoint needs no GPU.")
    try:
        cls = timesfm.TimesFM_2p5_200M_torch
        model = cls.from_pretrained(cls.DEFAULT_REPO_ID)
        model.compile(timesfm.ForecastConfig(
            max_context=MAX_CONTEXT,
            max_horizon=max(horizon, MAX_LEVEL_STEPS),
            normalize_inputs=True,
            use_continuous_quantile_head=True,
            fix_quantile_crossing=True,
        ))
        return model, f"loaded {cls.DEFAULT_REPO_ID}"
    except Exception as e:  # noqa: BLE001 - API varies across releases
        return None, f"load failed: {type(e).__name__}: {e}"


def scenarios(closes: Sequence[float], horizon: int = HORIZON_DAYS,
              timesfm_model=None) -> dict[str, Outlook]:
    """Both backends at one horizon, so they can be compared rather than
    trusted blindly."""
    out = {BACKEND_EMPIRICAL: empirical_outlook(closes, horizon)}
    if timesfm_model is not None:
        out[BACKEND_TIMESFM] = timesfm_outlook(closes, horizon, timesfm_model)
    return out


# ---------------------------------------------------------------------------
# Level forecasting: the next k values of a series, not its returns.
#
# `Outlook` above answers "what return might this price produce?". Revenue,
# volatility and filing counts need a different question -- "what will the next
# few *values* be?" -- so they get their own primitive rather than being bent
# through a returns model.
#
# Every level forecast carries a free baseline it has to beat. Seasonal-naive
# with drift is not a strawman: on short business series it is genuinely hard to
# beat, and without it there is no way to tell whether TimesFM contributed
# anything. Its band comes from backtesting the rule against its own history,
# so the interval is that rule's measured error rather than an assumption.
# ---------------------------------------------------------------------------

BACKEND_NAIVE = "seasonal_naive"

# What one compiled TimesFM can be asked for. `max_context` is how much history
# it reads -- 512 daily closes is two years, and the level series here are
# shorter than that by an order of magnitude. `MAX_LEVEL_STEPS` is the ceiling on
# `steps` across every level caller (revenue and intensity want 3, volatility 1),
# and it exists so `load_timesfm` can compile once for all of them.
#
# There is no frequency setting. TimesFM 2.5 dropped the `freq` input that 2.0
# took, so the series' cadence is not something to tell the model any more -- it
# is inferred. Three modules here used to pick a value for it.
MAX_CONTEXT = 512
MAX_LEVEL_STEPS = 8

# A drift multiplier beyond this is treated as a one-off, not a trend. A company
# that tripled revenue year on year did not begin tripling it every year, and
# projecting that forward produces a denominator so large it hides every real
# signal. Damping is wrong in a known direction; extrapolating is wrong in an
# unknown one.
MAX_DRIFT = 2.0
MIN_DRIFT = 0.5

# Fewer backtest errors than this and the band is not reported. The point
# forecast still is -- a central estimate with no interval is honest, a band
# built from two observations is not.
MIN_BACKTEST_ERRORS = 4

# Fewer errors than this and the *deviation* is not reported either. Lower than
# MIN_BACKTEST_ERRORS on purpose, and the difference is the whole point: the band
# needs the 10th and 90th percentiles of the error distribution, and a tail
# quantile from three observations is fiction. The deviation is the median of the
# absolute errors -- a central tendency, which is the one statistic three
# observations can support.
#
# The gap between the two thresholds is where this measure earns its place. With
# 13 quarters of sales, step 3 has exactly 3 past errors: not enough for a band,
# enough for "this rule has typically been off by 9% three steps out". That
# sentence is what a reader actually wanted from the empty band column.
#
# It was checked out-of-sample before being reported, because a plausible
# construction is not evidence. Over 502 held-out quarters the rank correlation
# between the deviation measured from history alone and the error the forecast
# then actually made was +0.49, and by tertile the claimed figures of 2.8%, 7.1%
# and 18.2% were followed by realized median errors of 4.7%, 7.2% and 15.3%. So
# it orders symbols by reliability and is roughly calibrated in level.
#
# Its known weakness, which the median makes unavoidable: it describes typical
# misses and badly understates rare ones. The worst held-out case claimed 34%
# and missed by 472% -- a restatement or a one-off quarter that no measure of
# past dispersion anticipates. Read as "how noisy this line normally is", not as
# a bound.
MIN_DEV_ERRORS = 3


@dataclass
class LevelBand:
    """One step ahead: the three scenarios as absolute values of the series."""

    step: int = 1
    bad: Optional[float] = None
    good: Optional[float] = None
    very_good: Optional[float] = None
    # How far this rule has typically missed at this step, as a percentage of
    # the value it predicted: the median of its own absolute walk-forward
    # errors. Distinct from the band, and not derivable from it -- the band is
    # where the *outcome* might land, this is how much to trust the arrow.
    dev_pct: Optional[float] = None
    n_errors: int = 0

    @property
    def ok(self) -> bool:
        return self.good is not None

    @property
    def has_band(self) -> bool:
        return self.bad is not None and self.very_good is not None


@dataclass
class SeriesForecast:
    """A forecast of the next `len(steps)` values of one series."""

    backend: str = ""
    label: str = ""
    season: Optional[int] = None
    n_history: int = 0
    steps: list[LevelBand] = field(default_factory=list)
    # Deviation of the *summed* path, for callers that use `total()`. Measured
    # directly on the sum at each past origin rather than combined from the
    # per-step deviations, because errors at consecutive steps are correlated --
    # a rule that underestimates one quarter usually underestimates the next --
    # and adding them as if they were independent understates the real miss while
    # adding them as if they were identical overstates it. Measuring the thing
    # being reported avoids having to choose.
    total_dev_pct: Optional[float] = None
    note: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        """Whether there is a central path to report. A `note` does not make it
        false -- see `Outlook.ok`, which draws the same line for the same
        reason. `MIN_BACKTEST_ERRORS` documents that a point forecast without a
        band is still reported; that only holds if the caveat lives in `note`.
        """
        return not self.error and bool(self.steps) and self.steps[0].ok

    @property
    def has_band(self) -> bool:
        """Whether the scenario bands were computable, not just the central
        path. A caller that needs three outcomes gates on this; one that needs a
        number gates on `ok`.

        Judged on the first step, because the bands thin out with distance -- a
        backtest has more observations of a one-step error than of a three-step
        one, so the far steps lose their band first. Step one is the one every
        caller uses and the one a reader weighs most.
        """
        return bool(self.steps) and self.steps[0].has_band

    @property
    def good_path(self) -> list[Optional[float]]:
        return [s.good for s in self.steps]

    def total(self, which: str = "good") -> Optional[float]:
        """Sum of one scenario across every step.

        The reason this exists: four quarters summed is a TTM figure, which is
        the denominator significance scoring actually wants.
        """
        values = [getattr(s, which) for s in self.steps]
        if not values or any(v is None for v in values):
            return None
        return float(sum(values))


def _drift(values: Sequence[float], season: int) -> float:
    """Growth of the last `season` values over the `season` before them.

    Summed rather than averaged point-to-point because for revenue this is
    exactly TTM-over-prior-TTM growth, which is the figure a reader already has
    in mind, and because summing is far less sensitive to one lumpy quarter.
    """
    n = len(values)
    if n < 2 * season:
        return 1.0
    recent = sum(values[n - season:])
    prior = sum(values[n - 2 * season:n - season])
    if prior <= 0 or recent <= 0:
        return 1.0
    return max(MIN_DRIFT, min(MAX_DRIFT, recent / prior))


def seasonal_naive_path(values: Sequence[float], steps: int,
                        season: Optional[int] = None) -> list[float]:
    """Point forecast from the last season, scaled by recent growth.

    With a season, step k repeats the value from one season ago -- which is what
    carries quarterly seasonality, the reason a March quarter should not be
    predicted from a December one. Without a usable season it degrades to
    persistence plus linear drift.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0 or steps <= 0:
        return []
    if season and season > 0 and steps <= season and n >= 2 * season:
        ratio = _drift(vals, season)
        return [vals[n - season + k] * ratio for k in range(steps)]
    # Persistence with drift: the last value plus the average recent change.
    look = min(n - 1, season or 4)
    slope = ((vals[-1] - vals[-1 - look]) / look) if look > 0 else 0.0
    return [vals[-1] + slope * (k + 1) for k in range(steps)]


def _damped(value: float, values: Sequence[float], step: int,
            season: Optional[int]) -> float:
    """Hold one scenario inside the same growth bounds `_drift` enforces.

    `MAX_DRIFT` is a decision not to project explosive growth, and it has to
    survive the error correction rather than be undone by it. For a company the
    rule deliberately damped, the measured errors are large and positive
    *because* of the damping -- correcting for that bias would be measuring our
    own chosen conservatism and cancelling it, which is how a capped forecast
    ends up above its cap.

    Applied to all three scenarios, not just the central one: the ceiling is a
    statement about how much growth is worth projecting, and it means as much for
    the optimistic case as for the middle. Clamping monotone inputs to shared
    bounds preserves their order, so bad <= good <= very good still holds.

    Only in the seasonal regime, where the bound is defined -- year-on-year
    against the same quarter a season back, which is what `_drift` measures.
    """
    n = len(values)
    if not season or season <= 0 or n < 2 * season or step > season:
        return round(value, 4)
    prior = values[n - season + step - 1]
    if prior <= 0:
        return round(value, 4)
    return round(max(prior * MIN_DRIFT, min(prior * MAX_DRIFT, value)), 4)


def _backtest_errors(values: Sequence[float], steps: int,
                     season: Optional[int]
                     ) -> tuple[dict[int, list[float]], list[float]]:
    """Percentage errors of `seasonal_naive_path` at every past origin.

    Walk-forward: at each origin only the values before it are used, so the
    errors are the ones the rule would really have made rather than the ones it
    makes with hindsight.

    Returns the per-step errors and, separately, the errors of the whole summed
    path -- collected only at origins with all `steps` values after them, since a
    partial sum is not the quantity `total()` reports.
    """
    vals = [float(v) for v in values]
    errors: dict[int, list[float]] = {k: [] for k in range(1, steps + 1)}
    totals: list[float] = []
    first = (2 * season) if season else 5
    for origin in range(first, len(vals)):
        path = seasonal_naive_path(vals[:origin], steps, season)
        if not path:
            continue
        for k in range(1, steps + 1):
            idx = origin + k - 1
            if idx >= len(vals) or k - 1 >= len(path):
                break
            pred = path[k - 1]
            if pred > 0:
                errors[k].append((vals[idx] - pred) / pred * 100.0)
        if origin + steps <= len(vals) and len(path) >= steps:
            predicted = sum(path[:steps])
            if predicted > 0:
                actual = sum(vals[origin:origin + steps])
                totals.append((actual - predicted) / predicted * 100.0)
    return errors, totals


def _deviation(errors: Sequence[float]) -> Optional[float]:
    """Typical absolute miss, as a percentage. None below the floor.

    The median rather than the mean, for the same reason the band uses
    quantiles: one restated quarter or one-off contract produces an error in the
    hundreds of percent, and a mean lets that single observation set the number
    reported for the whole series.
    """
    absolute = sorted(abs(e) for e in errors)
    if len(absolute) < MIN_DEV_ERRORS:
        return None
    return round(_quantile(absolute, 0.5), 2)


def naive_forecast(values: Sequence[float], steps: int,
                   season: Optional[int] = None, label: str = ""
                   ) -> SeriesForecast:
    """The baseline: seasonal-naive point path, band from its own backtest.

    The central estimate is the seasonal-naive path itself, in every case. The
    band around it is the measured spread of that rule's own past errors, and
    only the spread -- the level of those errors is deliberately not used to move
    the central case. See the comment at the quantiles for why.
    """
    out = SeriesForecast(backend=BACKEND_NAIVE, label=label, season=season,
                         n_history=len(values))
    vals = [float(v) for v in values if v is not None]
    need = (2 * season + 1) if season else 5
    if len(vals) < need:
        out.error = f"need {need} points, have {len(vals)}"
        return out
    path = seasonal_naive_path(vals, steps, season)
    if not path:
        out.error = "no forecast path"
        return out
    errors, total_errors = _backtest_errors(vals, steps, season)
    out.total_dev_pct = _deviation(total_errors)
    for k in range(1, steps + 1):
        band = LevelBand(step=k, good=round(path[k - 1], 4))
        errs = sorted(errors.get(k, []))
        band.n_errors = len(errs)
        band.dev_pct = _deviation(errs)
        if len(errs) >= MIN_BACKTEST_ERRORS:
            # The band is the *spread* of the measured error around its own
            # median, not its absolute level. Subtracting the median is what
            # centres the band on the path, and it is the whole reason the three
            # numbers come out ordered.
            #
            # Taking the raw quantiles instead put "bad" above the central case
            # on 42 of 252 real symbols at step 1 and 85 of 250 at step 2: a rule
            # that has undershot every time has a positive 10th-percentile error,
            # so its pessimistic case lands above its own point forecast, which
            # is not a range a reader can act on.
            #
            # Shifting the central case up by that median instead -- correcting
            # the measured bias -- is the tempting fix and the wrong one. The
            # median error here is mostly `_drift` lagging an accelerating
            # company, which is to say it is the growth signal already in the
            # path, measured a second time; applying both double-counts it. On
            # WELCORP, growing 20% a year, it produced a central path implying
            # +52%. Worse, the correction is only available where a band is, so
            # steps 1 and 2 would be corrected and step 3 not -- a forecast with
            # a discontinuity in the middle of it. Dispersion is the part of that
            # distribution this rule has not already used.
            mid = _quantile(errs, Q_GOOD)
            for attr, q in (("bad", Q_BAD), ("very_good", Q_VERY_GOOD)):
                shift = _quantile(errs, q) - mid
                setattr(band, attr,
                        _damped(path[k - 1] * (1 + shift / 100.0),
                                vals, k, season))
        out.steps.append(band)
    banded = sum(1 for s in out.steps if s.has_band)
    measured = sum(1 for s in out.steps if s.dev_pct is not None)
    if banded == 0:
        out.note = (f"point forecast only: fewer than {MIN_BACKTEST_ERRORS} "
                    f"backtest errors available")
        # Even with no band at all there may be a deviation, because its floor is
        # lower. Not saying so leaves a populated column looking unexplained next
        # to a note that reads as "nothing but the point estimate".
        if measured:
            out.note += (f"; the deviation is measured on the first "
                         f"{measured} of {len(out.steps)} steps")
    elif banded < len(out.steps):
        # The near steps banded and the far ones did not, which is the normal
        # case rather than an edge one: a walk-forward backtest observes a
        # k-step error only at origins with k values left after them, so step k
        # has (n - k - 2*season + 1) observations and the far steps fall under
        # the threshold first. With quarterly sales this is the *common* outcome
        # -- screener's page gives 13 quarters, which bands steps 1 and 2 and
        # never step 3.
        #
        # It has to be said out loud. `total()` needs every step, so one
        # unbanded far step empties the summed scenario columns, and a reader
        # looking at a populated step-1 band beside a blank total would
        # reasonably read it as a bug. Saying nothing is how the caveat gets
        # lost -- the same mistake as filing it in `error`, from the other side.
        need = len(out.steps) + 2 * (season or 4) + MIN_BACKTEST_ERRORS - 1
        out.note = (f"band on the first {banded} of {len(out.steps)} steps: a "
                    f"{len(out.steps)}-step error has fewer past observations "
                    f"than a 1-step one, so the full band needs {need} points "
                    f"and there are {len(vals)}")
        # The deviation usually survives where the band does not, and saying so
        # turns the caveat from a dead end into a redirection: the reader still
        # gets a number for how much to trust the far steps.
        if measured == len(out.steps):
            out.note += "; the deviation columns cover every step"
        elif measured > banded:
            out.note += (f"; the deviation reaches step {measured}")
    return out


def timesfm_levels(values: Sequence[float], steps: int, model=None,
                   label: str = "",
                   season: Optional[int] = None) -> SeriesForecast:
    """TimesFM's next `steps` values with quantile bands.

    Same defensive posture as `timesfm_outlook`: an output shape the extraction
    does not recognise becomes an error on the result, never an exception that
    ends a long run partway through.
    """
    out = SeriesForecast(backend=BACKEND_TIMESFM, label=label, season=season,
                         n_history=len(values))
    if model is None:
        out.error = "no model passed (call load_timesfm first)"
        return out
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 4:
        out.error = f"need 4 points, have {len(vals)}"
        return out
    try:
        point, quantiles = model.forecast(horizon=steps, inputs=[vals])
    except Exception as e:  # noqa: BLE001
        out.error = f"forecast failed: {type(e).__name__}: {e}"
        return out

    try:
        series = quantiles[0]
    except Exception as e:  # noqa: BLE001
        out.error = f"unrecognised output shape: {type(e).__name__}: {e}"
        return out

    degraded = ""
    for k in range(1, steps + 1):
        band = LevelBand(step=k)
        try:
            levels = list(series[k - 1])[1:]
            if len(levels) < 3:
                raise ValueError(f"only {len(levels)} quantile levels")
            band.bad = round(_from_quantile_grid(levels, Q_BAD), 4)
            band.good = round(_from_quantile_grid(levels, Q_GOOD), 4)
            band.very_good = round(_from_quantile_grid(levels, Q_VERY_GOOD), 4)
        except Exception as e:  # noqa: BLE001
            try:
                band.good = round(float(point[0][k - 1]), 4)
                degraded = degraded or f"no quantiles ({e}); point forecast only"
            except Exception:  # noqa: BLE001
                out.error = f"unusable at step {k}: {type(e).__name__}: {e}"
                return out
        out.steps.append(band)
    out.note = degraded
    return out


def forecast_series(values: Sequence[float], steps: int,
                    season: Optional[int] = None, model=None,
                    label: str = "") -> dict[str, SeriesForecast]:
    """Baseline always, TimesFM when a model is supplied.

    Both, never only the model. If they agree the model is reproducing a rule
    that costs nothing to run, and that is the single most useful thing to know
    before acting on its numbers.
    """
    out = {BACKEND_NAIVE: naive_forecast(values, steps, season, label)}
    if model is not None:
        out[BACKEND_TIMESFM] = timesfm_levels(values, steps, model,
                                              label, season)
    return out


def pick(both: dict[str, SeriesForecast]) -> SeriesForecast:
    """Which of `forecast_series`' results to report, for callers that want one.

    Preferring bands over backends. The model first when it produced three
    scenarios, because three outcomes are what the bands are for. But a baseline
    *with* a band beats a model with only a central path: the baseline's interval
    is its own measured backtest error rather than an assumption, and a number
    with an interval is worth more than a slightly better number without one.
    Only if neither banded does the model's point path win, and the baseline is
    the last resort rather than reporting nothing at all.

    Callers still have to check `ok` -- when every backend failed this returns
    the baseline carrying its error, because a caller needs the reason.
    """
    naive = both[BACKEND_NAIVE]
    model = both.get(BACKEND_TIMESFM)
    if model is not None and model.ok and model.has_band:
        return model
    if naive.ok and naive.has_band:
        return naive
    if model is not None and model.ok:
        return model
    return naive


def level_agreement(a: SeriesForecast, b: SeriesForecast,
                    tolerance_pct: float = 10.0) -> str:
    """Compare two level forecasts on their central path."""
    if not (a.ok and b.ok):
        return "incomparable"
    base = a.total("good")
    other = b.total("good")
    if base is None or other is None or base == 0:
        return "incomparable"
    gap = (other - base) / abs(base) * 100.0
    if abs(gap) <= tolerance_pct:
        return "similar"
    return "model-higher" if gap > 0 else "model-lower"


def agreement(a: Outlook, b: Outlook, tolerance_pct: float = 5.0) -> str:
    """Do two outlooks tell the same story?

    'similar' means the model is reproducing the stock's own return distribution
    and is not adding information. That is the expected result for equities at
    this horizon, and saying so is more useful than presenting the model's
    numbers as though they were a discovery.
    """
    if not (a.ok and b.ok):
        return "incomparable"
    if a.band_width_pct is None or b.band_width_pct is None:
        return "incomparable"
    centre_gap = abs(a.good_pct - b.good_pct)
    width_gap = abs(a.band_width_pct - b.band_width_pct)
    if centre_gap <= tolerance_pct and width_gap <= tolerance_pct * 2:
        return "similar"
    if b.band_width_pct < a.band_width_pct:
        return "model-narrower"
    return "model-wider"
