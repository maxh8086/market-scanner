"""Tests for the glue in enrich.py, narrowed to where a wrong answer is silent.

Most of this project's logic lives in `scanner/` and is tested there. What is
left in enrich.py is plumbing, and plumbing fails quietly: a unit conversion at
the wrong boundary, a "newest wins" comparison that picks the oldest, a column
filled from the wrong source. None of those raise. All of them poison a column
that a reader will take at face value.
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

import enrich
from scanner import docstore, llm, orderval, revenue, significance


def _filing(seq_id, symbol="ACME", kind=enrich.KIND_ORDER, an_date="2026-05-01",
            rupees=None, confidence=None):
    return {"seq_id": seq_id, "symbol": symbol, "kind": kind,
            "an_date": an_date, "regex_rupees": rupees,
            "regex_confidence": confidence, "isin": "INE000A01001"}


class _DocstoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = docstore.open_db(Path(self._tmp.name) / "docs.json")
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.db.close)


class TestOrdersForSymbol(_DocstoreCase):
    def test_a_trusted_regex_value_is_converted_to_crore(self):
        """The load-bearing assertion in this file. Screener revenue is in crore
        and order values are in rupees, so `order_backed` divides one by the
        other and a missed conversion is out by a factor of ten million."""
        docstore.put_filing(self.db, _filing(
            "s1", rupees=2_000 * significance.CRORE,
            confidence=orderval.CONF_ANCHOR_SCALED))
        orders = enrich._orders_for_symbol(self.db, "ACME")
        self.assertEqual(len(orders), 1)
        self.assertAlmostEqual(orders[0]["value"], 2_000.0)

    def test_an_untrusted_regex_value_falls_back_to_the_model(self):
        """A bare number with no anchor is the case the regex gets wrong, so the
        model's reading wins -- and it must be converted too."""
        docstore.put_filing(self.db, _filing("s2", rupees=999 * significance.CRORE,
                                             confidence="guess"))
        docstore.put_extraction(self.db, "s2", llm.KIND_ORDER,
                                {"data": {"order_value_inr": 150 * significance.CRORE,
                                          "execution_months": 18}})
        orders = enrich._orders_for_symbol(self.db, "ACME")
        self.assertAlmostEqual(orders[0]["value"], 150.0)
        self.assertEqual(orders[0]["execution_months"], 18)

    def test_a_filing_with_no_value_from_either_source_is_dropped(self):
        docstore.put_filing(self.db, _filing("s3"))
        self.assertEqual(enrich._orders_for_symbol(self.db, "ACME"), [])

    def test_a_zero_value_is_not_an_order(self):
        docstore.put_filing(self.db, _filing(
            "s4", rupees=0, confidence=orderval.CONF_ANCHOR_SCALED))
        self.assertEqual(enrich._orders_for_symbol(self.db, "ACME"), [])

    def test_only_order_filings_are_considered(self):
        docstore.put_filing(self.db, _filing(
            "s5", kind=enrich.KIND_EXPANSION, rupees=500 * significance.CRORE,
            confidence=orderval.CONF_ANCHOR_SCALED))
        self.assertEqual(enrich._orders_for_symbol(self.db, "ACME"), [])

    def test_a_missing_execution_period_is_zero_not_none(self):
        """`order_backed` divides by it, so None would be a TypeError on a path
        that is otherwise working."""
        docstore.put_filing(self.db, _filing(
            "s6", rupees=100 * significance.CRORE,
            confidence=orderval.CONF_ANCHOR_BARE))
        self.assertEqual(enrich._orders_for_symbol(self.db, "ACME")[0]
                         ["execution_months"], 0)

    def test_every_order_is_returned_not_just_the_largest(self):
        for i, cr in enumerate((100, 300, 200)):
            docstore.put_filing(self.db, _filing(
                f"m{i}", rupees=cr * significance.CRORE,
                confidence=orderval.CONF_ANCHOR_SCALED))
        values = sorted(o["value"] for o in
                        enrich._orders_for_symbol(self.db, "ACME"))
        self.assertEqual(values, [100.0, 200.0, 300.0])


class TestGuidanceForSymbol(_DocstoreCase):
    def _put(self, seq_id, an_date, data):
        docstore.put_filing(self.db, _filing(seq_id, kind=enrich.KIND_GUIDANCE,
                                             an_date=an_date))
        docstore.put_extraction(self.db, seq_id, llm.KIND_GUIDANCE,
                                {"data": data})

    def test_the_newest_target_wins_not_the_largest(self):
        """The opposite rule from order values, and the reason is the point: an
        order win stays true, but a target is superseded the moment management
        issues a new one. Reporting last year's raise after this year's cut
        would be worse than reporting nothing."""
        self._put("g1", "2025-05-01", {
            "has_guidance": True, "is_management_statement": True,
            "direction": revenue.GUIDANCE_RAISED, "growth_pct": 25.0,
            "verbatim": "raising our outlook"})
        self._put("g2", "2026-05-01", {
            "has_guidance": True, "is_management_statement": True,
            "direction": revenue.GUIDANCE_LOWERED, "growth_pct": 5.0,
            "verbatim": "moderating our outlook"})
        g = enrich._guidance_for_symbol(self.db, "ACME")
        self.assertEqual(g.direction, revenue.GUIDANCE_LOWERED)
        self.assertAlmostEqual(g.growth_pct, 5.0)

    def test_a_broker_forecast_is_not_guidance(self):
        """A third party's number quoted inside a company presentation is not a
        commitment by management, and the prompt is asked to say which it is."""
        self._put("g3", "2026-05-01", {
            "has_guidance": True, "is_management_statement": False,
            "direction": revenue.GUIDANCE_NEW, "growth_pct": 30.0})
        self.assertFalse(enrich._guidance_for_symbol(self.db, "ACME").ok)

    def test_a_filing_with_no_guidance_in_it_is_skipped(self):
        self._put("g4", "2026-05-01", {"has_guidance": False,
                                       "is_management_statement": True})
        self.assertFalse(enrich._guidance_for_symbol(self.db, "ACME").ok)

    def test_no_guidance_filings_gives_an_empty_guidance_not_none(self):
        g = enrich._guidance_for_symbol(self.db, "ACME")
        self.assertIsInstance(g, revenue.Guidance)
        self.assertFalse(g.ok)

    def test_the_verbatim_quote_is_carried_through(self):
        """The column exists so a reader can judge the model's reading rather
        than trust it, which only works if the words survive."""
        self._put("g5", "2026-05-01", {
            "has_guidance": True, "is_management_statement": True,
            "direction": revenue.GUIDANCE_NEW, "growth_pct": 18.0,
            "verbatim": "we guide to 18-20% revenue growth"})
        g = enrich._guidance_for_symbol(self.db, "ACME")
        self.assertIn("18-20%", g.verbatim)


class TestFillIsin(unittest.TestCase):
    """The scan CSV's `isin` is what announcements are matched on. Filled from
    the wrong column, or matched case-sensitively, every per-stock filing factor
    silently comes back empty -- which reads as "no filings" rather than as a
    bug."""

    def setUp(self):
        self._real = enrich.load_constituents
        enrich.load_constituents = lambda *a, **k: pd.DataFrame([
            {"Symbol": "ACME", "ISIN Code": "INE000A01001"},
            {"Symbol": "BETA", "ISIN Code": "INE000B01002"},
        ])
        self.addCleanup(lambda: setattr(enrich, "load_constituents", self._real))

    def test_isin_is_filled_from_the_constituents_csv(self):
        df = pd.DataFrame([{"symbol": "ACME"}, {"symbol": "BETA"}])
        out = enrich._fill_isin(df, Path("scan.csv"))
        self.assertEqual(out["isin"].tolist(),
                         ["INE000A01001", "INE000B01002"])

    def test_a_symbol_outside_the_index_gets_an_empty_isin(self):
        """Reachable via the scan's own --symbols flag, where there is no ISIN to
        be had. Empty is what the scan itself would have written."""
        df = pd.DataFrame([{"symbol": "ACME"}, {"symbol": "NOTLISTED"}])
        out = enrich._fill_isin(df, Path("scan.csv"))
        self.assertEqual(out["isin"].tolist(), ["INE000A01001", ""])

    def test_lookup_is_case_and_whitespace_insensitive(self):
        df = pd.DataFrame([{"symbol": " acme "}])
        out = enrich._fill_isin(df, Path("scan.csv"))
        self.assertEqual(out["isin"].tolist(), ["INE000A01001"])

    def test_the_input_frame_is_not_mutated(self):
        df = pd.DataFrame([{"symbol": "ACME"}])
        enrich._fill_isin(df, Path("scan.csv"))
        self.assertNotIn("isin", df.columns)

    def test_an_unreadable_constituents_csv_is_a_warning_not_a_crash(self):
        """--report needs no ISIN at all, so failing here must not take the whole
        run down with it."""
        def boom(*a, **k):
            raise FileNotFoundError("no constituents CSV")
        enrich.load_constituents = boom
        df = pd.DataFrame([{"symbol": "ACME"}])
        out = enrich._fill_isin(df, Path("scan.csv"))
        self.assertNotIn("isin", out.columns)


class TestNextMonths(unittest.TestCase):
    def test_counts_forward_from_the_month_given(self):
        self.assertEqual(enrich._next_months("2026-03", 3),
                         ["2026-04", "2026-05", "2026-06"])

    def test_crosses_a_year_boundary(self):
        self.assertEqual(enrich._next_months("2026-11", 3),
                         ["2026-12", "2027-01", "2027-02"])

    def test_the_month_given_is_not_included(self):
        """It is the last actual, and labelling a forecast with it would put a
        prediction in the same column as the observation it was made from."""
        self.assertNotIn("2026-03", enrich._next_months("2026-03", 3))


class TestNum(unittest.TestCase):
    def test_a_number_passes_through_as_float(self):
        self.assertEqual(enrich._num(5), 5.0)
        self.assertEqual(enrich._num(5.5), 5.5)

    def test_a_string_from_a_model_is_none_not_a_crash(self):
        """The model returns JSON it wrote itself, so a number can arrive as a
        string, as null, or as prose. None of those should reach arithmetic."""
        for value in ("20%", "", None, "about 500 crore", [], {}):
            self.assertIsNone(enrich._num(value), repr(value))

    def test_a_bool_is_not_a_number(self):
        """`isinstance(True, int)` is True in Python, so a model answering true
        where a value was asked for would otherwise become 1.0."""
        self.assertIsNone(enrich._num(True))


class TestBestOrderForSymbol(_DocstoreCase):
    """The value that feeds `order_significance`, and therefore the ranking.

    This function had no tests, which is how it shipped a report whose top two
    rows were a post-merger net worth figure and a cumulative order book, both
    graded TRANSFORMATIONAL. `_orderbook_series`, forty lines up, gated on the
    trusted tiers the whole time; this one never did.
    """

    def test_a_loose_value_is_never_ranked(self):
        """PIRAMALFIN: Rs 109,542 cr of net worth, read off an NCLT appeal memo,
        ranked first at 215% of market cap."""
        docstore.put_filing(self.db, _filing(
            "s1", rupees=109_542 * significance.CRORE,
            confidence=orderval.CONF_LOOSE))
        self.assertEqual(enrich._best_order_for_symbol(self.db, "ACME"),
                         (None, "", ""))

    def test_a_withheld_or_foreign_reading_is_not_a_value_either(self):
        for conf in (orderval.CONF_WITHHELD, orderval.CONF_FOREIGN,
                     orderval.CONF_NONE):
            with self.subTest(conf=conf):
                docstore.put_filing(self.db, _filing(
                    f"w-{conf}", rupees=500 * significance.CRORE,
                    confidence=conf))
                value, _, _ = enrich._best_order_for_symbol(self.db, "ACME")
                self.assertIsNone(value, f"{conf} must not rank")

    def test_an_anchored_value_is_kept_with_its_tier(self):
        docstore.put_filing(self.db, _filing(
            "s2", rupees=7_300 * significance.CRORE,
            confidence=orderval.CONF_ANCHOR_SCALED, an_date="2026-06-02"))
        value, source, when = enrich._best_order_for_symbol(self.db, "ACME")
        self.assertAlmostEqual(value, 7_300 * significance.CRORE)
        self.assertEqual(source, orderval.CONF_ANCHOR_SCALED)
        self.assertEqual(when, "2026-06-02")

    def test_the_largest_anchored_value_wins_not_the_largest_overall(self):
        """The defect in one assertion: a big loose figure must not beat a
        smaller anchored one. Garbage reads -- net worth, gross debt, cumulative
        order books, tax demands -- are systematically larger than any single
        order, so 'largest' actively selected for them."""
        docstore.put_filing(self.db, _filing(
            "big", rupees=50_000 * significance.CRORE,
            confidence=orderval.CONF_LOOSE))
        docstore.put_filing(self.db, _filing(
            "real", rupees=585 * significance.CRORE,
            confidence=orderval.CONF_ANCHOR_SCALED))
        value, source, _ = enrich._best_order_for_symbol(self.db, "ACME")
        self.assertAlmostEqual(value, 585 * significance.CRORE)
        self.assertEqual(source, orderval.CONF_ANCHOR_SCALED)

    def test_the_largest_of_several_anchored_values_still_wins(self):
        for i, cr in enumerate((400, 1_100, 900)):
            docstore.put_filing(self.db, _filing(
                f"a{i}", rupees=cr * significance.CRORE,
                confidence=orderval.CONF_ANCHOR_SCALED))
        value, _, _ = enrich._best_order_for_symbol(self.db, "ACME")
        self.assertAlmostEqual(value, 1_100 * significance.CRORE)

    def test_the_model_fills_a_gap_the_regex_could_not(self):
        """A loose regex read is a gap, not an answer, so the model supersedes
        it -- and is labelled `llm` so it is never read as a filed figure."""
        docstore.put_filing(self.db, _filing(
            "s3", rupees=88 * significance.CRORE,
            confidence=orderval.CONF_LOOSE))
        docstore.put_extraction(self.db, "s3", llm.KIND_ORDER,
                                {"data": {"order_value_inr":
                                          620 * significance.CRORE}})
        value, source, _ = enrich._best_order_for_symbol(self.db, "ACME")
        self.assertAlmostEqual(value, 620 * significance.CRORE)
        self.assertEqual(source, "llm")

    def test_an_anchored_regex_value_is_not_overridden_by_the_model(self):
        docstore.put_filing(self.db, _filing(
            "s4", rupees=300 * significance.CRORE,
            confidence=orderval.CONF_ANCHOR_BARE))
        docstore.put_extraction(self.db, "s4", llm.KIND_ORDER,
                                {"data": {"order_value_inr":
                                          9_999 * significance.CRORE}})
        value, source, _ = enrich._best_order_for_symbol(self.db, "ACME")
        self.assertAlmostEqual(value, 300 * significance.CRORE)
        self.assertEqual(source, orderval.CONF_ANCHOR_BARE)

    def test_only_order_filings_count(self):
        docstore.put_filing(self.db, _filing(
            "s5", kind=enrich.KIND_GUIDANCE, rupees=900 * significance.CRORE,
            confidence=orderval.CONF_ANCHOR_SCALED))
        self.assertEqual(enrich._best_order_for_symbol(self.db, "ACME"),
                         (None, "", ""))


class TestCapacityPlan(unittest.TestCase):
    """`order_capacity_plan` -- did a capacity filing precede the order?

    The label reports what was FILED, not what was planned. A company announces
    capacity when it chooses to, so `UNPLANNED` is an observation about the
    filings, and the column exists to point a human at the PDFs rather than to
    conclude anything.
    """

    def test_a_capacity_filing_before_the_order_is_planned(self):
        label, when = enrich._capacity_plan(
            ["2026-05-01", "2026-01-10"], "2026-06-17")
        self.assertEqual(label, "PLANNED")
        self.assertEqual(when, "2026-05-01",
                         "the nearest preceding filing, not the oldest")

    def test_capacity_only_after_the_order_says_so(self):
        """The most interesting of the three: capacity announced after a win is
        the company saying the order outgrew its plant."""
        label, when = enrich._capacity_plan(["2026-08-01"], "2026-06-17")
        self.assertEqual(label, "CAPACITY_AFTER")
        self.assertEqual(when, "2026-08-01")

    def test_no_capacity_filing_at_all_is_unplanned(self):
        self.assertEqual(enrich._capacity_plan([], "2026-06-17"),
                         ("UNPLANNED", ""))

    def test_no_order_means_no_verdict(self):
        """An empty cell says "no order to judge" better than a label would."""
        self.assertEqual(enrich._capacity_plan(["2026-08-01"], ""), ("", ""))

    def test_a_filing_on_the_order_date_counts_as_preceding(self):
        label, _ = enrich._capacity_plan(["2026-06-17"], "2026-06-17")
        self.assertEqual(label, "PLANNED")


if __name__ == "__main__":
    unittest.main()
