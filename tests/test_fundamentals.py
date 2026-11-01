"""Tests for scanner.fundamentals.

This module's job is to turn a third party's parse of someone else's HTML into
numbers, and that is a quiet kind of failure: a return shape that changed does
not raise, it yields None for every ratio and an empty revenue series, and the
scan reports "0/298 have a market cap" as though the market had no market caps.
That is exactly what happened -- the fetch was written against a guessed API and
every symbol failed -- so the parsing is pinned here against fixture HTML in the
shape screener actually serves.

No network: `parse_page` and the row extractors are pure, and the cache path is
exercised against a temporary docstore.
"""

import tempfile
import unittest
from pathlib import Path

from scanner import docstore
from scanner import fundamentals as fu


def _page(ratios=None, quarters=None, annual=None, promoters=None, cons=None,
          balance=None):
    """Minimal company page in screener's structure.

    Deliberately minimal: what is asserted is that the right cell is read out of
    the right table, and a full saved page would hide which part of the shape a
    test depends on.
    """
    # Values as screener renders them inside `span.number`: the rupee sign and
    # the "Cr." unit sit in sibling spans, so the number arrives bare.
    ratios = ratios if ratios is not None else {
        "Market Cap": "4,28,307", "Current Price": "4,824",
        "Stock P/E": "73.4", "ROCE": "20.5 %", "ROE": "37.7 %"}
    lis = "".join(f'<li><span class="name">{k}</span>'
                  f'<span class="number">{v}</span></li>'
                  for k, v in ratios.items())
    out = [f'<html><body><h1>Acme Ltd</h1>'
           f'<div id="top-ratios"><ul>{lis}</ul></div>']

    def table(section_id, years, rows):
        head = "".join(f"<th>{y}</th>" for y in years)
        body = ""
        for label, values in rows:
            cells = "".join(f"<td>{v}</td>" for v in values)
            body += f"<tr><td>{label}</td>{cells}</tr>"
        return (f'<section id="{section_id}"><table>'
                f'<thead><tr><th></th>{head}</tr></thead>'
                f'<tbody>{body}</tbody></table></section>')

    if quarters is not None:
        out.append(table("quarters", quarters[0], quarters[1]))
    if annual is not None:
        out.append(table("profit-loss", annual[0], annual[1]))
    if balance is not None:
        out.append(table("balance-sheet", balance[0], balance[1]))
    if promoters is not None:
        rows = "".join(f"<tr><td>{c}</td>"
                       + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"
                       for c, vals in promoters)
        out.append(f'<section id="shareholding"><table>'
                   f'<thead><tr><th></th><th>Jun 2026</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></section>')
    if cons is not None:
        items = "".join(f"<li>{c}</li>" for c in cons)
        out.append(f'<div id="analysis"><div class="cons"><ul>{items}'
                   f'</ul></div></div>')
    out.append("</body></html>")
    return "".join(out)


class TestSeriesFromTable(unittest.TestCase):
    def test_the_sales_row_is_read_oldest_first(self):
        table = {"years": ["Jun 2025", "Sep 2025", "Dec 2025"],
                 "rows": [{"label": "Sales", "values": ["100", "110", "120"]},
                          {"label": "Expenses", "values": ["90", "95", "99"]}]}
        self.assertEqual(fu._series_from_table(table), [100.0, 110.0, 120.0])

    def test_a_trailing_ttm_column_is_stripped(self):
        """The defect this guards is a 4x spike at the end of a quarterly
        series: a twelve-month total where the model expects three months, which
        reads as explosive growth and would be forecast forward."""
        table = {"years": ["Mar 2025", "Mar 2026", "TTM"],
                 "rows": [{"label": "Sales", "values": ["100", "120", "480"]}]}
        self.assertEqual(fu._series_from_table(table), [100.0, 120.0])

    def test_the_expandable_row_marker_is_tolerated(self):
        table = {"years": ["Mar 2026"],
                 "rows": [{"label": "Sales+", "values": ["120"]}]}
        self.assertEqual(fu._series_from_table(table), [120.0])

    def test_sales_is_preferred_over_total_income(self):
        """Total income includes other income, so it is a different quantity --
        usable as a last resort, never in preference to revenue."""
        table = {"years": ["Mar 2026"],
                 "rows": [{"label": "Total Income", "values": ["150"]},
                          {"label": "Sales", "values": ["120"]}]}
        self.assertEqual(fu._series_from_table(table), [120.0])

    def test_a_blank_cell_holds_its_position(self):
        """Dropping it would shift every later value, and a quarterly series is
        only seasonal if index k is really k quarters back."""
        table = {"years": ["a", "b", "c"],
                 "rows": [{"label": "Sales", "values": ["100", "", "120"]}]}
        self.assertEqual(fu._series_from_table(table), [100.0, None, 120.0])

    def test_a_missing_row_or_table_is_empty_not_an_exception(self):
        self.assertEqual(fu._series_from_table(None), [])
        self.assertEqual(fu._series_from_table({}), [])
        self.assertEqual(fu._series_from_table({"years": [], "rows": []}), [])
        self.assertEqual(
            fu._series_from_table({"years": ["a"],
                                   "rows": [{"label": "Expenses",
                                             "values": ["1"]}]}), [])


class TestPromoterHolding(unittest.TestCase):
    def test_the_latest_column_wins(self):
        got = fu._promoter_holding(
            {"quarters": ["Mar 2026", "Jun 2026"],
             "rows": [{"category": "Promoters", "values": ["52.0", "52.9"]}]})
        self.assertAlmostEqual(got, 52.9)

    def test_the_expandable_marker_and_case_are_tolerated(self):
        got = fu._promoter_holding(
            {"rows": [{"category": "Promoters+", "values": ["45.1"]}]})
        self.assertAlmostEqual(got, 45.1)

    def test_no_promoter_row_is_none_not_zero(self):
        """A company with no identified promoter is normal. Zero would read as
        promoters having sold out."""
        self.assertIsNone(fu._promoter_holding(
            {"rows": [{"category": "FIIs", "values": ["20.0"]}]}))
        self.assertIsNone(fu._promoter_holding(None))


class TestParsePage(unittest.TestCase):
    def test_the_ratios_come_out_of_top_ratios(self):
        f = fu.parse_page("ACME", _page())
        self.assertEqual(f.error, "")
        self.assertTrue(f.ok)
        self.assertAlmostEqual(f.mcap_cr, 428307.0)
        self.assertAlmostEqual(f.pe, 73.4)
        self.assertAlmostEqual(f.roce, 20.5)
        self.assertAlmostEqual(f.roe, 37.7)

    def test_a_currency_decorated_value_still_parses(self):
        """Screener renders the unit outside the number span today. If a layout
        change moves it inside, the cap must still read -- the alternative is
        every mcap silently None and every significance score unscored."""
        f = fu.parse_page("ACME", _page(
            ratios={"Market Cap": "₹ 4,28,307 Cr."}))
        self.assertAlmostEqual(f.mcap_cr, 428307.0)

    def test_a_page_with_no_market_cap_is_an_error(self):
        """Not silently ok: market cap is the denominator every significance
        score divides by, so a row with none is unusable rather than partial."""
        f = fu.parse_page("ACME", _page(ratios={"Stock P/E": "20"}))
        self.assertFalse(f.ok)
        self.assertIn("market cap", f.error)
        self.assertAlmostEqual(f.pe, 20.0, "the rest is still parsed")

    def test_both_revenue_series_are_read(self):
        f = fu.parse_page("ACME", _page(
            quarters=(["Jun 2025", "Sep 2025"],
                      [("Sales", ["100", "110"]), ("Expenses", ["9", "9"])]),
            annual=(["Mar 2025", "Mar 2026", "TTM"],
                    [("Sales", ["400", "450", "460"])])))
        self.assertEqual(f.quarterly_sales, [100.0, 110.0])
        self.assertEqual(f.annual_sales, [400.0, 450.0],
                         "the annual TTM column is not a fiscal year")

    def test_pledge_comes_from_the_cons_list_not_the_shareholding_table(self):
        """screener's shareholding table carries no pledge row at all, even for
        a company with most of its promoter stake pledged. The page states it in
        prose instead, which is the only place it can be read from."""
        f = fu.parse_page("ACME", _page(
            promoters=[("Promoters", ["52.9"])],
            cons=["Promoters have pledged 89.4% of their holding.",
                  "Company has a low return on equity."]))
        self.assertAlmostEqual(f.pledged_pct, 89.4)
        self.assertAlmostEqual(f.promoter_holding_pct, 52.9)

    def test_no_pledge_mentioned_is_none_not_zero(self):
        f = fu.parse_page("ACME", _page(cons=["Company has a low ROE."]))
        self.assertIsNone(f.pledged_pct)

    def test_debt_to_equity_is_derived_from_the_balance_sheet(self):
        f = fu.parse_page("ACME", _page(balance=(
            ["Mar 2026"], [("Equity Capital", ["100"]),
                           ("Reserves", ["300"]),
                           ("Borrowings", ["200"])])))
        self.assertAlmostEqual(f.debt_to_equity, 0.5)

    def test_junk_html_is_an_error_not_an_exception(self):
        """A 300-symbol run must not stop on one bad page."""
        f = fu.parse_page("ACME", "<html><body>nope</body></html>")
        self.assertFalse(f.ok)
        self.assertIn("market cap", f.error)


class TestCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = docstore.open_db(Path(self._tmp.name) / "docs.json")
        # LIFO: the db closes before the directory is removed, or Windows
        # refuses to unlink a file the store still holds open.
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.db.close)

    def test_a_fresh_doc_is_returned_without_a_fetch(self):
        docstore.put_fundamentals(self.db, "ACME", {"mcap_cr": 1000.0,
                                                    "pe": 20.0})
        got = fu.cached(self.db, "ACME")
        self.assertIsNotNone(got)
        self.assertEqual(got.symbol, "ACME")
        self.assertAlmostEqual(got.mcap_cr, 1000.0)

    def test_a_stale_doc_is_not_returned(self):
        docstore.put_fundamentals(self.db, "ACME", {"mcap_cr": 1000.0})
        self.assertIsNone(fu.cached(self.db, "ACME", max_age_days=-1.0))

    def test_an_absent_symbol_is_none(self):
        self.assertIsNone(fu.cached(self.db, "NOPE"))

    def test_a_cached_failure_is_not_a_cache_hit(self):
        """Caching a failure turns one transient timeout into a day of "no
        market cap" for every symbol it touched -- and did, when the fetch was
        broken and 298 error documents were written and then believed."""
        docstore.put_fundamentals(self.db, "ACME", {"error": "fetch failed"})
        self.assertIsNone(fu.cached(self.db, "ACME"))

    def test_a_failure_is_not_written_to_the_cache(self):
        fu._store(self.db, "ACME", fu.Fundamentals(symbol="ACME",
                                                   error="fetch failed"))
        self.assertIsNone(docstore.get_fundamentals(self.db, "ACME"))
        fu._store(self.db, "ACME", fu.Fundamentals(symbol="ACME",
                                                   mcap_cr=10.0))
        self.assertIsNotNone(docstore.get_fundamentals(self.db, "ACME"))

    def test_fetch_many_over_a_warm_cache_touches_no_network(self):
        """The assertion is the absence of a fetch: `_fetch_batch` is replaced
        with something that fails loudly, so a cache miss cannot pass quietly.
        """
        for symbol in ("A", "B"):
            docstore.put_fundamentals(self.db, symbol, {"mcap_cr": 1.0})

        def boom(*a, **k):
            raise AssertionError("a cached symbol must not be fetched")

        original = fu._fetch_batch
        fu._fetch_batch = boom
        try:
            got = fu.fetch_many(self.db, ["A", "B"])
        finally:
            fu._fetch_batch = original
        self.assertEqual(set(got), {"A", "B"})


class TestIndustryPE(unittest.TestCase):
    def _f(self, symbol, pe):
        return fu.Fundamentals(symbol=symbol, mcap_cr=100.0, pe=pe)

    def test_median_over_the_cohort(self):
        got = fu.industry_pe(
            {"A": self._f("A", 10.0), "B": self._f("B", 20.0),
             "C": self._f("C", 30.0)},
            {"A": "Auto", "B": "Auto", "C": "Auto"})
        self.assertAlmostEqual(got["Auto"], 20.0)

    def test_loss_makers_and_absurd_multiples_are_excluded(self):
        """A company with no earnings has no meaningful P/E, and one 500x
        outlier would define the median of a small cohort."""
        got = fu.industry_pe(
            {"A": self._f("A", 10.0), "B": self._f("B", 20.0),
             "C": self._f("C", None), "D": self._f("D", 500.0),
             "E": self._f("E", -5.0)},
            {k: "Auto" for k in "ABCDE"})
        self.assertAlmostEqual(got["Auto"], 15.0)

    def test_pe_vs_industry_sign(self):
        self.assertAlmostEqual(fu.pe_vs_industry(15.0, 20.0), -25.0)
        self.assertAlmostEqual(fu.pe_vs_industry(25.0, 20.0), 25.0)
        self.assertIsNone(fu.pe_vs_industry(None, 20.0))
        self.assertIsNone(fu.pe_vs_industry(15.0, 0.0))


if __name__ == "__main__":
    unittest.main()
