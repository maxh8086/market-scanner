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

if __name__ == "__main__":
    unittest.main()
