"""Tests for scanner.significance.

The first two cases are the ones stated as the requirement: a Rs 2,000 cr order
against a Rs 500 cr market cap must read as material, and a Rs 200 cr order
against a Rs 2,00,000 cr cap must not.
"""

import unittest

from scanner import significance as sig

CR = sig.CRORE


class TestStatedRequirement(unittest.TestCase):
    def test_small_cap_large_order_is_transformational(self):
        s = sig.score(2000 * CR, mcap_cr=500)
        self.assertAlmostEqual(s.order_to_mcap_pct, 400.0)
        self.assertEqual(s.verdict, "TRANSFORMATIONAL")

    def test_mega_cap_small_order_is_negligible(self):
        s = sig.score(200 * CR, mcap_cr=200000)
        self.assertAlmostEqual(s.order_to_mcap_pct, 0.1)
        self.assertEqual(s.verdict, "NEGLIGIBLE")

    def test_the_same_order_ranks_differently_by_company_size(self):
        small = sig.score(1000 * CR, mcap_cr=800)
        large = sig.score(1000 * CR, mcap_cr=150000)
        self.assertGreater(sig.rank(small.verdict), sig.rank(large.verdict))


class TestBands(unittest.TestCase):
    def test_mcap_band_boundaries_are_inclusive_at_the_lower_edge(self):
        cases = [
            (19, "NEGLIGIBLE"),        # 1.9%
            (20, "MODEST"),            # 2.0% exactly
            (50, "MODEST"),            # 5%
            (100, "MATERIAL"),         # 10% exactly
            (250, "LARGE"),            # 25% exactly
            (500, "TRANSFORMATIONAL"), # 50% exactly
        ]
        for order_cr, expected in cases:
            with self.subTest(order_cr=order_cr):
                self.assertEqual(sig.score(order_cr * CR, 1000).mcap_band, expected)

    def test_revenue_band_needs_a_bigger_ratio_than_mcap(self):
        """2% of mcap is MODEST; 2% of revenue is NEGLIGIBLE. Same number,
        different meaning -- that asymmetry is deliberate."""
        s = sig.score(20 * CR, mcap_cr=1000, quarterly_sales=[250] * 4)
        self.assertEqual(s.mcap_band, "MODEST")
        self.assertEqual(s.revenue_band, "NEGLIGIBLE")

    def test_order_exceeding_a_year_of_sales_is_transformational_on_revenue(self):
        s = sig.score(1200 * CR, mcap_cr=None, quarterly_sales=[250] * 4)
        self.assertAlmostEqual(s.ttm_sales_cr, 1000.0)
        self.assertAlmostEqual(s.order_to_ttm_sales_pct, 120.0)
        self.assertEqual(s.revenue_band, "TRANSFORMATIONAL")
        self.assertEqual(s.verdict, "TRANSFORMATIONAL")


class TestVerdictCombination(unittest.TestCase):
    def test_verdict_is_the_higher_of_the_two_bands(self):
        # 1% of mcap (NEGLIGIBLE) but 60% of TTM sales (LARGE).
        s = sig.score(600 * CR, mcap_cr=60000, quarterly_sales=[250] * 4)
        self.assertEqual(s.mcap_band, "NEGLIGIBLE")
        self.assertEqual(s.revenue_band, "LARGE")
        self.assertEqual(s.verdict, "LARGE")

    def test_unknown_band_is_ignored_when_the_other_is_known(self):
        s = sig.score(2000 * CR, mcap_cr=500, quarterly_sales=None)
        self.assertEqual(s.revenue_band, sig.UNKNOWN)
        self.assertEqual(s.verdict, "TRANSFORMATIONAL")

    def test_verdict_unknown_when_no_denominator_at_all(self):
        s = sig.score(500 * CR, mcap_cr=None)
        self.assertEqual(s.verdict, sig.UNKNOWN)

    def test_unknown_ranks_below_negligible(self):
        self.assertLess(sig.rank(sig.UNKNOWN), sig.rank("NEGLIGIBLE"))


class TestRevenueBase(unittest.TestCase):
    def test_ttm_is_the_sum_of_four_quarters_not_the_latest_one(self):
        s = sig.score(400 * CR, None, quarterly_sales=[100, 110, 120, 130])
        self.assertAlmostEqual(s.ttm_sales_cr, 460.0)

    def test_ttm_uses_the_last_four_of_a_longer_series(self):
        s = sig.score(0, None, quarterly_sales=[1, 2, 3, 100, 110, 120, 130])
        self.assertAlmostEqual(s.ttm_sales_cr, 460.0)

    def test_falls_back_to_annual_when_quarters_are_short(self):
        s = sig.score(500 * CR, None, quarterly_sales=[100, 110],
                      annual_sales=[900, 1000])
        self.assertIsNone(s.ttm_sales_cr)
        self.assertAlmostEqual(s.annual_sales_cr, 1000.0)
        self.assertAlmostEqual(s.order_to_ttm_sales_pct, 50.0)

    def test_ttm_preferred_over_annual_when_both_present(self):
        s = sig.score(100 * CR, None, quarterly_sales=[250] * 4,
                      annual_sales=[500])
        self.assertAlmostEqual(s.order_to_ttm_sales_pct, 10.0)  # vs 1000, not 500


class TestGrowth(unittest.TestCase):
    def test_qoq_and_yoy_from_the_stated_example(self):
        """'previous quarter 200cr and present quarter 300cr makes more
        difference' -- 50% QoQ."""
        s = sig.score(None, None, quarterly_sales=[200, 300])
        self.assertAlmostEqual(s.qoq_growth_pct, 50.0)
        self.assertIsNone(s.yoy_growth_pct, "needs 5 quarters")

    def test_yoy_compares_against_four_quarters_back(self):
        s = sig.score(None, None, quarterly_sales=[200, 210, 220, 230, 300])
        self.assertAlmostEqual(s.yoy_growth_pct, 50.0)

    def test_annual_growth(self):
        s = sig.score(None, None, annual_sales=[200, 500])
        self.assertAlmostEqual(s.annual_growth_pct, 150.0)

    def test_growth_from_a_loss_is_none_not_a_huge_percentage(self):
        self.assertIsNone(sig.growth_pct(300, -100))
        self.assertIsNone(sig.growth_pct(300, 0))


class TestNumberParsing(unittest.TestCase):
    def test_screener_indian_grouping(self):
        self.assertAlmostEqual(sig._num("16,20,656"), 1620656.0)

    def test_percent_sign_and_blanks(self):
        self.assertAlmostEqual(sig._num("21.7%"), 21.7)
        for blank in ("", "  ", "-", "--", None):
            self.assertIsNone(sig._num(blank))

    def test_garbage_is_none_not_an_exception(self):
        self.assertIsNone(sig._num("n/a"))
        self.assertIsNone(sig._num("Rs cr"))

    def test_mixed_series_skips_unparseable_entries(self):
        s = sig.score(0, None, quarterly_sales=[100, "", 110, "-", 120, 130])
        self.assertAlmostEqual(s.ttm_sales_cr, 460.0)


class TestDivisionSafety(unittest.TestCase):
    def test_zero_denominator_is_none_not_infinity(self):
        self.assertIsNone(sig.pct(100, 0))
        self.assertIsNone(sig.pct(100, -5))

    def test_no_order_value_leaves_ratios_none(self):
        s = sig.score(None, mcap_cr=1000, quarterly_sales=[250] * 4)
        self.assertIsNone(s.order_cr)
        self.assertIsNone(s.order_to_mcap_pct)
        self.assertEqual(s.verdict, sig.UNKNOWN)
        self.assertEqual(s.summary(), "")


class TestSummary(unittest.TestCase):
    def test_summary_names_both_denominators(self):
        s = sig.score(2000 * CR, mcap_cr=500, quarterly_sales=[250] * 4)
        text = s.summary()
        self.assertIn("TRANSFORMATIONAL", text)
        self.assertIn("2,000 cr", text)
        self.assertIn("% of mcap", text)
        self.assertIn("% of TTM sales", text)


if __name__ == "__main__":
    unittest.main()
