import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "ui/app/static/app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "ui/app/static/index.html").read_text(encoding="utf-8")

def stocks_section(js):
    start = js.find("async function renderStocks")
    if start == -1:
        raise AssertionError("renderStocks missing")
    end = js.find("\nasync function ", start + 1)
    return js[start:] if end == -1 else js[start:end]

def function_section(js, name):
    start = js.find(f"async function {name}(")
    if start == -1:
        raise AssertionError(f"{name} missing")
    ends = [i for i in (js.find("\nasync function ", start + 1), js.find("\nfunction ", start + 1)) if i != -1]
    end = min(ends) if ends else -1
    return js[start:] if end == -1 else js[start:end]

class UIStocksPageContractTests(unittest.TestCase):
    def test_hash_route_exists(self):
        self.assertIn("#/stocks", APP_JS, "app.js should route the #/stocks hash")

    def test_route_dispatches_stocks(self):
        self.assertIn("renderStocks(", APP_JS, "router should dispatch to renderStocks(")

    def test_fetches_stocks_api(self):
        self.assertIn("/api/stocks", stocks_section(APP_JS), "renderStocks should call /api/stocks")

    def test_links_to_stock_detail(self):
        self.assertIn("#/stock/${", stocks_section(APP_JS), "renderStocks should link rows to #/stock/${symbol}")

    def test_nav_entry_present(self):
        self.assertIn('data-nav="stocks"', INDEX_HTML,
            "index.html nav should contain a data-nav=\"stocks\" entry")

    def test_no_unknown_placeholder(self):
        self.assertNotIn("UNKNOWN", stocks_section(APP_JS), "missing values must render as blank cells, not UNKNOWN")

    def test_stock_detail_fetches_detail_endpoint(self):
        self.assertIn("/api/stocks/", function_section(APP_JS, "renderStock"),
            "renderStock should call the /api/stocks/ detail endpoint")

    def test_stock_detail_has_no_invented_sample_labels(self):
        body = "\n".join(line for line in function_section(APP_JS, "renderStock").splitlines() if "TBD" not in line)
        for label in ["EMA", "Rel", "relative strength", "Governance", "Holdings", "Sizing", "Review"]:
            with self.subTest(label=label):
                self.assertNotIn(label, body,
                    f"renderStock should not render invented sample label {label!r}")

    def test_stock_detail_uses_tbd_for_missing_fields(self):
        self.assertIn("TBD", function_section(APP_JS, "renderStock"),
            "renderStock should render fields the API lacks as TBD")

    def test_stocks_list_has_no_invented_column_headers(self):
        section = stocks_section(APP_JS)
        for label in ["EMA", "Governance"]:
            with self.subTest(label=label):
                self.assertNotIn(label, section,
                    f"renderStocks should not have invented column header {label!r}")

    def test_stocks_list_rows_link_to_detail(self):
        self.assertIn("#/stock/${", stocks_section(APP_JS),
            "renderStocks rows should link to #/stock/${symbol}")

if __name__ == "__main__":
    unittest.main()
