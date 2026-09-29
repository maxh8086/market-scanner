"""Tests for scanner.revenue.

The arithmetic is the whole module, so it is all testable without a model: the
TimesFM path is exercised by passing None (baseline only) and by a stub.

Quarters throughout are in rupees so the order-book comparison is in one unit.
A "100" quarter is 100 rupees, not 100 crore -- the scale is irrelevant to the
arithmetic and keeping it small keeps the expected values readable.
"""

import unittest

from scanner import indicators
from scanner import revenue as rev


def _seasonal(years=4, base=100.0, growth=1.10):
    """Quarterly series with a clear Q4 peak and steady annual growth."""
    shape = [0.9, 1.0, 1.05, 1.25]      # Q1..Q4 seasonal factors
    out = []
    for y in range(years):
        for q in range(4):
            out.append(base * (growth ** y) * shape[q])
    return out


def _noisy(years=5, base=100.0, growth=1.10):
    """`_seasonal` with a repeating wobble, so the backtest has real errors.

    A clean seasonal series is predicted exactly by the seasonal rule, so its
    measured error -- and therefore its band -- is zero. That is the right
    answer for that series and a useless fixture for testing a band.
    """
    jitter = [1.03, 0.96, 1.05, 0.94, 1.02, 0.97, 1.06, 0.95]
    return [v * jitter[i % len(jitter)]
            for i, v in enumerate(_seasonal(years, base, growth))]


class TestTrailingTTM(unittest.TestCase):
    def test_sums_the_last_four(self):
        self.assertAlmostEqual(rev.trailing_ttm([1, 2, 3, 4, 5, 6, 7, 8]), 26.0)

    def test_none_when_fewer_than_four(self):
        self.assertIsNone(rev.trailing_ttm([1, 2, 3]))

    def test_blanks_are_dropped_not_zero_filled(self):
        """A zero quarter would read as a quarter with no revenue and wreck both
        the seasonal baseline and the drift."""
        self.assertAlmostEqual(rev.trailing_ttm([9, 1, None, 2, 3, "", 4]), 10.0)


class TestForwardRevenue(unittest.TestCase):
    def test_short_series_is_an_error(self):
        out = rev.forward_revenue([100.0] * 5)
        self.assertFalse(out.ok)
        self.assertIn("need", out.error)

    def test_the_minimum_history_still_yields_every_comparison(self):
        """The case that matters most in practice, because it is the common one.

        Nine quarters is what a screener page gives for a recently listed
        company, and it is enough for the seasonal rule but not for a backtest.
        Every figure the reader asked for -- the three predicted quarters, QoQ
        against the latest actual, YoY against the same quarter a year back, the
        forward TTM -- is computable from a point path alone. Only the bad /
        very good bands are not, and that must cost the bands rather than the
        whole outlook.
        """
        quarters = _seasonal()[:8] + [_seasonal()[8]]
        self.assertEqual(len(quarters), rev.MIN_QUARTERS)
        out = rev.forward_revenue(quarters)
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.error, "")
        self.assertIn("point forecast only", out.note)
        self.assertFalse(out.has_scenarios)
        self.assertEqual(len(out.quarters), 3)
        for q in out.quarters:
            self.assertIsNotNone(q.value)
            self.assertIsNotNone(q.qoq_pct)
            self.assertIsNotNone(q.yoy_pct)
            self.assertIsNone(q.bad)
        self.assertIsNotNone(out.trailing_ttm)
        self.assertIsNotNone(out.forward_ttm)
        self.assertIsNotNone(out.ttm_growth_pct)
        # The forward year's bands go missing with the quarterly ones, and for
        # the same reason. The central figure above stays.
        self.assertIsNone(out.forward_ttm_bad)
        self.assertIsNone(out.forward_ttm_very_good)
        self.assertIsNone(out.growth_pct_bad)
        self.assertIsNone(out.growth_pct_very_good)

    def test_a_long_history_gets_scenarios(self):
        out = rev.forward_revenue(_seasonal(years=5))
        self.assertTrue(out.ok, out.error)
        self.assertTrue(out.has_scenarios)
        self.assertEqual(out.note, "")
        self.assertLessEqual(out.quarters[0].bad, out.quarters[0].value)
        self.assertLessEqual(out.quarters[0].value, out.quarters[0].very_good)

    def test_the_forward_year_is_reported_as_three_outcomes(self):
        """The whole point of the exercise: a forward year with a range around
        it, not a single number presented as if it were known.

        On a noisy series, because the band is the rule's own measured backtest
        error and `_seasonal` is exactly what the rule predicts -- the error
        there is genuinely zero and the band correctly collapses to a point.
        """
        out = rev.forward_revenue(_noisy(years=5))
        self.assertLess(out.forward_ttm_bad, out.forward_ttm)
        self.assertLess(out.forward_ttm, out.forward_ttm_very_good)
        self.assertLess(out.growth_pct_bad, out.ttm_growth_pct)
        self.assertLess(out.ttm_growth_pct, out.growth_pct_very_good)

    def test_the_forward_year_deviation_excludes_the_quarter_already_known(self):
        """Three of the four quarters are forecast; the fourth is an actual and
        carries no error. So the rupee miss is the measured percentage of the
        forecast three, and stating it against the whole year gives a smaller
        percentage -- correctly, because a quarter of the total is not a guess.

        Pinned as an inequality rather than a recomputation: applying the raw
        percentage to the full year is the mistake this guards, and that version
        would make the two equal.
        """
        out = rev.forward_revenue(_noisy(years=5))
        self.assertIsNotNone(out.ttm_dev_cr)
        forecast_part = out.forward_ttm - out.latest_actual
        self.assertLess(out.ttm_dev_pct,
                        out.ttm_dev_cr / forecast_part * 100.0)
        # And the rupee figure must be that share of the full-year number.
        self.assertAlmostEqual(out.ttm_dev_pct,
                               out.ttm_dev_cr / out.forward_ttm * 100.0,
                               places=1)

    def test_the_deviation_survives_where_the_band_does_not(self):
        """Thirteen quarters, the real screener shape: the summed scenarios are
        empty because step 3 cannot band, and the deviation is there anyway. That
        asymmetry is the reason it was added."""
        out = rev.forward_revenue(_noisy(years=4)[:13])
        self.assertTrue(out.ok)
        self.assertIsNone(out.forward_ttm_bad)
        self.assertIsNotNone(out.ttm_dev_pct)
        for q in out.quarters:
            self.assertIsNotNone(q.dev_pct, f"step {q.step}")

    def test_each_forward_year_is_the_latest_actual_plus_its_own_scenario(self):
        """Each total must come from its own scenario's three quarters -- mixing
        a bad quarter into a good year would make the bands meaningless."""
        out = rev.forward_revenue(_noisy(years=5))
        latest = out.latest_actual
        for attr, which in (("forward_ttm", "value"),
                            ("forward_ttm_bad", "bad"),
                            ("forward_ttm_very_good", "very_good")):
            expected = latest + sum(getattr(q, which) for q in out.quarters)
            self.assertAlmostEqual(getattr(out, attr), expected, places=2,
                                   msg=attr)

    def test_three_quarters_are_produced(self):
        out = rev.forward_revenue(_seasonal())
        self.assertTrue(out.ok, out.error)
        self.assertEqual([q.step for q in out.quarters], [1, 2, 3])

    def test_seasonality_is_respected_not_smoothed(self):
        """The quarter after a Q4 peak must be forecast lower. A model that
        predicted Q1 from Q4 would read the seasonal drop as a collapse."""
        out = rev.forward_revenue(_seasonal())    # ends on a Q4 peak
        self.assertTrue(out.ok, out.error)
        self.assertLess(out.quarters[0].value, out.latest_actual)

    def test_qoq_is_against_the_latest_actual(self):
        out = rev.forward_revenue(_seasonal())
        q1 = out.quarters[0]
        expected = (q1.value - out.latest_actual) / out.latest_actual * 100.0
        self.assertAlmostEqual(q1.qoq_pct, round(expected, 1), places=1)

    def test_yoy_is_against_the_same_quarter_last_year(self):
        """Not against the previous quarter: for a seasonal business that would
        confuse seasonality with growth."""
        quarters = _seasonal()
        out = rev.forward_revenue(quarters)
        q1 = out.quarters[0]
        same_quarter_last_year = quarters[-4]
        expected = ((q1.value - same_quarter_last_year)
                    / same_quarter_last_year * 100.0)
        self.assertAlmostEqual(q1.yoy_pct, round(expected, 1), places=1)

    def test_yoy_is_positive_for_a_growing_business(self):
        out = rev.forward_revenue(_seasonal(growth=1.20))
        for q in out.quarters:
            with self.subTest(step=q.step):
                self.assertGreater(q.yoy_pct, 0)

    def test_forward_ttm_is_latest_actual_plus_three_forecasts(self):
        out = rev.forward_revenue(_seasonal())
        total = out.latest_actual + sum(q.value for q in out.quarters)
        self.assertAlmostEqual(out.forward_ttm, total, places=2)

    def test_ttm_growth_is_positive_for_a_growing_business(self):
        out = rev.forward_revenue(_seasonal(growth=1.15))
        self.assertGreater(out.ttm_growth_pct, 0)

    def test_flat_business_has_near_zero_ttm_growth(self):
        out = rev.forward_revenue(_seasonal(growth=1.0))
        self.assertAlmostEqual(out.ttm_growth_pct, 0.0, delta=1.0)

    def test_drift_is_damped_not_extrapolated(self):
        """A company that tripled year on year did not start tripling every
        year; projecting that forward makes a denominator that hides every real
        signal."""
        out = rev.forward_revenue(_seasonal(growth=3.0))
        self.assertLessEqual(out.ttm_growth_pct, 105.0)


class TestOrderBacked(unittest.TestCase):
    def test_no_orders_is_an_error_not_a_zero(self):
        got = rev.order_backed([], 1000.0)
        self.assertFalse(got.ok)
        self.assertIn("no order values", got.error)

    def test_execution_period_drives_the_annual_figure(self):
        """The same headline value means very different things over 6 months and
        over 24 -- the reason the period is extracted at all."""
        fast = rev.order_backed([{"value": 2000.0, "execution_months": 6}], 1000.0)
        slow = rev.order_backed([{"value": 2000.0, "execution_months": 24}], 1000.0)
        self.assertAlmostEqual(fast.annualised, 4000.0)
        self.assertAlmostEqual(slow.annualised, 1000.0)

    def test_missing_period_uses_the_default_and_says_so(self):
        got = rev.order_backed([{"value": 1200.0}], 1000.0)
        self.assertEqual(got.assumed_execution, 1)
        self.assertAlmostEqual(got.annualised,
                               1200.0 / (rev.DEFAULT_EXECUTION_MONTHS / 12))

    def test_several_orders_accumulate(self):
        got = rev.order_backed([
            {"value": 1200.0, "execution_months": 12},
            {"value": 600.0, "execution_months": 12},
        ], 1000.0)
        self.assertEqual(got.order_count, 2)
        self.assertAlmostEqual(got.total_value, 1800.0)
        self.assertAlmostEqual(got.annualised, 1800.0)

    def test_book_to_bill_above_one_means_a_growing_backlog(self):
        got = rev.order_backed([{"value": 1500.0, "execution_months": 12}], 1000.0)
        self.assertAlmostEqual(got.book_to_bill, 1.5)

    def test_unusable_values_are_skipped(self):
        got = rev.order_backed([
            {"value": None}, {"value": "n/a"}, {"value": -5},
            {"value": 1200.0, "execution_months": 12},
        ], 1000.0)
        self.assertEqual(got.order_count, 1)

    def test_implied_forward_is_additive_which_is_an_upper_bound(self):
        """Pinning the documented assumption. For a pure order-execution business
        this double-counts, so the figure is a ceiling and book_to_bill is the
        robust reading. A future change to non-additive must break this test
        rather than slip through."""
        got = rev.order_backed(
            [{"value": 1000.0, "execution_months": 12}], 1000.0)
        self.assertAlmostEqual(got.implied_forward_ttm, 2000.0)
        self.assertAlmostEqual(got.book_to_bill, 1.0)

    def test_no_trailing_revenue_is_reported_not_guessed(self):
        got = rev.order_backed([{"value": 1200.0, "execution_months": 12}], None)
        self.assertFalse(got.ok)
        self.assertIn("trailing revenue", got.error)


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self.model = rev.forward_revenue(_seasonal(growth=1.05))

    def test_a_large_order_book_runs_ahead_of_history(self):
        trailing = self.model.trailing_ttm
        orders = rev.order_backed(
            [{"value": trailing * 0.8, "execution_months": 12}], trailing)
        got = rev.reconcile(self.model, orders)
        self.assertEqual(got.verdict, rev.VERDICT_ORDERS_AHEAD)
        self.assertGreater(got.gap_pct, rev.GAP_STRONG)

    def test_a_matching_order_book_confirms(self):
        """Orders sized to reproduce the extrapolated forward year should read as
        agreement, not as a signal."""
        trailing = self.model.trailing_ttm
        needed = self.model.forward_ttm - trailing
        orders = rev.order_backed(
            [{"value": needed, "execution_months": 12}], trailing)
        got = rev.reconcile(self.model, orders)
        self.assertEqual(got.verdict, rev.VERDICT_CONFIRMS)

    def test_a_thin_order_book_lags_a_fast_extrapolation(self):
        """Growth the history implies but the order book does not contain. Note
        this needs a *fast* extrapolation: against a 5%-growth company a near-
        empty order book is only a few percent off, which is agreement, not a
        divergence -- the tolerance is doing its job there."""
        fast = rev.forward_revenue(_seasonal(growth=1.5))
        trailing = fast.trailing_ttm
        orders = rev.order_backed(
            [{"value": trailing * 0.01, "execution_months": 60}], trailing)
        got = rev.reconcile(fast, orders)
        self.assertEqual(got.verdict, rev.VERDICT_ORDERS_BEHIND)
        self.assertLess(got.gap_pct, -rev.GAP_STRONG)

    def test_a_thin_book_against_slow_growth_is_within_tolerance(self):
        trailing = self.model.trailing_ttm
        orders = rev.order_backed(
            [{"value": trailing * 0.01, "execution_months": 60}], trailing)
        got = rev.reconcile(self.model, orders)
        self.assertEqual(got.verdict, rev.VERDICT_CONFIRMS)

    def test_missing_pieces_are_named(self):
        self.assertEqual(rev.reconcile(rev.RevenueOutlook(error="x"),
                                       rev.OrderBacked()).verdict,
                         rev.VERDICT_NO_MODEL)
        self.assertEqual(rev.reconcile(self.model, rev.OrderBacked()).verdict,
                         rev.VERDICT_NO_ORDERS)

    def test_the_default_period_assumption_is_disclosed_in_the_note(self):
        trailing = self.model.trailing_ttm
        orders = rev.order_backed([{"value": trailing}], trailing)
        got = rev.reconcile(self.model, orders)
        self.assertIn("default period", got.note)


class TestGuidance(unittest.TestCase):
    def test_absolute_target_is_used_as_filed(self):
        g = rev.Guidance(direction=rev.GUIDANCE_NEW, target_inr=12000.0)
        self.assertAlmostEqual(g.implied_forward_ttm(9000.0), 12000.0)

    def test_growth_is_applied_to_trailing_revenue(self):
        g = rev.Guidance(direction=rev.GUIDANCE_RAISED, growth_pct=20.0)
        self.assertAlmostEqual(g.implied_forward_ttm(1000.0), 1200.0)

    def test_growth_without_trailing_is_none(self):
        g = rev.Guidance(direction=rev.GUIDANCE_RAISED, growth_pct=20.0)
        self.assertIsNone(g.implied_forward_ttm(None))

    def test_a_direction_with_no_number_is_not_usable(self):
        self.assertFalse(rev.Guidance(direction=rev.GUIDANCE_RAISED).ok)

    def test_no_guidance_is_not_ok(self):
        self.assertFalse(rev.Guidance(target_inr=100.0).ok)


class TestConfluenceFlag(unittest.TestCase):
    RAISED = dict(direction=rev.GUIDANCE_RAISED, growth_pct=25.0, period="FY27")
    CUT = dict(direction=rev.GUIDANCE_LOWERED, growth_pct=-5.0, period="FY27")

    def test_raised_guidance_in_an_uptrend_is_green(self):
        flag = rev.confluence_flag(rev.Guidance(**self.RAISED),
                                   indicators.TREND_UPTREND)
        self.assertEqual(flag.level, rev.FLAG_GREEN)
        self.assertTrue(any("50 EMA" in r for r in flag.reasons))

    def test_lowered_guidance_with_a_broken_chart_is_red(self):
        flag = rev.confluence_flag(rev.Guidance(**self.CUT),
                                   indicators.TREND_BELOW_BOTH)
        self.assertEqual(flag.level, rev.FLAG_RED)

    def test_raised_guidance_the_market_ignores_is_amber(self):
        flag = rev.confluence_flag(rev.Guidance(**self.RAISED),
                                   indicators.TREND_BELOW_BOTH)
        self.assertEqual(flag.level, rev.FLAG_AMBER)

    def test_lowered_guidance_a_strong_chart_has_not_priced_is_amber(self):
        """The warning case: management cut the target and the stock has not
        reacted yet."""
        flag = rev.confluence_flag(rev.Guidance(**self.CUT),
                                   indicators.TREND_UPTREND)
        self.assertEqual(flag.level, rev.FLAG_AMBER)
        self.assertTrue(any("priced in" in r for r in flag.reasons))

    def test_no_guidance_means_no_flag(self):
        flag = rev.confluence_flag(rev.Guidance(), indicators.TREND_UPTREND)
        self.assertEqual(flag.level, rev.FLAG_NONE)
        self.assertEqual(flag.summary(), "")

    def test_a_supporting_order_book_strengthens_a_green_flag(self):
        rec = rev.Reconciliation(verdict=rev.VERDICT_ORDERS_AHEAD)
        flag = rev.confluence_flag(rev.Guidance(**self.RAISED),
                                   indicators.TREND_UPTREND, rec)
        self.assertEqual(flag.level, rev.FLAG_GREEN)
        self.assertTrue(any("order book" in r for r in flag.reasons))

    def test_green_downgrades_when_the_order_book_does_not_support_it(self):
        """A raised target with nothing contracted behind it is a claim, not
        evidence."""
        rec = rev.Reconciliation(verdict=rev.VERDICT_ORDERS_BEHIND)
        flag = rev.confluence_flag(rev.Guidance(**self.RAISED),
                                   indicators.TREND_UPTREND, rec)
        self.assertEqual(flag.level, rev.FLAG_AMBER)

    def test_the_trend_labels_match_indicators(self):
        """Copied strings would let a rename silently stop the flag firing."""
        self.assertEqual(rev._TREND_UPTREND, indicators.TREND_UPTREND)
        self.assertEqual(rev._TREND_BELOW_BOTH, indicators.TREND_BELOW_BOTH)


class TestConsensus(unittest.TestCase):
    def test_all_three_estimates_appear_separately(self):
        model = rev.forward_revenue(_seasonal())
        trailing = model.trailing_ttm
        orders = rev.order_backed(
            [{"value": trailing * 0.5, "execution_months": 12}], trailing)
        guidance = rev.Guidance(direction=rev.GUIDANCE_NEW, growth_pct=30.0,
                                period="FY28")
        got = rev.consensus(model, orders, guidance)
        self.assertIsNotNone(got["model_forward_ttm"])
        self.assertIsNotNone(got["order_forward_ttm"])
        self.assertIsNotNone(got["guidance_forward_ttm"])
        self.assertEqual(got["guidance_direction"], rev.GUIDANCE_NEW)

    def test_they_are_not_averaged_into_one_number(self):
        """Collapsing three differently-sourced estimates would destroy the
        disagreement that makes them worth computing."""
        got = rev.consensus(rev.RevenueOutlook(), rev.OrderBacked(),
                            rev.Guidance())
        self.assertNotIn("consensus", got)
        self.assertNotIn("average", got)


if __name__ == "__main__":
    unittest.main()
