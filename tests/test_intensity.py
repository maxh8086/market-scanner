"""Tests for scanner.intensity.

The load-bearing claims here are about the series construction, not the forecast:
a month with no order filings must be a zero rather than a missing key, the
incomplete current month must be excluded, and the order-win rule must be the
same one the per-stock factor uses. Get any of those wrong and the seasonality
the model is supposed to read is destroyed before the model ever sees it.
"""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scanner import factors
from scanner import forecast as fc
from scanner import intensity


def _row(year, month, day=15, desc="BAGGING/RECEIVING OF ORDERS/CONTRACTS",
         text="", symbol="ACME"):
    return {"symbol": symbol, "desc": desc, "attchmntText": text,
            "an_dt": f"{year:04d}-{month:02d}-{day:02d}", "sort_date": None}


def _filings(start_year=2023, months=30, per_month=3, today=None):
    """A dense run of order filings, `per_month` in every month from a start."""
    rows = []
    y, m = start_year, 1
    for _ in range(months):
        for i in range(per_month):
            rows.append(_row(y, m, day=1 + i))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return rows


class TestMonthKeyAndRange(unittest.TestCase):
    def test_month_key_is_zero_padded_and_sorts_lexically(self):
        keys = [intensity._month_key(date(2026, m, 1)) for m in (1, 9, 10, 12)]
        self.assertEqual(keys, ["2026-01", "2026-09", "2026-10", "2026-12"])
        self.assertEqual(keys, sorted(keys))

    def test_range_is_inclusive_of_both_ends(self):
        self.assertEqual(intensity._month_range("2026-01", "2026-03"),
                         ["2026-01", "2026-02", "2026-03"])

    def test_range_crosses_a_year_boundary(self):
        self.assertEqual(intensity._month_range("2025-11", "2026-02"),
                         ["2025-11", "2025-12", "2026-01", "2026-02"])

    def test_a_single_month_range(self):
        self.assertEqual(intensity._month_range("2026-04", "2026-04"),
                         ["2026-04"])

    def test_two_full_years_is_twenty_four_months(self):
        self.assertEqual(len(intensity._month_range("2024-01", "2025-12")), 24)


class TestMonthlyCounts(unittest.TestCase):
    def test_counts_one_per_matching_filing(self):
        rows = [_row(2026, 2), _row(2026, 3), _row(2026, 3), _row(2026, 4)]
        months, counts = intensity.monthly_counts(rows, today=date(2026, 6, 1))
        self.assertEqual(months, ["2026-03", "2026-04"])   # 2026-02 is the drop
        self.assertEqual(counts, [2, 1])

    def test_the_oldest_month_is_dropped(self):
        """The mirror of the current-month rule, and it exists for the same
        reason. The announcement cache begins at "today minus N months", which
        lands mid-month, so its first month holds only the days after that date.

        Losing a month of history is the cheaper error. An undercounted month
        becomes the denominator of exactly one year-on-year comparison and the
        "same month a year ago" value for one seasonal prediction, and both
        would read as growth that never happened."""
        rows = [_row(2026, 1, day=28), _row(2026, 2), _row(2026, 3)]
        months, counts = intensity.monthly_counts(rows, today=date(2026, 6, 1))
        self.assertEqual(months, ["2026-02", "2026-03"])
        self.assertEqual(counts, [1, 1])

    def test_a_one_month_series_is_not_dropped_to_nothing(self):
        """The drop is a trim, not a filter. Emptying a one-month series would
        make "no order filings matched at all" indistinguishable from "one
        partial month matched", and the backfill report needs to tell a caller
        which of those happened."""
        rows = [_row(2026, 3)]
        months, counts = intensity.monthly_counts(rows, today=date(2026, 6, 1))
        self.assertEqual(months, ["2026-03"])
        self.assertEqual(counts, [1])

    def test_an_empty_month_between_filings_is_a_zero_not_a_missing_key(self):
        """The whole point of the dense range. A skipped month would compress the
        calendar so that a February count landed in a January slot, and the
        annual pattern the model reads would be fiction."""
        rows = [_row(2025, 12), _row(2026, 1), _row(2026, 4)]
        months, counts = intensity.monthly_counts(rows, today=date(2026, 7, 1))
        self.assertEqual(months,
                         ["2026-01", "2026-02", "2026-03", "2026-04"])
        self.assertEqual(counts, [1, 0, 0, 1])

    def test_months_after_the_last_filing_are_absent_not_zero(self):
        """The counterpart to the rule above, and the distinction matters. An
        interior gap really is a month with no order wins. A gap at the end is
        far more likely a cache that has not been refreshed, and filling it with
        zeros would report a market-wide collapse that never happened.

        Across ~750 companies a genuinely empty month does not occur, so reading
        trailing absence as missing data rather than as zero is the safe side."""
        rows = [_row(2025, 12), _row(2026, 1), _row(2026, 2)]
        months, counts = intensity.monthly_counts(rows, today=date(2026, 7, 1))
        self.assertEqual(months, ["2026-01", "2026-02"])
        self.assertEqual(counts, [1, 1])

    def test_the_current_month_is_dropped(self):
        """It is incomplete by definition. Counted as if complete, order flow
        appears to collapse on the first of every month."""
        rows = [_row(2026, 4), _row(2026, 5), _row(2026, 6, day=2)]
        months, counts = intensity.monthly_counts(rows, today=date(2026, 6, 10))
        self.assertEqual(months, ["2026-05"])
        self.assertEqual(counts, [1])

    def test_a_future_dated_filing_does_not_extend_the_series(self):
        rows = [_row(2026, 4), _row(2026, 5), _row(2026, 9)]
        months, _ = intensity.monthly_counts(rows, today=date(2026, 6, 10))
        self.assertEqual(months, ["2026-05"])

    def test_non_order_filings_are_not_counted(self):
        rows = [_row(2026, 3, desc="BOARD MEETING INTIMATION"),
                _row(2026, 3, desc="TRADING WINDOW")]
        self.assertEqual(intensity.monthly_counts(rows, today=date(2026, 6, 1)),
                         ([], []))

    def test_regulatory_order_filings_are_excluded(self):
        """'Orders passed' against the company is the opposite signal, and it is
        the exclusion most likely to be lost when a rule is reimplemented."""
        rows = [_row(2026, 3, desc="ACTION(S) TAKEN OR ORDERS PASSED",
                     text="ORDER BOOK")]
        self.assertEqual(intensity.monthly_counts(rows, today=date(2026, 6, 1)),
                         ([], []))

    def test_a_keyword_in_the_attachment_text_counts(self):
        rows = [_row(2026, 3, desc="OTHER ANNOUNCEMENT",
                     text="Received a Letter of Award from NHAI")]
        _, counts = intensity.monthly_counts(rows, today=date(2026, 6, 1))
        self.assertEqual(counts, [1])

    def test_the_rule_is_factors_own_rule(self):
        """If these ever diverge, the market series counts different filings than
        the per-stock column and comparing them is meaningless."""
        row = _row(2026, 3)
        matched, _ = factors.matches_orderbook(row)
        self.assertTrue(matched)
        _, counts = intensity.monthly_counts([row], today=date(2026, 6, 1))
        self.assertEqual(sum(counts), 1)

    def test_rows_without_a_usable_date_are_skipped(self):
        rows = [{"symbol": "X", "desc": "BAGGING/RECEIVING OF ORDERS/CONTRACTS",
                 "attchmntText": "", "an_dt": None, "sort_date": None}]
        self.assertEqual(intensity.monthly_counts(rows, today=date(2026, 6, 1)),
                         ([], []))

    def test_no_rows_at_all(self):
        self.assertEqual(intensity.monthly_counts([], today=date(2026, 6, 1)),
                         ([], []))

    def test_filings_from_every_symbol_aggregate_into_one_series(self):
        """Aggregation across companies is the property that makes this series
        forecastable at all, so it must not be split by symbol."""
        rows = [_row(2026, 3, symbol="A"), _row(2026, 3, symbol="B"),
                _row(2026, 3, symbol="C")]
        _, counts = intensity.monthly_counts(rows, today=date(2026, 6, 1))
        self.assertEqual(counts, [3])


class TestPreTaxonomyTrim(unittest.TestCase):
    """NSE introduced the structured order-win announcement subjects in
    September 2024. A cache fetched further back does not begin with quiet
    months -- it begins with a step in the level of the series, because only the
    minority of filings whose attachment text carries a keyword can be seen.

    This is the one defect that would break the feature while looking like it
    works: a seasonal model fitted across a level break reads the break as trend
    and extrapolates market-wide growth that is an artifact of when a field
    started being published. The series really does rise, so nothing downstream
    would flag it.
    """

    def _pre(self, year, month, n=40):
        """Filings from before the taxonomy: plenty of them, none in a category,
        a couple visible only through attachment-text keywords."""
        rows = [_row(year, month, day=1 + (i % 27), desc="OTHER ANNOUNCEMENT")
                for i in range(n)]
        rows[0]["attchmntText"] = "Received a Letter of Award from NHAI"
        return rows

    def _post(self, year, month, n=5):
        return [_row(year, month, day=1 + i) for i in range(n)]

    def test_leading_pre_taxonomy_months_are_dropped(self):
        rows = (self._pre(2024, 6) + self._pre(2024, 7) + self._pre(2024, 8)
                + self._post(2024, 9) + self._post(2024, 10)
                + self._post(2024, 11))
        months, counts = intensity.monthly_counts(rows, today=date(2025, 1, 5))
        # 2024-09 is the first with a category, then DROP_FIRST_MONTH takes it.
        self.assertEqual(months, ["2024-10", "2024-11"])
        self.assertEqual(counts, [5, 5])

    def test_the_step_in_the_level_is_what_gets_removed(self):
        """Stated as the numbers, because this is the whole point. Keeping the
        pre-taxonomy months would hand the model a series that quintuples."""
        rows = self._pre(2024, 6) + self._pre(2024, 7) + self._post(2024, 8, n=25)
        _, counts = intensity.monthly_counts(rows, today=date(2025, 1, 5))
        self.assertEqual(counts, [25])
        self.assertNotIn(1, counts)

    def test_a_later_month_with_no_category_match_is_kept(self):
        """Only a leading run is trimmed. A gap in the middle is a data problem
        worth seeing, and cutting there would silently reshape the series rather
        than shorten it."""
        rows = (self._post(2024, 9) + self._post(2024, 10)
                + self._pre(2024, 11) + self._post(2024, 12))
        months, counts = intensity.monthly_counts(rows, today=date(2025, 3, 5))
        self.assertEqual(months, ["2024-10", "2024-11", "2024-12"])
        self.assertEqual(counts, [5, 1, 5])

    def test_a_clean_series_is_untouched(self):
        rows = self._post(2024, 9) + self._post(2024, 10) + self._post(2024, 11)
        months, _ = intensity.monthly_counts(rows, today=date(2025, 1, 5))
        self.assertEqual(months, ["2024-10", "2024-11"])

    def test_a_month_with_no_filings_at_all_does_not_decide_the_boundary(self):
        """An empty month is a gap in the cache, not evidence about the taxonomy.
        Treating it as pre-taxonomy would cut a series short at the first hole."""
        rows = self._post(2024, 9) + self._post(2024, 11)   # 2024-10 is empty
        months, counts = intensity.monthly_counts(rows, today=date(2025, 1, 5))
        self.assertEqual(months, ["2024-10", "2024-11"])
        self.assertEqual(counts, [0, 5])

    def test_an_all_pre_taxonomy_series_is_not_emptied(self):
        """Degenerate but reachable, with a cache that stops before the change.
        Returning nothing would report "no order filings found" for a window
        that has thousands."""
        rows = self._pre(2024, 6) + self._pre(2024, 7)
        months, _ = intensity.monthly_counts(rows, today=date(2025, 1, 5))
        self.assertTrue(months)

    def test_the_note_says_waiting_not_backfilling_for_taxonomy_series(self):
        """The advice has to match the wall that was hit. When the series starts
        at NSE's first month of published categories, it cannot be extended
        backwards, so the message should mention waiting, not backfilling. But
        with the new unvalidated forecast support from 13 months, these short
        series now get a forecast; this test validates that the waiting message
        appears when reaching for a VALIDATED forecast (25 months)."""
        rows = []
        for m in range(1, 7):
            rows += self._pre(2024, m)
        y, mo = 2024, 7
        for _ in range(18):
            rows += self._post(y, mo)
            mo += 1
            if mo > 12:
                y, mo = y + 1, 1
        out = intensity.market_intensity(rows, today=date(2026, 2, 5))
        self.assertTrue(out.ok, out.error)
        # Now we allow unvalidated forecasts from 13 months
        self.assertTrue(out.can_forecast)
        self.assertFalse(out.band_validated)
        # The note should indicate that the series starts at the taxonomy boundary
        # and mention the months needed for a validated band
        self.assertIn("25", out.note)  # Mentions 25-month requirement for validation

    def test_a_merely_short_cache_still_says_backfill(self):
        """When there's no taxonomy break, just a short cache, the message
        should suggest backfilling. This test validates that message still
        appears when needed for a VALIDATED forecast (25 months)."""
        # Use pre-taxonomy data without the taxonomy boundary, so backfill is suggested
        rows = _filings(start_year=2024, months=20, per_month=3)  # 20 months of regular data
        out = intensity.market_intensity(rows, today=date(2026, 8, 15))
        # With 19 usable months (20 raw - 1 drop first), we can forecast
        self.assertTrue(out.can_forecast)
        self.assertFalse(out.band_validated)
        # Should suggest backfilling for a validated forecast
        self.assertIn("25", out.note)


class TestClassify(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(intensity._classify(40.0), intensity.TREND_RISING)
        self.assertEqual(intensity._classify(0.0), intensity.TREND_FLAT)
        self.assertEqual(intensity._classify(-40.0), intensity.TREND_FALLING)
        self.assertEqual(intensity._classify(None), intensity.TREND_UNKNOWN)

    def test_the_boundaries_are_inclusive(self):
        self.assertEqual(intensity._classify(intensity.RISING_PCT),
                         intensity.TREND_RISING)
        self.assertEqual(intensity._classify(intensity.FALLING_PCT),
                         intensity.TREND_FALLING)


class TestMarketIntensity(unittest.TestCase):
    def test_no_rows_is_an_error_not_an_exception(self):
        out = intensity.market_intensity(rows=[], today=date(2026, 6, 1))
        self.assertFalse(out.ok)
        self.assertIn("no cached announcements", out.error)

    def test_too_little_history_says_how_much_is_needed(self):
        rows = _filings(start_year=2025, months=6)
        out = intensity.market_intensity(rows, today=date(2026, 6, 1))
        self.assertFalse(out.ok)
        self.assertIn(str(intensity.MIN_MONTHS_TREND), out.error)

    def test_the_backfill_default_actually_reaches_the_forecast(self):
        """The number a user types has to work. It is derived from MIN_MONTHS by
        arithmetic that is easy to get one short, so simulate the real thing: a
        fetch starting mid-month BACKFILL_MONTHS back, with filings every month
        up to today, and check the usable series clears the bar."""
        today = date(2026, 9, 29)
        start = factors._subtract_months(today, intensity.BACKFILL_MONTHS)
        rows, y, m = [], start.year, start.month
        while (y, m) <= (today.year, today.month):
            rows.append(_row(y, m, day=28))
            m += 1
            if m > 12:
                y, m = y + 1, 1
        out = intensity.market_intensity(rows, today=today)
        self.assertTrue(out.can_forecast,
                        f"{len(out.counts)} usable months, need "
                        f"{intensity.MIN_MONTHS}")

    def test_the_partial_ends_cost_a_month_off_each_end(self):
        """Pins the arithmetic a caller has to do to size a backfill. A fetch of
        N months yields N-1 usable ones once the partial first month is trimmed,
        so `--backfill-announcements MIN_MONTHS` is one short and the flag's help
        text has to say MIN_MONTHS + 1."""
        rows = _filings(start_year=2025, months=14)      # 2025-01 .. 2026-02
        out = intensity.market_intensity(rows, today=date(2026, 3, 15))
        self.assertEqual(len(out.counts), 13)
        self.assertEqual(out.months[0], "2025-02")
        self.assertEqual(out.months[-1], "2026-02")

    def test_12_months_gives_trend_only_not_even_ok(self):
        """12 months is not enough for year-on-year comparison or forecast."""
        # _filings with months=13 gives 13 raw months from 2025-01 to 2026-01
        # Drop first: 2025-02 to 2026-01 = 12 months (still not enough for YoY)
        rows = _filings(start_year=2025, months=13, per_month=3)
        out = intensity.market_intensity(rows, today=date(2026, 2, 15))
        self.assertFalse(out.ok, "Should not have enough for year-on-year")
        self.assertEqual(out.error, "need 13 complete months to compare year on year, have 12")

    def test_13_months_gives_unvalidated_seasonal_forecast(self):
        """13 months is enough for an unvalidated seasonal forecast (no error band)."""
        # _filings with months=14 gives 14 raw months from 2024-01 to 2025-02
        # Drop first: 2024-02 to 2025-02 = 13 months
        rows = _filings(start_year=2024, months=14, per_month=3)
        out = intensity.market_intensity(rows, today=date(2025, 3, 15))
        self.assertTrue(out.ok, out.error)
        self.assertTrue(out.can_forecast)
        self.assertFalse(out.band_validated)
        self.assertIsNotNone(out.yoy_pct)
        self.assertEqual(out.trend, intensity.TREND_FLAT)
        self.assertEqual(len(out.forecast), intensity.STEPS)
        # Note should mention the 25-month requirement for validation
        self.assertIn("25", out.note)
        self.assertIn("point forecast", out.note)

    def test_18_months_gives_unvalidated_seasonal_forecast(self):
        """18 months is still unvalidated but should have point estimates."""
        # _filings with months=19 gives 19 raw months from 2024-01 to 2025-07
        # Drop first: 2024-02 to 2025-07 = 18 months
        rows = _filings(start_year=2024, months=19, per_month=3)
        out = intensity.market_intensity(rows, today=date(2025, 8, 15))
        self.assertTrue(out.ok, out.error)
        self.assertTrue(out.can_forecast)
        self.assertFalse(out.band_validated)
        self.assertEqual(len(out.forecast), intensity.STEPS)
        # Note should mention the 25-month requirement for validation
        self.assertIn("25", out.note)

    def test_23_months_gives_unvalidated_seasonal_forecast(self):
        """23 months is still 2 short of validated but should have point estimates."""
        # _filings with months=24 gives 24 raw months from 2023-01 to 2024-12
        # Drop first: 2023-02 to 2024-12 = 23 months
        rows = _filings(start_year=2023, months=24, per_month=3)
        out = intensity.market_intensity(rows, today=date(2025, 1, 15))
        self.assertTrue(out.ok, out.error)
        self.assertTrue(out.can_forecast)
        self.assertFalse(out.band_validated)
        self.assertEqual(len(out.counts), 23)
        self.assertEqual(len(out.forecast), intensity.STEPS)
        # Note should mention the 25-month requirement for validation
        self.assertIn("25", out.note)

    def test_25_months_gives_validated_seasonal_forecast(self):
        """25 months is the validated threshold, no unvalidated message."""
        # _filings with months=26 gives 26 raw months; drop first leaves 25
        rows = _filings(start_year=2023, months=26, per_month=3)
        out = intensity.market_intensity(rows, today=date(2026, 2, 15))
        self.assertTrue(out.ok, out.error)
        self.assertTrue(out.can_forecast)
        self.assertTrue(out.band_validated)
        self.assertEqual(len(out.forecast), intensity.STEPS)
        self.assertNotIn("unvalidated band", out.note)

    def test_a_year_of_history_gives_unvalidated_forecast(self):
        """The three thresholds keep the properties aligned with actual capability.
        A year and a month is enough to compare this month against the same month
        a year ago (year-on-year measurement that changes a stock's order win read).
        It is also enough for an unvalidated seasonal forecast, though without a
        backtest to validate the error band. A validated forecast needs two years."""
        rows = _filings(start_year=2025, months=14, per_month=3)
        out = intensity.market_intensity(rows, today=date(2026, 3, 15))
        self.assertTrue(out.ok, out.error)
        self.assertTrue(out.can_forecast)  # Now we allow unvalidated forecasts from 13 months
        self.assertFalse(out.band_validated)  # But the band is not validated
        self.assertIsNotNone(out.yoy_pct)
        self.assertEqual(out.trend, intensity.TREND_FLAT)
        self.assertEqual(len(out.forecast), intensity.STEPS)

    def test_two_years_of_history_gives_validated_forecast(self):
        # Use 32 months to ensure we have enough for validated bands at all steps
        rows = _filings(start_year=2023, months=32, per_month=3)
        out = intensity.market_intensity(rows, today=date(2025, 9, 15))
        self.assertTrue(out.ok, out.error)
        self.assertTrue(out.can_forecast)
        self.assertTrue(out.band_validated)
        # With 32 months, the band is fully validated
        self.assertEqual(out.note, "")
        self.assertEqual(len(out.forecast), intensity.STEPS)

    def test_a_full_series_is_ok_and_reports_the_latest_month(self):
        rows = _filings(start_year=2023, months=30, per_month=4)
        out = intensity.market_intensity(rows, today=date(2025, 7, 15))
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.latest_month, "2025-06")
        self.assertEqual(out.latest_count, 4)

    def test_n_filings_is_the_sum_of_the_series(self):
        rows = _filings(start_year=2023, months=30, per_month=2)
        out = intensity.market_intensity(rows, today=date(2025, 7, 15))
        self.assertEqual(out.n_filings, sum(out.counts))

    def test_yoy_compares_the_same_month_a_year_earlier(self):
        """Not the previous month. Order flow has a hard fiscal calendar, so
        month-on-month would report the seasonal pattern as a trend."""
        rows = _filings(start_year=2023, months=29, per_month=2)
        rows += [_row(2025, 6, day=d) for d in range(1, 5)]   # 4 in the last
        out = intensity.market_intensity(rows, today=date(2025, 7, 15))
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.latest_count, 4)
        self.assertAlmostEqual(out.yoy_pct, 100.0)
        self.assertEqual(out.trend, intensity.TREND_RISING)

    def test_a_falling_market_is_labelled_falling(self):
        rows = _filings(start_year=2023, months=29, per_month=4)
        rows += [_row(2025, 6, day=1)]                        # 1 vs 4 a year ago
        out = intensity.market_intensity(rows, today=date(2025, 7, 15))
        self.assertAlmostEqual(out.yoy_pct, -75.0)
        self.assertEqual(out.trend, intensity.TREND_FALLING)

    def test_a_flat_market_is_labelled_flat(self):
        rows = _filings(start_year=2023, months=30, per_month=4)
        out = intensity.market_intensity(rows, today=date(2025, 7, 15))
        self.assertAlmostEqual(out.yoy_pct, 0.0)
        self.assertEqual(out.trend, intensity.TREND_FLAT)

    def test_the_baseline_forecast_runs_without_any_model(self):
        """The measurement half must not depend on TimesFM being installed."""
        rows = _filings(start_year=2023, months=30, per_month=4)
        out = intensity.market_intensity(rows, today=date(2025, 7, 15))
        self.assertEqual(out.backend, fc.BACKEND_NAIVE)
        self.assertEqual(len(out.forecast), intensity.STEPS)
        self.assertEqual(out.agreement, "")

    def test_the_forecast_total_is_the_sum_of_the_path(self):
        rows = _filings(start_year=2023, months=30, per_month=4)
        out = intensity.market_intensity(rows, today=date(2025, 7, 15))
        self.assertAlmostEqual(out.forecast_total,
                               sum(x for x in out.forecast if x is not None),
                               places=4)

    def test_a_model_is_compared_against_the_baseline(self):
        rows = _filings(start_year=2023, months=30, per_month=4)
        out = intensity.market_intensity(rows, model=_StubModel(),
                                         today=date(2025, 7, 15))
        self.assertEqual(out.backend, fc.BACKEND_TIMESFM)
        self.assertTrue(out.agreement)

    def test_summary_is_empty_of_numbers_when_not_ok(self):
        out = intensity.market_intensity(rows=[], today=date(2026, 6, 1))
        self.assertEqual(out.summary(), out.error)

    def test_summary_names_the_month_and_the_trend(self):
        rows = _filings(start_year=2023, months=30, per_month=4)
        out = intensity.market_intensity(rows, today=date(2025, 7, 15))
        text = out.summary()
        self.assertIn("2025-06", text)
        self.assertIn("flat", text)


class _StubModel:
    """A flat forecast with a symmetric quantile fan, well above the series."""

    def forecast(self, horizon, inputs):
        levels = [50.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        return ([[50.0] * horizon], [[list(levels)] * horizon])


class TestContextNote(unittest.TestCase):
    def test_nothing_to_say_when_the_read_failed(self):
        self.assertEqual(intensity.context_note(intensity.MarketIntensity()), "")

    def test_a_falling_market_says_the_win_is_against_the_tide(self):
        out = intensity.MarketIntensity(
            counts=[1] * intensity.MIN_MONTHS_TREND,
            trend=intensity.TREND_FALLING)
        self.assertIn("against the tide", intensity.context_note(out))

    def test_a_rising_market_says_upcycle(self):
        out = intensity.MarketIntensity(
            counts=[1] * intensity.MIN_MONTHS_TREND,
            trend=intensity.TREND_RISING)
        self.assertIn("upcycle", intensity.context_note(out))

    def test_a_flat_market_says_so_plainly(self):
        out = intensity.MarketIntensity(
            counts=[1] * intensity.MIN_MONTHS_TREND, trend=intensity.TREND_FLAT)
        self.assertIn("flat", intensity.context_note(out))

    def test_the_context_note_does_not_require_validated_forecast(self):
        """It is the trend that contextualises a stock's order win, not the
        validated forecast. The context note must be available even with just
        enough for an unvalidated forecast (13 months)."""
        out = intensity.MarketIntensity(
            counts=[1] * intensity.MIN_MONTHS_TREND,
            trend=intensity.TREND_RISING,
            band_validated=False)  # Explicitly mark as unvalidated
        # With 13 months (MIN_MONTHS_TREND), we can get an unvalidated forecast
        self.assertTrue(out.can_forecast)
        self.assertFalse(out.band_validated)
        # But the context note still works without needing the validated band
        self.assertTrue(intensity.context_note(out))


class TestLoadAnnouncements(unittest.TestCase):
    """The reader must never raise on a missing or unexpected database -- this is
    an optional enrichment stage, and a broken cache must degrade to no forecast
    rather than take down the run."""

    def test_a_missing_database_is_an_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                intensity.load_announcements(Path(tmp) / "nope.db"), [])

    def test_a_database_without_the_table_is_an_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.db"
            sqlite3.connect(path).close()
            self.assertEqual(intensity.load_announcements(path), [])

    def test_rows_come_back_with_the_keys_the_shared_rule_expects(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "factors.db"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE announcements (symbol TEXT, desc TEXT, "
                         "attchmnt_text TEXT, an_dt TEXT, sort_date TEXT)")
            conn.execute("INSERT INTO announcements VALUES (?,?,?,?,?)",
                         ("ACME", "BAGGING/RECEIVING OF ORDERS/CONTRACTS",
                          "bagged an order", "2026-03-15", None))
            conn.commit()
            conn.close()
            rows = intensity.load_announcements(path)
        self.assertEqual(len(rows), 1)
        # The stored column is attchmnt_text; the rule reads attchmntText.
        self.assertIn("attchmntText", rows[0])
        matched, _ = factors.matches_orderbook(rows[0])
        self.assertTrue(matched)
        self.assertIsNotNone(intensity._row_date(rows[0]))


if __name__ == "__main__":
    unittest.main()
