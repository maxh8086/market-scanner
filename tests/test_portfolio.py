"""Unit tests for scanner.portfolio — holdings overlay on scan results."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from scanner.portfolio import load_holdings, overlay, _normalize_holdings


class TestLoadHoldingsFromFile(unittest.TestCase):
    """Test file-based holdings loading."""

    def test_load_json(self):
        """Load holdings from JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            holdings = [
                {
                    "tradingsymbol": "INFY",
                    "exchange": "NSE",
                    "isin": "INE009A01021",
                    "quantity": 10,
                    "t1_quantity": 0,
                    "average_price": 1500.0,
                    "last_price": 1600.0,
                    "pnl": 1000.0,
                    "day_change_percentage": 5.0,
                }
            ]
            path = Path(tmpdir) / "holdings.json"
            path.write_text(json.dumps(holdings))

            df = load_holdings(file_path=str(path))
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["tradingsymbol"], "INFY")

    def test_load_csv(self):
        """Load holdings from CSV file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "holdings.csv"
            path.write_text(
                "tradingsymbol,exchange,isin,quantity,average_price,last_price\n"
                "INFY,NSE,INE009A01021,10,1500.0,1600.0\n"
            )

            df = load_holdings(file_path=str(path))
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["tradingsymbol"], "INFY")

    def test_load_missing_file_returns_empty(self):
        """Missing file returns empty DataFrame."""
        df = load_holdings(file_path="/nonexistent/path.json")
        self.assertTrue(df.empty)

    @unittest.skip("Skipping os.chdir test due to Windows file locking")
    def test_load_defaults_to_data_holdings(self):
        """load_holdings looks for data/holdings.json and data/holdings.csv by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            data_dir = Path("data")
            data_dir.mkdir()

            path = data_dir / "holdings.json"
            path.write_text(json.dumps([
                {"tradingsymbol": "TCS", "quantity": 5, "average_price": 3000.0, "last_price": 3100.0}
            ]))

            df = load_holdings()
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["tradingsymbol"], "TCS")


class TestLoadHoldingsLivePath(unittest.TestCase):
    """Test live Kite API path."""

    @patch.dict(os.environ, {
        "KITE_API_KEY": "test_key",
        "KITE_ACCESS_TOKEN": "test_token"
    })
    @patch("scanner.portfolio.KiteConnect")
    def test_load_from_kite_api(self, mock_kite_class):
        """Load holdings from Kite API if credentials are set."""
        mock_kite = MagicMock()
        mock_kite_class.return_value = mock_kite
        mock_kite.holdings.return_value = [
            {
                "tradingsymbol": "INFY",
                "exchange": "NSE",
                "isin": "INE009A01021",
                "quantity": 10,
                "average_price": 1500.0,
                "last_price": 1600.0,
            }
        ]

        df = load_holdings(verbose=False)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["tradingsymbol"], "INFY")
        mock_kite.set_access_token.assert_called_once_with("test_token")

    @unittest.skip("Skipping os.chdir test due to Windows file locking")
    @patch.dict(os.environ, {
        "KITE_API_KEY": "test_key",
        "KITE_ACCESS_TOKEN": "test_token"
    }, clear=False)
    @patch("scanner.portfolio.KiteConnect")
    def test_kite_api_fallback_to_file(self, mock_kite_class):
        """Kite API auth error falls back to file path."""
        mock_kite = MagicMock()
        mock_kite_class.return_value = mock_kite
        mock_kite.holdings.side_effect = Exception("Token expired")

        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            data_dir = Path("data")
            data_dir.mkdir()

            path = data_dir / "holdings.json"
            path.write_text(json.dumps([
                {"tradingsymbol": "TCS", "quantity": 5, "average_price": 3000.0, "last_price": 3100.0}
            ]))

            df = load_holdings(verbose=False)
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["tradingsymbol"], "TCS")


class TestNormalizeHoldings(unittest.TestCase):
    """Test holdings normalization."""

    def test_normalize_tradingsymbol_to_symbol(self):
        """Rename tradingsymbol to symbol."""
        df = pd.DataFrame({"tradingsymbol": ["INFY"], "quantity": [10]})
        normalized = _normalize_holdings(df)
        self.assertIn("symbol", normalized.columns)
        self.assertEqual(normalized.iloc[0]["symbol"], "INFY")

    def test_normalize_isin_missing_creates_empty(self):
        """Missing ISIN column is created as empty."""
        df = pd.DataFrame({"symbol": ["INFY"], "quantity": [10]})
        normalized = _normalize_holdings(df)
        self.assertIn("isin", normalized.columns)
        self.assertEqual(normalized.iloc[0]["isin"], "")

    def test_normalize_lowercase_columns(self):
        """Column names are normalized to lowercase."""
        df = pd.DataFrame({"Symbol": ["INFY"], "Quantity": [10], "Average_Price": [1500.0]})
        normalized = _normalize_holdings(df)
        self.assertIn("symbol", normalized.columns)
        self.assertIn("quantity", normalized.columns)


class TestOverlay(unittest.TestCase):
    """Test overlay of holdings with scan data."""

    def setUp(self):
        """Set up test DataFrames."""
        self.holdings = pd.DataFrame({
            "symbol": ["INFY", "TCS", "OUT_OF_SCAN"],
            "isin": ["INE009A01021", "INE467B01029", ""],
            "quantity": [10, 5, 3],
            "average_price": [1500.0, 3000.0, 500.0],
            "last_price": [1600.0, 3100.0, 450.0],
        })

        self.scan = pd.DataFrame({
            "symbol": ["INFY", "TCS"],
            "isin": ["INE009A01021", "INE467B01029"],
            "bucket": ["0-5%", "5-15%"],
            "distance_pct": [2.5, 10.0],
            "ath_date": ["2024-01-15", "2024-01-10"],
            "above_ema50": [True, True],
            "above_sma200": [True, False],
        })

    def test_overlay_basic(self):
        """Basic overlay joins holdings with scan data."""
        portfolio, summary = overlay(self.holdings, self.scan)

        self.assertEqual(len(portfolio), 3)

        # In-scan holdings
        infy = portfolio[portfolio["symbol"] == "INFY"].iloc[0]
        self.assertEqual(infy["in_scan"], "YES")
        self.assertEqual(infy["bucket"], "0-5%")
        self.assertEqual(infy["quantity"], 10)
        self.assertEqual(infy["invested"], 15000.0)
        self.assertEqual(infy["current_value"], 16000.0)
        self.assertEqual(infy["pnl"], 1000.0)

        # Out of scan holding
        out = portfolio[portfolio["symbol"] == "OUT_OF_SCAN"].iloc[0]
        self.assertEqual(out["in_scan"], "NOT_IN_SCAN")
        self.assertTrue(pd.isna(out["bucket"]))

    def test_overlay_isin_join(self):
        """Overlay joins on ISIN when available."""
        # Create scan with different symbol names but same ISIN
        scan_renamed = self.scan.copy()
        scan_renamed.loc[scan_renamed["symbol"] == "INFY", "symbol"] = "INFOSYS"

        portfolio, _ = overlay(self.holdings, scan_renamed)

        # Should still match on ISIN
        infy = portfolio[portfolio["symbol"] == "INFY"].iloc[0]
        self.assertEqual(infy["in_scan"], "YES")
        self.assertEqual(infy["bucket"], "0-5%")

    def test_overlay_symbol_fallback(self):
        """Overlay falls back to symbol when ISIN is missing."""
        scan_no_isin = self.scan.copy()
        scan_no_isin["isin"] = ""

        portfolio, _ = overlay(self.holdings, scan_no_isin)

        # Should still match on symbol
        infy = portfolio[portfolio["symbol"] == "INFY"].iloc[0]
        self.assertEqual(infy["in_scan"], "YES")
        self.assertEqual(infy["bucket"], "0-5%")

    def test_overlay_with_enriched(self):
        """Overlay includes enriched columns when provided."""
        enriched = self.scan.copy()
        enriched["order_significance"] = ["HIGH", "MEDIUM"]
        enriched["revenue_outlook"] = ["GROWTH", "STABLE"]

        portfolio, _ = overlay(self.holdings, self.scan, enriched)

        infy = portfolio[portfolio["symbol"] == "INFY"].iloc[0]
        self.assertEqual(infy["order_significance"], "HIGH")
        self.assertEqual(infy["revenue_outlook"], "GROWTH")

    def test_overlay_computes_pnl(self):
        """Overlay computes P&L and P&L %."""
        portfolio, _ = overlay(self.holdings, self.scan)

        infy = portfolio[portfolio["symbol"] == "INFY"].iloc[0]
        self.assertEqual(infy["invested"], 15000.0)
        self.assertEqual(infy["current_value"], 16000.0)
        self.assertEqual(infy["pnl"], 1000.0)
        self.assertAlmostEqual(infy["pnl_pct"], 6.67, places=1)

    def test_overlay_zero_quantity_holdings(self):
        """Zero-quantity holdings are retained."""
        holdings_with_zero = self.holdings.copy()
        holdings_with_zero.loc[holdings_with_zero["symbol"] == "INFY", "quantity"] = 0

        portfolio, _ = overlay(holdings_with_zero, self.scan)

        infy = portfolio[portfolio["symbol"] == "INFY"].iloc[0]
        self.assertEqual(infy["quantity"], 0)
        self.assertEqual(infy["invested"], 0)
        self.assertEqual(infy["current_value"], 0)

    def test_overlay_empty_holdings(self):
        """Empty holdings DataFrame returns empty portfolio."""
        empty_holdings = pd.DataFrame()
        portfolio, summary = overlay(empty_holdings, self.scan)

        self.assertTrue(portfolio.empty)
        self.assertEqual(summary["total_holdings"], 0)


class TestSummaryComputation(unittest.TestCase):
    """Test portfolio summary statistics."""

    def setUp(self):
        """Set up test DataFrames."""
        self.holdings = pd.DataFrame({
            "symbol": ["INFY", "TCS"],
            "quantity": [10, 5],
            "average_price": [1500.0, 3000.0],
            "last_price": [1600.0, 3100.0],
            "isin": ["INE009A01021", "INE467B01029"],
        })

        self.scan = pd.DataFrame({
            "symbol": ["INFY", "TCS"],
            "isin": ["INE009A01021", "INE467B01029"],
            "bucket": ["0-5%", "5-15%"],
            "distance_pct": [2.5, 10.0],
            "ath_date": ["2024-01-15", "2024-01-10"],
            "above_ema50": [True, True],
            "above_sma200": [True, False],
        })

    def test_summary_totals(self):
        """Summary computes correct totals."""
        _, summary = overlay(self.holdings, self.scan)

        self.assertEqual(summary["total_holdings"], 2)
        self.assertEqual(summary["total_holdings_in_scan"], 2)
        self.assertEqual(summary["total_invested"], 30000.0)  # 15000 + 15000
        self.assertEqual(summary["total_value"], 31500.0)  # 16000 + 15500
        self.assertEqual(summary["total_pnl"], 1500.0)

    def test_summary_by_bucket(self):
        """Summary groups holdings by bucket."""
        _, summary = overlay(self.holdings, self.scan)

        self.assertIn("0-5%", summary["holdings_by_bucket"])
        self.assertIn("5-15%", summary["holdings_by_bucket"])
        self.assertEqual(summary["holdings_by_bucket"]["0-5%"], 1)
        self.assertEqual(summary["holdings_by_bucket"]["5-15%"], 1)

    def test_summary_attention_flags_momentum(self):
        """Momentum flag fires for 0-5% holdings."""
        _, summary = overlay(self.holdings, self.scan)

        flags = summary["attention_flags"]
        self.assertTrue(any("Momentum play" in f for f in flags))

    def test_summary_attention_flags_trend(self):
        """Trend-broken flag fires for below-SMA200 holdings."""
        _, summary = overlay(self.holdings, self.scan)

        flags = summary["attention_flags"]
        self.assertTrue(any("Trend broken" in f for f in flags))

    def test_summary_attention_flags_concentration(self):
        """Concentration flag fires for positions > 15%."""
        holdings = pd.DataFrame({
            "symbol": ["MEGA"],
            "quantity": [100],
            "average_price": [1000.0],
            "last_price": [1000.0],
            "isin": ["MEGAISN123"],
        })
        scan = pd.DataFrame({
            "symbol": ["MEGA"],
            "isin": ["MEGAISN123"],
            "bucket": ["5-15%"],
            "distance_pct": [10.0],
            "ath_date": ["2024-01-10"],
            "above_ema50": [True],
            "above_sma200": [True],
        })

        _, summary = overlay(holdings, scan)

        flags = summary["attention_flags"]
        # Single holding of 100,000 is 100% of portfolio
        self.assertTrue(any("Concentration" in f for f in flags))

    def test_summary_attention_flags_not_in_scan(self):
        """Not-in-scan flag fires for holdings not in scan."""
        holdings = pd.DataFrame({
            "symbol": ["INFY", "OUTSIDER"],
            "quantity": [10, 5],
            "average_price": [1500.0, 500.0],
            "last_price": [1600.0, 450.0],
            "isin": ["INE009A01021", "OUTSIDERISIN"],
        })
        scan = pd.DataFrame({
            "symbol": ["INFY"],
            "isin": ["INE009A01021"],
            "bucket": ["0-5%"],
            "distance_pct": [2.5],
            "ath_date": ["2024-01-15"],
            "above_ema50": [True],
            "above_sma200": [True],
        })

        _, summary = overlay(holdings, scan)

        flags = summary["attention_flags"]
        self.assertTrue(any("Not in scan" in f for f in flags))
        self.assertEqual(summary["total_holdings_not_in_scan"], 1)


class TestReadOnlyGuard(unittest.TestCase):
    """Test that portfolio module never references order placement methods."""

    def test_no_place_order_import(self):
        """Module does not import place_order."""
        import scanner.portfolio as pf

        # Check the module's namespace for disallowed methods
        disallowed = ["place_order", "modify_order", "cancel_order"]
        for method in disallowed:
            self.assertFalse(hasattr(pf, method),
                            f"portfolio module should not have {method}")

    def test_no_order_placement_in_overlay(self):
        """overlay() function never calls any order placement methods."""
        holdings = pd.DataFrame({
            "symbol": ["INFY"],
            "quantity": [10],
            "average_price": [1500.0],
            "last_price": [1600.0],
            "isin": ["INE009A01021"],
        })
        scan = pd.DataFrame({
            "symbol": ["INFY"],
            "isin": ["INE009A01021"],
            "bucket": ["0-5%"],
            "distance_pct": [2.5],
            "ath_date": ["2024-01-15"],
            "above_ema50": [True],
            "above_sma200": [True],
        })

        # This should never attempt any order operations
        with patch("scanner.portfolio.KiteConnect") as mock_kite:
            mock_kite.place_order = MagicMock()
            mock_kite.modify_order = MagicMock()
            mock_kite.cancel_order = MagicMock()

            portfolio, summary = overlay(holdings, scan)

            # Verify none of these were called
            mock_kite.place_order.assert_not_called()
            mock_kite.modify_order.assert_not_called()
            mock_kite.cancel_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
