import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_PY = (ROOT / "ui/app/api.py").read_text(encoding="utf-8")
QUERIES_PY = (ROOT / "ui/app/queries.py").read_text(encoding="utf-8")
APP_JS = (ROOT / "ui/app/static/app.js").read_text(encoding="utf-8")


def function_section(js, name):
    start = js.find(f"async function {name}(")
    if start == -1:
        raise AssertionError(f"{name} missing")
    ends = [i for i in (js.find("\nasync function ", start + 1), js.find("\nfunction ", start + 1)) if i != -1]
    end = min(ends) if ends else -1
    return js[start:] if end == -1 else js[start:end]


class RelativeStrengthUIContractTests(unittest.TestCase):
    def test_query_constant_exists(self):
        self.assertIn("RELATIVE_STRENGTH_LATEST = ", QUERIES_PY,
            "queries.py should define RELATIVE_STRENGTH_LATEST")
        self.assertIn("FROM relative_strength", QUERIES_PY,
            "RELATIVE_STRENGTH_LATEST should read the relative_strength table")

    def test_get_stock_returns_relative_strength_key(self):
        self.assertIn('"relative_strength"', API_PY,
            "api.py get_stock should return a relative_strength key")
        self.assertIn("queries.RELATIVE_STRENGTH_LATEST", API_PY,
            "api.py should run queries.RELATIVE_STRENGTH_LATEST")

    def test_render_stock_references_relative_strength(self):
        self.assertIn("relative_strength", function_section(APP_JS, "renderStock"),
            "renderStock should read data.relative_strength")

    def test_results_query_joins_latest_relative_strength(self):
        self.assertIn("LEFT JOIN LATERAL", API_PY, "results query should join relative strength per symbol")
        self.assertIn("FROM relative_strength r", API_PY)
        self.assertIn("rs_gap_pct", API_PY)
        self.assertIn("rs_ratio_pct", API_PY)

    def test_results_table_has_rs_column(self):
        body = function_section(APP_JS, "renderResults")
        columns = APP_JS[APP_JS.find("const RESULT_COLUMNS = ["):APP_JS.find("];", APP_JS.find("const RESULT_COLUMNS = ["))]
        self.assertIn('label: "RS %"', columns, "All results table should have an RS % column")
        self.assertIn("rs_ratio_pct", columns, "the RS % column should sort on rs_ratio_pct")
        self.assertIn("rs_ratio_pct", body, "results rows should render rs_ratio_pct")

    def test_stock_page_3m_return_uses_relative_strength_basis(self):
        body = function_section(APP_JS, "renderStock")
        self.assertIn("3M return", body, "the headline return tile should be the 3-month price return")
        self.assertIn("stock_return_3m", body,
            "the 3M return tile should read stock_return_3m from the relative_strength row")
        self.assertNotIn("1Y return", body,
            "one_year_return_pct is quarterly YoY growth, so it must not be labelled as a 1-year return")
        self.assertIn("YoY growth (latest qtr)", body,
            "one_year_return_pct should be labelled as the latest-quarter YoY growth")


if __name__ == "__main__":
    unittest.main()
