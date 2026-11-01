"""Tests for scanner.indicators."""

import io
import unittest

from scanner import indicators as ind


class TestSMA(unittest.TestCase):
    def test_simple_average_of_last_period(self):
        # Only the final 200 matter; the leading 1.0s must be ignored.
        closes = [1.0] * 100 + [float(x) for x in range(1, 201)]
        self.assertAlmostEqual(ind.sma(closes, 200), sum(range(1, 201)) / 200)

    def test_exactly_period_length_works(self):
        self.assertAlmostEqual(ind.sma([2.0] * 200, 200), 2.0)

    def test_short_series_returns_none(self):
        self.assertIsNone(ind.sma([1.0] * 199, 200))

    def test_flat_series_equals_the_level(self):
        self.assertAlmostEqual(ind.sma([37.5] * 250, 200), 37.5)


class TestEMA(unittest.TestCase):
    def test_flat_series_equals_the_level(self):
        # A constant series must not drift, whatever the seed.
        self.assertAlmostEqual(ind.ema([50.0] * 300, 50), 50.0)

    def test_short_series_returns_none(self):
        self.assertIsNone(ind.ema([1.0] * 49, 50))

    def test_seed_is_sma_when_series_is_exactly_period(self):
        closes = [float(x) for x in range(1, 51)]
        self.assertAlmostEqual(ind.ema(closes, 50), sum(closes) / 50)

    def test_known_value_three_period(self):
        # alpha = 0.5. seed = mean(1,2,3) = 2; then 4 -> 3.0, then 5 -> 4.0.
        self.assertAlmostEqual(ind.ema([1, 2, 3, 4, 5], 3), 4.0)

    def test_reacts_faster_than_sma_on_a_rally(self):
        closes = [100.0] * 250 + [200.0] * 20
        self.assertGreater(ind.ema(closes, 50), ind.sma(closes, 200))

    def test_converges_regardless_of_extra_leading_history(self):
        tail = [100.0 + i for i in range(300)]
        short = ind.ema(tail, 50)
        long = ind.ema([50.0] * 500 + tail, 50)
        # 300 periods leave a ~1e-4 residual on a trending series. The bound that
        # matters is the output's own granularity: results are rounded to paise,
        # so agreement well inside 0.01 means the seed is irrelevant in practice.
        self.assertLess(abs(short - long), 0.001)


class TestClassifyTrend(unittest.TestCase):
    def test_above_both(self):
        self.assertEqual(ind.classify_trend(110, 100, 90), ind.TREND_UPTREND)

    def test_above_ema_only(self):
        self.assertEqual(ind.classify_trend(95, 90, 100), ind.TREND_ABOVE_50)

    def test_above_sma_only(self):
        self.assertEqual(ind.classify_trend(95, 100, 90), ind.TREND_ABOVE_200)

    def test_below_both(self):
        self.assertEqual(ind.classify_trend(80, 90, 100), ind.TREND_BELOW_BOTH)

    def test_missing_sma_is_unknown_not_bearish(self):
        # A 190-day-old listing has no honest 200 DMA; calling it BELOW_BOTH
        # would invent a bearish signal out of missing data.
        self.assertEqual(ind.classify_trend(100, 90, None), ind.TREND_UNKNOWN)

    def test_missing_ema_is_unknown(self):
        self.assertEqual(ind.classify_trend(100, None, 90), ind.TREND_UNKNOWN)

    def test_price_equal_to_average_is_not_above(self):
        self.assertEqual(ind.classify_trend(100, 100, 100), ind.TREND_BELOW_BOTH)


class TestComputeTrend(unittest.TestCase):
    def test_bundle_shape_and_rounding(self):
        closes = [100.0] * 300
        out = ind.compute_trend(closes, 100.0)
        self.assertEqual(
            set(out), {"ema50", "sma200", "above_ema50", "above_sma200", "trend"}
        )
        self.assertEqual(out["ema50"], 100.0)
        self.assertEqual(out["sma200"], 100.0)
        self.assertFalse(out["above_ema50"])
        self.assertEqual(out["trend"], ind.TREND_BELOW_BOTH)

    def test_recent_ipo_yields_nulls_not_false(self):
        # 190 candles: EMA50 is computable, 200 DMA is not.
        out = ind.compute_trend([100.0] * 190, 120.0)
        self.assertIsNotNone(out["ema50"])
        self.assertIsNone(out["sma200"])
        self.assertIsNone(out["above_sma200"])
        self.assertEqual(out["trend"], ind.TREND_UNKNOWN)

    def test_uptrend_on_a_rising_series(self):
        closes = [100.0 + i * 0.5 for i in range(400)]
        out = ind.compute_trend(closes, closes[-1])
        self.assertTrue(out["above_ema50"])
        self.assertTrue(out["above_sma200"])
        self.assertEqual(out["trend"], ind.TREND_UPTREND)

    def test_empty_series_is_unknown(self):
        out = ind.compute_trend([], 100.0)
        self.assertEqual(out["trend"], ind.TREND_UNKNOWN)
        self.assertIsNone(out["ema50"])

    def test_unknown_label_survives_a_csv_round_trip(self):
        # "n/a" is in pandas' default na_values: writing it and reading back
        # would yield NaN and erase the difference between "no history" and
        # "column absent". Guard the label against a regression to that.
        import pandas as pd

        df = pd.DataFrame([ind.compute_trend([100.0] * 190, 120.0)])
        restored = pd.read_csv(io.StringIO(df.to_csv(index=False)))
        self.assertEqual(restored["trend"].iloc[0], ind.TREND_UNKNOWN)
        self.assertTrue(pd.notna(restored["trend"].iloc[0]))


if __name__ == "__main__":
    unittest.main()
