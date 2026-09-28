"""Unit tests for scanner.ath — pure functions, synthetic candles only."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from scanner.ath import (
    Candle,
    classify_bucket,
    compute_ath,
    distance_pct,
    is_new_ath_today,
    is_recent_ipo,
    listed_days,
    scan_symbol,
)

D0 = date(2020, 1, 1)


def c(day_offset: int, high: float, close: float | None = None) -> Candle:
    return Candle(d=D0 + timedelta(days=day_offset), high=high, close=close if close is not None else high)


class TestComputeAth(unittest.TestCase):
    def test_basic(self):
        candles = [c(0, 100), c(1, 150), c(2, 120)]
        stats = compute_ath(candles)
        self.assertEqual(stats.ath_high, 150)
        self.assertEqual(stats.ath_date, D0 + timedelta(days=1))
        self.assertEqual(stats.first_date, D0)
        self.assertEqual(stats.last_date, D0 + timedelta(days=2))

    def test_single_day_history(self):
        candles = [c(0, 100, close=99)]
        stats = compute_ath(candles)
        self.assertEqual(stats.ath_high, 100)
        self.assertEqual(stats.ath_close, 99)
        self.assertEqual(stats.first_date, D0)
        self.assertEqual(stats.last_date, D0)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            compute_ath([])

    def test_gap_in_data(self):
        # A big gap between day 1 and day 100 shouldn't affect ATH-by-high;
        # it's still just the max over whatever candles exist.
        candles = [c(0, 100), c(1, 200), c(100, 150)]
        stats = compute_ath(candles)
        self.assertEqual(stats.ath_high, 200)
        self.assertEqual(stats.ath_date, D0 + timedelta(days=1))
        self.assertEqual(stats.first_date, D0)
        self.assertEqual(stats.last_date, D0 + timedelta(days=100))


class TestNewAthToday(unittest.TestCase):
    def test_new_high_today(self):
        prior = [c(0, 100), c(1, 110)]
        self.assertTrue(is_new_ath_today(prior, today_high=110))
        self.assertTrue(is_new_ath_today(prior, today_high=111))

    def test_not_new_high_today(self):
        prior = [c(0, 100), c(1, 110)]
        self.assertFalse(is_new_ath_today(prior, today_high=109))

    def test_no_prior_history_is_vacuously_new_ath(self):
        # Single-day-old listing: today is the only session there is.
        self.assertTrue(is_new_ath_today([], today_high=50))


class TestDistancePct(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(distance_pct(100, 90), 10.0)

    def test_at_ath(self):
        self.assertEqual(distance_pct(100, 100), 0.0)

    def test_above_ath_clamped_to_zero(self):
        self.assertEqual(distance_pct(100, 105), 0.0)


class TestClassifyBucket(unittest.TestCase):
    def test_new_ath_overrides_distance(self):
        self.assertEqual(classify_bucket(50, is_new_ath=True, max_dist=26), "NEW_ATH_TODAY")

    def test_boundary_5_inclusive(self):
        self.assertEqual(classify_bucket(5.0, is_new_ath=False, max_dist=26), "0-5%")

    def test_just_above_5(self):
        self.assertEqual(classify_bucket(5.0001, is_new_ath=False, max_dist=26), "5-15%")

    def test_boundary_15_inclusive(self):
        self.assertEqual(classify_bucket(15.0, is_new_ath=False, max_dist=26), "5-15%")

    def test_just_above_15(self):
        self.assertEqual(classify_bucket(15.0001, is_new_ath=False, max_dist=26), "15-26%")

    def test_boundary_26_inclusive(self):
        self.assertEqual(classify_bucket(26.0, is_new_ath=False, max_dist=26), "15-26%")

    def test_just_above_26_dropped(self):
        self.assertIsNone(classify_bucket(26.0001, is_new_ath=False, max_dist=26))

    def test_zero_distance(self):
        self.assertEqual(classify_bucket(0.0, is_new_ath=False, max_dist=26), "0-5%")

    def test_custom_max_dist_below_15(self):
        # With --max-dist 10, the "15-26%" bucket shouldn't exist at all.
        self.assertEqual(classify_bucket(5.0, is_new_ath=False, max_dist=10), "0-5%")
        self.assertEqual(classify_bucket(10.0, is_new_ath=False, max_dist=10), "5-10%")
        self.assertIsNone(classify_bucket(10.0001, is_new_ath=False, max_dist=10))


class TestListedDays(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(listed_days(D0, D0 + timedelta(days=10)), 10)

    def test_recent_ipo_flag(self):
        self.assertTrue(is_recent_ipo(300))
        self.assertFalse(is_recent_ipo(400))
        self.assertFalse(is_recent_ipo(365))  # boundary: exactly 1 year is not "recent"


class TestScanSymbol(unittest.TestCase):
    def test_new_ath_today(self):
        prior = [c(0, 100), c(1, 110)]
        as_of = D0 + timedelta(days=2)
        result = scan_symbol(prior, today_high=120, ltp=118, as_of=as_of, max_dist=26)
        self.assertIsNotNone(result)
        self.assertEqual(result.bucket, "NEW_ATH_TODAY")
        self.assertEqual(result.ath_high, 120)
        self.assertEqual(result.ath_date, as_of)
        self.assertEqual(result.days_since_ath, 0)

    def test_within_5pct_of_ath(self):
        prior = [c(0, 100), c(1, 200)]
        as_of = D0 + timedelta(days=10)
        result = scan_symbol(prior, today_high=195, ltp=196, as_of=as_of, max_dist=26)
        self.assertIsNotNone(result)
        self.assertEqual(result.ath_high, 200)
        self.assertAlmostEqual(result.distance_pct, 2.0)
        self.assertEqual(result.bucket, "0-5%")
        self.assertEqual(result.days_since_ath, 9)

    def test_dropped_beyond_max_dist(self):
        prior = [c(0, 100), c(1, 200)]
        as_of = D0 + timedelta(days=10)
        result = scan_symbol(prior, today_high=140, ltp=140, as_of=as_of, max_dist=26)
        self.assertIsNone(result)

    def test_single_day_history_brand_new_listing(self):
        # No prior candles at all: first session ever, today.
        as_of = D0
        result = scan_symbol([], today_high=100, ltp=98, as_of=as_of, max_dist=26)
        self.assertIsNotNone(result)
        self.assertEqual(result.bucket, "NEW_ATH_TODAY")
        self.assertEqual(result.listed_days, 0)
        self.assertTrue(result.recent_ipo)

    def test_gap_in_history_still_computes_correct_ath(self):
        prior = [c(0, 100), c(1, 300), c(50, 250)]
        as_of = D0 + timedelta(days=60)
        result = scan_symbol(prior, today_high=280, ltp=270, as_of=as_of, max_dist=26)
        self.assertIsNotNone(result)
        self.assertEqual(result.ath_high, 300)
        self.assertAlmostEqual(result.distance_pct, 10.0)
        self.assertEqual(result.bucket, "5-15%")
        self.assertEqual(result.days_since_ath, 59)


if __name__ == "__main__":
    unittest.main()
