"""Tests for scanner.screener: the parsers and the paced fetcher, with no network.

The fetcher is driven through httpx.MockTransport, so retry, 404 and the
consolidated -> standalone fall-back are exercised against real httpx behaviour.
"""
import asyncio
import unittest
from unittest import mock

import httpx

from scanner import screener as sc
from tests.test_fundamentals import _page

PAGE = _page(
    annual=(["Mar 2023", "Mar 2024", "TTM"],
            [("Sales +", ["100", "120", "130"]), ("Raw PDF", [""] * 3)]),
    balance=(["Mar 2024"], [("Equity Capital", ["10"]), ("Reserves", ["90"]),
                            ("Borrowings +", ["50"])]),
    cons=["Promoters have pledged 12.5% of their holding."])


def _client_with(handler):
    c = sc.Client()
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                follow_redirects=True, base_url=sc.BASE_URL)
    return c


def _run(coro):
    return asyncio.run(coro)


class ParserTests(unittest.TestCase):
    def test_overview_ratios_and_name(self):
        o = sc.parse_overview(PAGE)
        self.assertEqual(o["name"], "Acme Ltd")
        self.assertEqual(o["key_ratios"]["Market Cap"], "4,28,307")
        self.assertEqual(o["key_ratios"]["ROCE"], "20.5 %")

    def test_profit_loss_drops_raw_pdf_and_label_suffix(self):
        t = sc.parse_profit_loss(PAGE)
        self.assertEqual([r["label"] for r in t["rows"]], ["Sales"])
        self.assertEqual(t["years"], ["Mar 2023", "Mar 2024", "TTM"])

    def test_split_ttm_strips_trailing_column(self):
        years, rows, ttm = sc.split_ttm(sc.parse_profit_loss(PAGE))
        self.assertEqual(years, ["Mar 2023", "Mar 2024"])
        self.assertEqual(rows[0]["values"], ["100", "120"])
        self.assertEqual(ttm, {"Sales": "130"})

    def test_split_ttm_without_ttm_is_untouched(self):
        t = {"years": ["Mar 2023"], "rows": [{"label": "Sales", "values": ["1"]}]}
        self.assertEqual(sc.split_ttm(t), (["Mar 2023"], t["rows"], None))

    def test_debt_to_equity(self):
        self.assertEqual(sc.debt_to_equity(PAGE), 0.5)

    def test_debt_to_equity_none_when_equity_not_positive(self):
        page = _page(balance=(["Mar 2024"], [("Equity Capital", ["10"]),
                                             ("Reserves", ["-20"]),
                                             ("Borrowings", ["5"])]))
        self.assertIsNone(sc.debt_to_equity(page))

    def test_debt_to_equity_none_without_balance_sheet(self):
        self.assertIsNone(sc.debt_to_equity(_page()))

    def test_pledged_pct(self):
        self.assertEqual(sc.pledged_pct(PAGE), 12.5)
        self.assertIsNone(sc.pledged_pct(_page()))

    def test_normalize_symbol(self):
        for raw in ("nse:msumi ", "MSUMI.NS", "/company/MSUMI/", "msumi"):
            self.assertEqual(sc.normalize_symbol(raw), "MSUMI")

    def test_page_has_data(self):
        self.assertTrue(sc.page_has_data(PAGE))
        blank = _page(ratios={"Market Cap": ""})
        self.assertFalse(sc.page_has_data(blank))
        self.assertFalse(sc.page_has_data("<html></html>"))


class FetchTests(unittest.TestCase):
    def setUp(self):
        # Retries back off through _cool_down; a zero interval keeps the tests fast.
        p = mock.patch.object(sc, "_MIN_INTERVAL", 0.0)
        p.start()
        self.addCleanup(p.stop)

    def test_consolidated_page_used_when_it_has_data(self):
        seen = []

        def handler(req):
            seen.append(req.url.path)
            return httpx.Response(200, text=PAGE)
        page = _run(sc.fetch_page(_client_with(handler), "ACME"))
        self.assertEqual(page.financial_type, "consolidated")
        self.assertEqual(seen, ["/company/ACME/consolidated/"])

    def test_blank_consolidated_falls_back_to_standalone(self):
        def handler(req):
            if req.url.path.endswith("/consolidated/"):
                return httpx.Response(200, text=_page(ratios={"Market Cap": ""}))
            return httpx.Response(200, text=PAGE)
        page = _run(sc.fetch_page(_client_with(handler), "ACME"))
        self.assertEqual(page.financial_type, "standalone")

    def test_unknown_symbol_is_reported_not_found(self):
        client = _client_with(lambda req: httpx.Response(404))
        with self.assertRaisesRegex(sc.ScreenerError, "not found"):
            _run(sc.fetch_page(client, "NOSUCH"))

    def test_invalid_symbol_is_rejected_before_any_request(self):
        def handler(req):
            raise AssertionError("no request expected")
        with self.assertRaises(sc.ScreenerError):
            _run(sc.fetch_page(_client_with(handler), "a b/../x"))

    def test_429_is_retried_and_honours_retry_after(self):
        calls = {"n": 0}

        def handler(req):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, text=PAGE)
        page = _run(sc.fetch_page(_client_with(handler), "ACME"))
        self.assertEqual(calls["n"], 2)
        self.assertEqual(page.symbol, "ACME")

    def test_network_error_is_retried(self):
        calls = {"n": 0}

        def handler(req):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("boom")
            return httpx.Response(200, text=PAGE)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            _run(sc.fetch_page(_client_with(handler), "ACME"))
        self.assertEqual(calls["n"], 2)

    def test_server_error_raises_with_status(self):
        client = _client_with(lambda req: httpx.Response(500))
        with self.assertRaisesRegex(sc.ScreenerError, "HTTP 500"):
            _run(sc.fetch_page(client, "ACME"))

    def test_login_redirect_is_an_error(self):
        def handler(req):
            if req.url.path == "/login/":
                return httpx.Response(200, text="login")
            return httpx.Response(302, headers={"Location": "/login/?next=/x"})
        with self.assertRaisesRegex(sc.ScreenerError, "login"):
            _run(sc.fetch_page(_client_with(handler), "ACME"))


if __name__ == "__main__":
    unittest.main()
