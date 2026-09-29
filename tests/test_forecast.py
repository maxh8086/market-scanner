"""Tests for scanner.forecast.

The empirical backend is fully testable (it is arithmetic over a series). The
TimesFM backend is tested against stub models, because the point of the
defensive extraction is that an unexpected output shape degrades instead of
raising -- and that is exactly what a stub can verify.
"""

import unittest

from scanner import forecast as fc


def _ramp(n, start=100.0, step=1.0):
    return [start + i * step for i in range(n)]


class TestQuantile(unittest.TestCase):
    def test_endpoints_and_median(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertAlmostEqual(fc._quantile(values, 0.0), 1.0)
        self.assertAlmostEqual(fc._quantile(values, 1.0), 5.0)
        self.assertAlmostEqual(fc._quantile(values, 0.5), 3.0)

    def test_interpolates_between_points(self):
        self.assertAlmostEqual(fc._quantile([0.0, 10.0], 0.25), 2.5)

    def test_single_value(self):
        self.assertAlmostEqual(fc._quantile([7.0], 0.9), 7.0)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            fc._quantile([], 0.5)


class TestFromQuantileGrid(unittest.TestCase):
    """Quantile *levels* are not samples. Reading p10 off nine levels must give
    the first level, not the 10th percentile of the list of nine."""

    NINE = [90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0]

    def test_nine_levels_map_to_the_documented_grid(self):
        self.assertAlmostEqual(fc._from_quantile_grid(self.NINE, 0.10), 90.0)
        self.assertAlmostEqual(fc._from_quantile_grid(self.NINE, 0.50), 110.0)
        self.assertAlmostEqual(fc._from_quantile_grid(self.NINE, 0.90), 130.0)

    def test_between_grid_points_interpolates(self):
        self.assertAlmostEqual(fc._from_quantile_grid(self.NINE, 0.15), 92.5)

    def test_outside_the_grid_clamps_rather_than_extrapolating(self):
        narrow = [100.0, 110.0, 120.0]   # grid 0.25 / 0.50 / 0.75
        self.assertAlmostEqual(fc._from_quantile_grid(narrow, 0.10), 100.0)
        self.assertAlmostEqual(fc._from_quantile_grid(narrow, 0.90), 120.0)

    def test_unsorted_input_is_tolerated(self):
        self.assertAlmostEqual(
            fc._from_quantile_grid([130.0, 90.0, 110.0], 0.50), 110.0)

    def test_single_level_and_empty(self):
        self.assertAlmostEqual(fc._from_quantile_grid([7.0], 0.9), 7.0)
        with self.assertRaises(ValueError):
            fc._from_quantile_grid([], 0.5)


class TestHorizonReturns(unittest.TestCase):
    def test_count_is_series_minus_horizon(self):
        self.assertEqual(len(fc.horizon_returns(_ramp(100), horizon=10)), 90)

    def test_value_on_a_known_ramp(self):
        # 100 -> 110 over 10 steps is +10%.
        self.assertAlmostEqual(fc.horizon_returns(_ramp(11), horizon=10)[0], 10.0)

    def test_series_shorter_than_horizon_is_empty(self):
        self.assertEqual(fc.horizon_returns(_ramp(5), horizon=10), [])

    def test_non_positive_and_none_values_are_dropped(self):
        self.assertEqual(fc.horizon_returns([100, None, 0, -5, 110], horizon=1),
                         [10.0])


class TestMinHistory(unittest.TestCase):
    def test_scales_with_the_horizon(self):
        """A 6-month band needs about twice the history a 3-month band does,
        for the same number of independent windows."""
        self.assertEqual(fc.min_history(fc.HORIZON_3M),
                         fc.MIN_INDEPENDENT_WINDOWS * 63 + 1)
        self.assertGreater(fc.min_history(fc.HORIZON_6M),
                           2 * fc.min_history(fc.HORIZON_1M))

    def test_module_constant_matches_the_default_horizon(self):
        self.assertEqual(fc.MIN_HISTORY, fc.min_history(fc.HORIZON_DAYS))

    def test_three_months_of_trading_days_is_about_ninety_calendar_days(self):
        """63 trading days is the 3-month horizon; a reader should not have to
        convert it themselves."""
        self.assertEqual(fc.Outlook(horizon=fc.HORIZON_3M).months, 3.0)
        self.assertEqual(fc.Outlook(horizon=fc.HORIZON_6M).months, 6.0)
        self.assertEqual(fc.Outlook(horizon=fc.HORIZON_1M).months, 1.0)


class TestEmpiricalOutlook(unittest.TestCase):
    def test_short_history_is_an_error_not_a_guess(self):
        out = fc.empirical_outlook(_ramp(50))
        self.assertFalse(out.ok)
        self.assertIn("need", out.error)
        self.assertIsNone(out.good_pct)

    def test_the_error_names_the_independent_window_requirement(self):
        """Overlapping windows inflate the apparent sample size; the message has
        to say what is actually being demanded."""
        out = fc.empirical_outlook(_ramp(200), horizon=fc.HORIZON_3M)
        self.assertIn("independent windows", out.error)

    def test_independent_windows_is_reported_not_implied(self):
        out = fc.empirical_outlook(_ramp(640), horizon=fc.HORIZON_3M)
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.independent_windows, 640 // 63)

    def test_a_series_long_enough_for_three_months_may_be_short_for_six(self):
        closes = _ramp(fc.min_history(fc.HORIZON_3M) + 10)
        self.assertTrue(fc.empirical_outlook(closes, fc.HORIZON_3M).ok)
        self.assertFalse(fc.empirical_outlook(closes, fc.HORIZON_6M).ok)

    def test_scenarios_are_ordered(self):
        import random
        random.seed(7)
        closes = [100.0]
        for _ in range(800):
            closes.append(closes[-1] * (1 + random.gauss(0.0005, 0.02)))
        out = fc.empirical_outlook(closes)
        self.assertTrue(out.ok)
        self.assertLessEqual(out.bad_pct, out.good_pct)
        self.assertLessEqual(out.good_pct, out.very_good_pct)

    def test_steady_uptrend_gives_a_positive_central_case(self):
        out = fc.empirical_outlook(_ramp(600, 100.0, 0.5))
        self.assertTrue(out.ok, out.error)
        self.assertGreater(out.good_pct, 0)

    def test_band_width_is_p90_minus_p10(self):
        out = fc.Outlook(bad_pct=-12.0, good_pct=3.0, very_good_pct=25.0)
        self.assertAlmostEqual(out.band_width_pct, 37.0)

    def test_band_width_none_when_incomplete(self):
        self.assertIsNone(fc.Outlook(good_pct=3.0).band_width_pct)

    def test_flat_series_has_a_zero_band(self):
        out = fc.empirical_outlook([100.0] * 600)
        self.assertAlmostEqual(out.band_width_pct, 0.0)

    def test_summary_is_empty_when_not_ok(self):
        self.assertEqual(fc.Outlook(error="nope").summary(), "")

    def test_summary_shows_three_signed_numbers(self):
        out = fc.Outlook(bad_pct=-12.0, good_pct=3.0, very_good_pct=25.0)
        self.assertEqual(out.summary(), "-12% / +3% / +25%")


class TestMultiHorizon(unittest.TestCase):
    def setUp(self):
        import random
        random.seed(11)
        self.closes = [100.0]
        for _ in range(1200):
            self.closes.append(self.closes[-1] * (1 + random.gauss(0.0004, 0.018)))

    def test_one_outlook_per_horizon(self):
        got = fc.multi_horizon(self.closes)
        self.assertEqual(set(got), set(fc.HORIZONS))
        for h, out in got.items():
            with self.subTest(horizon=h):
                self.assertEqual(out.horizon, h)
                self.assertTrue(out.ok, out.error)

    def test_the_band_widens_with_the_horizon(self):
        """The random-walk null: dispersion grows with time. If a longer horizon
        came back narrower, the series or the arithmetic would be wrong."""
        got = fc.multi_horizon(self.closes)
        widths = [got[h].band_width_pct for h in fc.HORIZONS]
        self.assertEqual(widths, sorted(widths))

    def test_a_short_series_reports_per_horizon_instead_of_failing_whole(self):
        """A 2-year series supports a 1-month band and not a 6-month one; each
        horizon has to say so for itself."""
        got = fc.multi_horizon(_ramp(500))
        self.assertTrue(got[fc.HORIZON_1M].ok)
        self.assertFalse(got[fc.HORIZON_6M].ok)


class _StubTimesFM:
    """Returns (point, quantiles) in the documented shape."""

    def __init__(self, point_value=120.0, levels=None):
        self.point_value = point_value
        self.levels = levels if levels is not None else [
            120.0, 90.0, 95.0, 100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0]

    def forecast(self, inputs, freq):
        horizon = fc.HORIZON_DAYS
        return ([[self.point_value] * horizon], [[list(self.levels)] * horizon])


class _NoQuantileTimesFM(_StubTimesFM):
    def forecast(self, inputs, freq):
        return ([[self.point_value] * fc.HORIZON_DAYS], [[[1.0]] * fc.HORIZON_DAYS])


class _RaisingTimesFM:
    def forecast(self, inputs, freq):
        raise RuntimeError("shape mismatch")


class TestTimesFMOutlook(unittest.TestCase):
    def setUp(self):
        self.closes = [100.0] * fc.MIN_HISTORY

    def test_no_model_is_an_error(self):
        self.assertIn("no model", fc.timesfm_outlook(self.closes).error)

    def test_short_history_rejected_before_calling_the_model(self):
        out = fc.timesfm_outlook(_ramp(10), model=_RaisingTimesFM())
        self.assertIn("need", out.error, "must not reach the model at all")

    def test_quantiles_become_three_ordered_scenarios(self):
        out = fc.timesfm_outlook(self.closes, model=_StubTimesFM())
        self.assertTrue(out.ok, out.error)
        self.assertLessEqual(out.bad_pct, out.good_pct)
        self.assertLessEqual(out.good_pct, out.very_good_pct)

    def test_percentages_are_relative_to_the_last_close(self):
        closes = [50.0] * fc.MIN_HISTORY
        out = fc.timesfm_outlook(closes, model=_StubTimesFM(levels=[
            55.0, 45.0, 50.0, 55.0, 60.0, 65.0]))
        # bad quantile of [45,50,55,60,65] is 45 -> -10% from 50.
        self.assertAlmostEqual(out.bad_pct, -10.0)

    def test_missing_quantiles_degrade_to_the_point_forecast(self):
        out = fc.timesfm_outlook(self.closes, model=_NoQuantileTimesFM(130.0))
        self.assertAlmostEqual(out.good_pct, 30.0)
        self.assertIsNone(out.bad_pct, "no band may be invented")
        self.assertIn("point forecast only", out.note)
        # The caveat is a `note`, not an `error`. A caller that gates on `ok`
        # would otherwise throw away the central estimate the code went out of
        # its way to salvage.
        self.assertEqual(out.error, "")
        self.assertTrue(out.ok)
        self.assertFalse(out.has_band)

    def test_a_point_only_summary_does_not_format_a_none(self):
        # `ok` without `has_band` is reachable, and the old summary formatted
        # bad_pct with :+.0f -- which raises TypeError on None.
        out = fc.timesfm_outlook(self.closes, model=_NoQuantileTimesFM(130.0))
        self.assertEqual(out.summary(), "+30% (no band)")

    def test_a_raising_model_is_an_error_not_an_exception(self):
        out = fc.timesfm_outlook(self.closes, model=_RaisingTimesFM())
        self.assertFalse(out.ok)
        self.assertIn("forecast failed", out.error)


class TestScenariosAndAgreement(unittest.TestCase):
    def test_empirical_always_present_timesfm_only_when_asked(self):
        got = fc.scenarios(_ramp(600))
        self.assertIn(fc.BACKEND_EMPIRICAL, got)
        self.assertNotIn(fc.BACKEND_TIMESFM, got)
        both = fc.scenarios([100.0] * fc.MIN_HISTORY,
                            timesfm_model=_StubTimesFM())
        self.assertEqual(set(both), {fc.BACKEND_EMPIRICAL, fc.BACKEND_TIMESFM})

    def test_identical_outlooks_are_similar(self):
        a = fc.Outlook(backend="a", bad_pct=-10.0, good_pct=2.0, very_good_pct=15.0)
        b = fc.Outlook(backend="b", bad_pct=-10.0, good_pct=2.0, very_good_pct=15.0)
        self.assertEqual(fc.agreement(a, b), "similar")

    def test_a_much_narrower_model_band_is_flagged(self):
        a = fc.Outlook(bad_pct=-30.0, good_pct=0.0, very_good_pct=30.0)
        b = fc.Outlook(bad_pct=-2.0, good_pct=0.0, very_good_pct=2.0)
        self.assertEqual(fc.agreement(a, b), "model-narrower")

    def test_a_much_wider_model_band_is_flagged(self):
        a = fc.Outlook(bad_pct=-2.0, good_pct=0.0, very_good_pct=2.0)
        b = fc.Outlook(bad_pct=-40.0, good_pct=0.0, very_good_pct=40.0)
        self.assertEqual(fc.agreement(a, b), "model-wider")

    def test_incomparable_when_either_failed(self):
        good = fc.Outlook(bad_pct=-1.0, good_pct=0.0, very_good_pct=1.0)
        self.assertEqual(fc.agreement(good, fc.Outlook(error="x")),
                         "incomparable")


def _seasonal(n_years, season=4, base=100.0, shape=(0.9, 0.95, 1.0, 1.15),
              growth=1.1):
    """`n_years * season` values with a repeating shape and steady growth."""
    out = []
    for y in range(n_years):
        level = base * (growth ** y)
        for k in range(season):
            out.append(round(level * shape[k % len(shape)], 4))
    return out


class _StubLevels:
    """A level model: `quantiles[0][k]` is [mean, q10..q90] for step k+1."""

    def __init__(self, path, spread=10.0, with_quantiles=True):
        self.path = list(path)
        self.spread = spread
        self.with_quantiles = with_quantiles

    def forecast(self, inputs, freq):
        point = [list(self.path)]
        if not self.with_quantiles:
            # One level per step: too few for a band, so each step falls back
            # to the point value.
            return (point, [[[v] for v in self.path]])
        rows = []
        for v in self.path:
            # Nine ascending levels spanning v +/- spread, so q10 is v-spread,
            # q50 is v and q90 is v+spread.
            rows.append([v] + [v - self.spread + i * (self.spread / 4.0)
                               for i in range(9)])
        return (point, [rows])


class TestNaiveLevelForecast(unittest.TestCase):
    """The baseline path and, separately, whether it could band it.

    These two outcomes are the reason `note` exists. A series long enough to
    forecast but too short to backtest produces every number a caller wants and
    no interval around them, and that has to arrive as a caveat rather than as a
    failure -- `MIN_BACKTEST_ERRORS` says so in a comment, and for a while the
    code did the opposite.
    """

    def test_too_short_to_forecast_is_an_error(self):
        out = fc.naive_forecast([100.0, 110.0, 120.0], steps=3, season=4)
        self.assertFalse(out.ok)
        self.assertIn("need 9 points", out.error)
        self.assertEqual(out.note, "")

    def test_a_short_series_forecasts_without_a_band(self):
        # 9 quarters: enough for the seasonal rule (2*season+1), but only one
        # walk-forward origin, so there is nothing to build an interval from.
        out = fc.naive_forecast(_seasonal(2)[:8] + [250.0], steps=3, season=4)
        self.assertTrue(out.ok, "a point path is still a forecast")
        self.assertEqual(out.error, "", "a missing band is not a failure")
        self.assertFalse(out.has_band)
        self.assertIn("point forecast only", out.note)
        self.assertEqual(len(out.steps), 3)
        for band in out.steps:
            self.assertIsNotNone(band.good)
            self.assertIsNone(band.bad, "no band may be invented")

    def test_a_long_series_gets_a_band(self):
        out = fc.naive_forecast(_seasonal(4), steps=3, season=4)
        self.assertTrue(out.ok)
        self.assertTrue(out.has_band)
        self.assertEqual(out.note, "")
        for band in out.steps:
            self.assertLessEqual(band.bad, band.good)
            self.assertLessEqual(band.good, band.very_good)

    def test_the_central_scenario_stays_inside_its_own_band(self):
        """A rule that systematically undershoots has every backtest error
        positive, so even its 10th percentile lands above the raw path. Taking
        the raw path as the central case then put "bad" above "good" -- which
        happened on 42 of 252 real symbols at step 1 and 85 of 250 at step 2.

        Accelerating growth is what produces it: the seasonal rule scales last
        year's quarter by trailing growth, so it is always a step behind.
        """
        vals = _seasonal(5, growth=1.35)
        out = fc.naive_forecast(vals, steps=3, season=4)
        self.assertTrue(out.has_band)
        for band in out.steps:
            if band.has_band:
                self.assertLessEqual(band.bad, band.good, f"step {band.step}")
                self.assertLessEqual(band.good, band.very_good,
                                     f"step {band.step}")

    def test_the_band_is_dispersion_and_leaves_the_central_case_alone(self):
        """The mechanism behind the ordering, and the thing it must not do.

        The band is the spread of the measured error about its median, so the
        central case stays the seasonal rule's own output. Shifting it by that
        median instead would double-count growth the path already carries -- on
        WELCORP, growing 20% a year, it implied +52%.
        """
        vals = _seasonal(5, growth=1.35)
        raw = fc.seasonal_naive_path(vals, 3, 4)
        out = fc.naive_forecast(vals, steps=3, season=4)
        for band in out.steps:
            self.assertAlmostEqual(band.good, round(raw[band.step - 1], 4),
                                   places=3, msg=f"step {band.step}")

    def test_the_central_case_does_not_depend_on_whether_a_band_exists(self):
        """One quarter more history must not move the central path, only reveal
        a band around it. A correction available at some steps and not others
        would have put a discontinuity inside a single forecast.
        """
        vals = _seasonal(5, growth=1.35)
        short = fc.naive_forecast(vals[:13], steps=3, season=4)
        long_ = fc.naive_forecast(vals[:13], steps=1, season=4)
        self.assertFalse(short.steps[2].has_band)
        self.assertTrue(short.steps[0].has_band)
        # Step 3 has no band and step 1 does; both central values are still the
        # untouched rule, so the path has no step in it.
        raw = fc.seasonal_naive_path(vals[:13], 3, 4)
        for band in short.steps:
            self.assertAlmostEqual(band.good, round(raw[band.step - 1], 4),
                                   places=3, msg=f"step {band.step}")
        self.assertAlmostEqual(long_.steps[0].good, short.steps[0].good)

    def test_the_drift_cap_binds_the_optimistic_case_too(self):
        """`MAX_DRIFT` is a decision about how much growth is worth projecting,
        and it means as much for the optimistic scenario as for the middle. The
        central path is already damped by `_drift`; an unclamped very-good case
        would walk straight through the same ceiling.
        """
        vals = _seasonal(5, growth=3.0)
        out = fc.naive_forecast(vals, steps=3, season=4)
        n = len(vals)
        for band in out.steps:
            ceiling = vals[n - 4 + band.step - 1] * fc.MAX_DRIFT
            for which in ("bad", "good", "very_good"):
                value = getattr(band, which)
                if value is not None:
                    self.assertLessEqual(value, ceiling + 1e-6,
                                         f"step {band.step} {which}")

    def test_a_partial_band_says_which_steps_are_missing(self):
        """Thirteen quarters -- what a screener page gives -- and the reason this
        branch exists at all. Steps 1 and 2 band, step 3 cannot, and `total()`
        needs all three, so the summed scenario is empty. A reader seeing a
        step-1 band beside a blank total with no note would read it as a bug.
        """
        out = fc.naive_forecast(_seasonal(4)[:13], steps=3, season=4)
        self.assertTrue(out.ok)
        self.assertTrue(out.has_band)          # judged on step 1, which banded
        self.assertTrue(out.steps[1].has_band)
        self.assertFalse(out.steps[2].has_band)
        self.assertIsNone(out.total("bad"))
        self.assertIsNotNone(out.total("good"))
        self.assertIn("first 2 of 3 steps", out.note)
        self.assertIn("needs 14 points and there are 13", out.note)

    def test_one_more_quarter_completes_the_band(self):
        """The threshold in the note has to be the real one, so it is pinned
        from the other side: fourteen points and the caveat goes away."""
        out = fc.naive_forecast(_seasonal(4)[:14], steps=3, season=4)
        self.assertEqual(out.note, "")
        self.assertIsNotNone(out.total("bad"))

    def test_the_path_repeats_the_season_scaled_by_growth(self):
        # Four flat years growing 10% a year: the next Q1 should be the last
        # year's Q1 times roughly that growth, not the last quarter's value.
        vals = _seasonal(4, shape=(1.0, 1.0, 1.0, 1.0), growth=1.1)
        out = fc.naive_forecast(vals, steps=3, season=4)
        self.assertAlmostEqual(out.steps[0].good, vals[-4] * 1.1, places=2)

    def test_total_sums_one_scenario_and_is_none_when_incomplete(self):
        out = fc.naive_forecast(_seasonal(4), steps=3, season=4)
        self.assertAlmostEqual(out.total("good"),
                               sum(s.good for s in out.steps), places=3)
        short = fc.naive_forecast(_seasonal(2)[:8] + [250.0], steps=3, season=4)
        self.assertIsNone(short.total("bad"),
                          "summing a scenario that has no values must not "
                          "silently return a partial total")


class TestTimesFMLevels(unittest.TestCase):
    def test_bands_come_from_the_quantile_grid(self):
        out = fc.timesfm_levels(_seasonal(4), steps=3,
                                model=_StubLevels([300.0, 310.0, 320.0]),
                                season=4)
        self.assertTrue(out.ok)
        self.assertTrue(out.has_band)
        self.assertAlmostEqual(out.steps[0].good, 300.0)
        self.assertAlmostEqual(out.steps[0].bad, 290.0)
        self.assertAlmostEqual(out.steps[0].very_good, 310.0)

    def test_unusable_quantiles_degrade_to_a_note_not_an_error(self):
        out = fc.timesfm_levels(_seasonal(4), steps=3,
                                model=_StubLevels([300.0, 310.0, 320.0],
                                                  with_quantiles=False),
                                season=4)
        self.assertTrue(out.ok)
        self.assertEqual(out.error, "")
        self.assertFalse(out.has_band)
        self.assertIn("point forecast only", out.note)
        self.assertAlmostEqual(out.steps[0].good, 300.0)

    def test_a_raising_model_is_an_error(self):
        out = fc.timesfm_levels(_seasonal(4), steps=3,
                                model=_RaisingTimesFM(), season=4)
        self.assertFalse(out.ok)
        self.assertIn("forecast failed", out.error)

    def test_no_model_is_an_error_not_a_silent_empty(self):
        out = fc.timesfm_levels(_seasonal(4), steps=3, season=4)
        self.assertFalse(out.ok)
        self.assertIn("no model", out.error)


class TestPick(unittest.TestCase):
    """Which backend gets reported, when they disagree about what they have."""

    def _both(self, model=None, values=None):
        return fc.forecast_series(values or _seasonal(4), 3, season=4,
                                  model=model)

    def test_no_model_means_the_baseline(self):
        got = fc.pick(self._both())
        self.assertEqual(got.backend, fc.BACKEND_NAIVE)

    def test_the_model_wins_when_both_banded(self):
        got = fc.pick(self._both(_StubLevels([300.0, 310.0, 320.0])))
        self.assertEqual(got.backend, fc.BACKEND_TIMESFM)

    def test_a_banded_baseline_beats_a_point_only_model(self):
        got = fc.pick(self._both(_StubLevels([300.0, 310.0, 320.0],
                                             with_quantiles=False)))
        self.assertEqual(got.backend, fc.BACKEND_NAIVE,
                         "an interval measured from backtest error is worth "
                         "more than a slightly better number without one")
        self.assertTrue(got.has_band)

    def test_a_point_only_model_wins_when_the_baseline_cannot_band_either(self):
        short = _seasonal(2)[:8] + [250.0]
        got = fc.pick(self._both(_StubLevels([300.0, 310.0, 320.0],
                                             with_quantiles=False),
                                 values=short))
        self.assertEqual(got.backend, fc.BACKEND_TIMESFM)
        self.assertTrue(got.ok)

    def test_a_failed_model_never_wins(self):
        short = _seasonal(2)[:8] + [250.0]
        got = fc.pick(self._both(_RaisingTimesFM(), values=short))
        self.assertEqual(got.backend, fc.BACKEND_NAIVE)
        self.assertTrue(got.ok)

    def test_everything_failing_returns_the_baseline_with_its_reason(self):
        got = fc.pick(fc.forecast_series([1.0, 2.0], 3, season=4,
                                         model=_RaisingTimesFM()))
        self.assertFalse(got.ok)
        self.assertIn("need", got.error,
                      "the caller needs the reason, not an empty result")


class TestNoHardDependencies(unittest.TestCase):
    def test_module_imports_without_torch_or_timesfm(self):
        """The forecast is optional; importing it must not require the model."""
        import sys
        self.assertNotIn("timesfm", sys.modules)
        self.assertTrue(fc.empirical_outlook(_ramp(600)).ok)

    def test_load_timesfm_reports_absence_instead_of_raising(self):
        model, detail = fc.load_timesfm()
        if model is None:
            self.assertTrue(detail)


if __name__ == "__main__":
    unittest.main()
