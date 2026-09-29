"""Tests for scanner.volatility.

Series are constructed so the expected volatility is known in advance: a constant
daily move of r gives a realized volatility of exactly 0 (no dispersion), and an
alternating +r/-r gives a known non-zero one. That makes the annualisation
arithmetic checkable rather than merely plausible.
"""

import math
import unittest

from scanner import indicators
from scanner import volatility as vol


def _flat(n, price=100.0):
    return [price] * n


def _steady(n, price=100.0, step_pct=0.5):
    """Constant *percentage* growth: log returns are identical, so realized
    volatility is zero even though the price rises a lot."""
    out = [price]
    for _ in range(n - 1):
        out.append(out[-1] * (1 + step_pct / 100.0))
    return out


def _alternating(n, price=100.0, move_pct=2.0):
    out = [price]
    for i in range(n - 1):
        direction = 1 if i % 2 == 0 else -1
        out.append(out[-1] * (1 + direction * move_pct / 100.0))
    return out


def _chain(*segments):
    """Join price segments, continuing each from where the last ended."""
    out = list(segments[0])
    for builder in segments[1:]:
        out.extend(builder(out[-1])[1:])
    return out


def _calm(n=160):
    """Low but non-zero volatility, which is what a real quiet stock looks like.
    A literally zero-volatility series is a degenerate case, tested separately."""
    return lambda price=100.0: _alternating(n, price=price, move_pct=0.3)


def _violent(n=40):
    return lambda price=100.0: _alternating(n, price=price, move_pct=3.0)


def _calm_then_violent():
    return _chain(_calm(160)(100.0), _violent(40))


def _violent_then_calm():
    return _chain(_violent(160)(100.0), _calm(40))


class TestLogReturns(unittest.TestCase):
    def test_count_is_one_less_than_closes(self):
        self.assertEqual(len(vol.log_returns(_flat(10))), 9)

    def test_flat_series_has_zero_returns(self):
        self.assertTrue(all(r == 0.0 for r in vol.log_returns(_flat(10))))

    def test_known_value(self):
        self.assertAlmostEqual(vol.log_returns([100.0, 110.0])[0],
                               math.log(1.1))

    def test_non_positive_and_missing_closes_are_dropped(self):
        self.assertEqual(len(vol.log_returns([100, None, 0, -3, 110])), 1)


class TestRealizedVolSeries(unittest.TestCase):
    def test_constant_percentage_growth_has_zero_volatility(self):
        """The distinction that matters: a stock up 60% in a straight line is not
        volatile. A measure that called it volatile would be measuring trend."""
        series = vol.realized_vol_series(_steady(100), window=21)
        self.assertTrue(series)
        self.assertAlmostEqual(max(series), 0.0, places=6)

    def test_alternating_moves_annualise_to_a_known_figure(self):
        series = vol.realized_vol_series(_alternating(60, move_pct=2.0),
                                         window=20)
        # Log returns alternate +ln(1.02) / +ln(0.98); over an even window the
        # mean is ~0 and the stdev is ~|ln(1.02)| to first order.
        expected = abs(math.log(1.02)) * math.sqrt(252) * 100
        self.assertAlmostEqual(series[-1], expected, delta=expected * 0.05)

    def test_one_value_per_complete_window(self):
        closes = _alternating(80)
        series = vol.realized_vol_series(closes, window=21)
        self.assertEqual(len(series), len(closes) - 1 - 21 + 1)

    def test_too_short_is_empty_not_an_exception(self):
        self.assertEqual(vol.realized_vol_series(_flat(5), window=21), [])


class TestClassifyRegime(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(vol.classify_regime(2.0), vol.REGIME_EXPANDING)
        self.assertEqual(vol.classify_regime(1.0), vol.REGIME_STABLE)
        self.assertEqual(vol.classify_regime(0.5), vol.REGIME_CONTRACTING)
        self.assertEqual(vol.classify_regime(None), vol.REGIME_UNKNOWN)

    def test_thresholds_are_symmetric_in_log_terms(self):
        """Expanding by 30% and contracting by the same factor should be the same
        distance from 1, or the label would be biased toward one direction."""
        self.assertAlmostEqual(vol.EXPANDING * vol.CONTRACTING, 1.0, delta=0.02)


class TestPercentileOf(unittest.TestCase):
    def test_all_values_identical_is_the_midpoint(self):
        """The case the midpoint rank exists for: a value that never changes is
        exactly typical of itself, not the most extreme reading on record."""
        self.assertAlmostEqual(vol._percentile_of([5.0] * 10, 5.0), 50.0)

    def test_ties_within_float_noise_still_count_as_ties(self):
        """Equal-by-construction volatilities differ in the last bits after a
        square root. With exact equality none of these count as ties and the
        answer jumps to ~95 instead of 50."""
        values = [5.0 * (1 + i * 1e-15) for i in range(20)]
        self.assertAlmostEqual(vol._percentile_of(values, values[-1]), 50.0,
                               delta=1.0)

    def test_a_genuine_extreme_still_reads_extreme(self):
        """The tolerance must not blunt real dispersion."""
        self.assertAlmostEqual(vol._percentile_of([1.0] * 9 + [50.0], 50.0),
                               95.0)

    def test_a_genuine_low_still_reads_low(self):
        self.assertAlmostEqual(vol._percentile_of([1.0] + [50.0] * 9, 1.0), 5.0)

    def test_middle_of_a_spread(self):
        self.assertAlmostEqual(vol._percentile_of([1.0, 2.0, 3.0, 4.0], 2.0),
                               37.5)

    def test_empty_is_zero_not_an_exception(self):
        self.assertEqual(vol._percentile_of([], 1.0), 0.0)


class TestVolState(unittest.TestCase):
    def test_short_history_is_an_error(self):
        state = vol.vol_state(_flat(30))
        self.assertFalse(state.ok)
        self.assertIn("need", state.error)

    def test_a_calm_stock_reads_calm(self):
        state = vol.vol_state(_calm(200)())
        self.assertTrue(state.ok, state.error)
        self.assertLess(state.current, 10.0)

    def test_constant_volatility_is_typical_of_itself_not_extreme(self):
        """Everything here is relative to the stock's own history, so a stock
        whose volatility never changes sits at its own median -- the midpoint
        rank that `_percentile_of` exists to get right."""
        state = vol.vol_state(_calm(200)())
        self.assertAlmostEqual(state.percentile, 50.0, delta=5.0)
        self.assertFalse(state.unusually_high)
        self.assertEqual(state.regime, vol.REGIME_STABLE)

    def test_a_zero_volatility_series_is_not_reported_as_unknown(self):
        """Degenerate but must not silently become UNKNOWN: a perfectly smooth
        ramp has zero volatility and a zero baseline, and 'stable' is the honest
        label."""
        state = vol.vol_state(_steady(200))
        self.assertTrue(state.ok, state.error)
        self.assertAlmostEqual(state.current, 0.0, places=4)
        self.assertEqual(state.regime, vol.REGIME_STABLE)

    def test_volatility_expanding_after_a_quiet_stretch(self):
        """The case the module exists for: same price level, completely different
        risk, and nothing else in the pipeline sees the difference."""
        state = vol.vol_state(_calm_then_violent())
        self.assertTrue(state.ok, state.error)
        self.assertEqual(state.regime, vol.REGIME_EXPANDING)
        self.assertGreater(state.ratio, vol.EXPANDING)

    def test_percentile_is_against_the_stock_itself(self):
        state = vol.vol_state(_calm_then_violent())
        self.assertGreaterEqual(state.percentile, vol.HIGH_PERCENTILE)
        self.assertTrue(state.unusually_high)

    def test_volatility_contracting_after_a_violent_stretch(self):
        state = vol.vol_state(_violent_then_calm())
        self.assertTrue(state.ok, state.error)
        self.assertEqual(state.regime, vol.REGIME_CONTRACTING)
        self.assertLess(state.ratio, vol.CONTRACTING)

    def test_no_model_still_produces_the_measurements(self):
        """Regime and percentile are measurements, not predictions, and must not
        depend on a model being installed."""
        state = vol.vol_state(_alternating(200))
        self.assertTrue(state.ok)
        self.assertIsNone(state.forecast)
        self.assertEqual(state.backend, "")

    def test_the_forecast_band_is_inverted_for_volatility(self):
        """High volatility is the bad scenario, so forecast_bad must be the
        upper edge -- the opposite of a price band."""
        state = vol.vol_state(_alternating(200), model=_StubModel())
        self.assertTrue(state.ok, state.error)
        self.assertIsNotNone(state.forecast_bad)
        self.assertGreater(state.forecast_bad, state.forecast_low)


class _StubModel:
    """Returns a widening quantile fan around a fixed level."""

    def forecast(self, inputs, freq):
        levels = [30.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]
        return ([[30.0] * 8], [[list(levels)] * 8])


class TestBreakoutQuality(unittest.TestCase):
    def test_a_calming_uptrend_is_orderly(self):
        state = vol.vol_state(_violent_then_calm())
        self.assertEqual(vol.breakout_quality(state, indicators.TREND_UPTREND),
                         "ORDERLY")

    def test_a_steady_volatility_uptrend_is_normal(self):
        state = vol.vol_state(_calm(200)())
        self.assertEqual(vol.breakout_quality(state, indicators.TREND_UPTREND),
                         "NORMAL")

    def test_an_expanding_uptrend_is_hot(self):
        state = vol.vol_state(_calm_then_violent())
        self.assertEqual(vol.breakout_quality(state, indicators.TREND_UPTREND),
                         "HOT")

    def test_no_label_outside_an_uptrend(self):
        """The distinction only means something for a stock making highs; for a
        broken chart it would be noise dressed as a signal."""
        state = vol.vol_state(_calm_then_violent())
        self.assertEqual(
            vol.breakout_quality(state, indicators.TREND_BELOW_BOTH), "")

    def test_no_label_without_a_usable_state(self):
        self.assertEqual(
            vol.breakout_quality(vol.VolState(error="x"),
                                 indicators.TREND_UPTREND), "")


if __name__ == "__main__":
    unittest.main()
