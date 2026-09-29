"""Unit tests for scanner.crosscheck — price comparison and validation.

Tests use mocked HTTP responses and temporary cache files. No real network calls.
"""
from __future__ import annotations

import csv
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from scanner.crosscheck import (
    AthCheckResult,
    ComparisonResult,
    FallbackChain,
    NseBhavcopy,
    PriceSource,
    PriceSnapshot,
    check_ath,
    compare,
    summarize_comparison,
)


# Synthetic PriceSource for testing
class MockPriceSource(PriceSource):
    """Simple in-memory mock for testing."""

    def __init__(self, name: str = "Mock"):
        self._name = name
        self.data: dict[str, dict[date, PriceSnapshot]] = {}

    @property
    def name(self) -> str:
        return self._name

    def add_price(self, symbol: str, snapshot: PriceSnapshot) -> None:
        """Add a price snapshot."""
        if symbol not in self.data:
            self.data[symbol] = {}
        self.data[symbol][snapshot.date] = snapshot

    def close_on(self, symbol: str, on_date: date) -> float | None:
        snapshot = self.data.get(symbol, {}).get(on_date)
        return snapshot.close if snapshot else None

    def high_between(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> float | None:
        snapshots = self.data.get(symbol, {})
        highs = [snap.high for d, snap in snapshots.items() if from_date <= d <= to_date]
        return max(highs) if highs else None


class TestMockPriceSource(unittest.TestCase):
    """Sanity-check the mock itself."""

    def test_close_on(self):
        source = MockPriceSource()
        snap = PriceSnapshot(
            date=date(2026, 9, 29),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.5,
        )
        source.add_price("INFY", snap)
        self.assertEqual(source.close_on("INFY", date(2026, 9, 29)), 102.5)
        self.assertIsNone(source.close_on("INFY", date(2026, 9, 28)))
        self.assertIsNone(source.close_on("UNKNOWN", date(2026, 9, 29)))

    def test_high_between(self):
        source = MockPriceSource()
        source.add_price(
            "TCS",
            PriceSnapshot(date(2026, 9, 27), open=200.0, high=210.0, low=198.0, close=205.0),
        )
        source.add_price(
            "TCS",
            PriceSnapshot(date(2026, 9, 28), open=205.0, high=215.0, low=203.0, close=212.0),
        )
        source.add_price(
            "TCS",
            PriceSnapshot(date(2026, 9, 29), open=212.0, high=220.0, low=210.0, close=218.0),
        )

        self.assertEqual(source.high_between("TCS", date(2026, 9, 27), date(2026, 9, 29)), 220.0)
        self.assertEqual(source.high_between("TCS", date(2026, 9, 28), date(2026, 9, 29)), 220.0)
        self.assertEqual(source.high_between("TCS", date(2026, 9, 27), date(2026, 9, 27)), 210.0)
        self.assertIsNone(source.high_between("TCS", date(2026, 9, 30), date(2026, 10, 1)))


class TestComparisonVerdicts(unittest.TestCase):
    """Test close-price comparison and verdict logic."""

    def setUp(self):
        self.source = MockPriceSource("Test")
        # Add a price for 2026-09-29
        self.source.add_price(
            "INFY",
            PriceSnapshot(date(2026, 9, 29), open=100.0, high=105.0, low=99.0, close=100.0),
        )

    def test_ok_within_tolerance(self):
        """Scan LTP within tolerance should be OK."""
        scan_df = pd.DataFrame({
            "symbol": ["INFY"],
            "ltp": [100.25],  # 0.25% above close
        })
        result = compare(scan_df, self.source, date(2026, 9, 29), tol_pct=0.5)
        self.assertEqual(result.iloc[0]["verdict"], "OK")
        self.assertAlmostEqual(result.iloc[0]["diff_pct"], 0.25, places=2)

    def test_diverged_outside_tolerance(self):
        """Scan LTP outside tolerance should be DIVERGED."""
        scan_df = pd.DataFrame({
            "symbol": ["INFY"],
            "ltp": [101.0],  # 1% above close
        })
        result = compare(scan_df, self.source, date(2026, 9, 29), tol_pct=0.5)
        self.assertEqual(result.iloc[0]["verdict"], "DIVERGED")
        self.assertAlmostEqual(result.iloc[0]["diff_pct"], 1.0, places=1)

    def test_no_data(self):
        """Missing price data should be NO_DATA."""
        scan_df = pd.DataFrame({
            "symbol": ["UNKNOWN"],
            "ltp": [100.0],
        })
        result = compare(scan_df, self.source, date(2026, 9, 29))
        self.assertEqual(result.iloc[0]["verdict"], "NO_DATA")
        self.assertIsNone(result.iloc[0]["source_close"])

    def test_tolerance_edge_lower(self):
        """Exactly at lower tolerance edge should be OK."""
        scan_df = pd.DataFrame({
            "symbol": ["INFY"],
            "ltp": [99.5],  # 0.5% below close
        })
        result = compare(scan_df, self.source, date(2026, 9, 29), tol_pct=0.5)
        self.assertEqual(result.iloc[0]["verdict"], "OK")

    def test_tolerance_edge_upper(self):
        """Exactly at upper tolerance edge should be OK."""
        scan_df = pd.DataFrame({
            "symbol": ["INFY"],
            "ltp": [100.5],  # 0.5% above close
        })
        result = compare(scan_df, self.source, date(2026, 9, 29), tol_pct=0.5)
        self.assertEqual(result.iloc[0]["verdict"], "OK")

    def test_multiple_symbols(self):
        """Compare multiple symbols at once."""
        self.source.add_price(
            "TCS",
            PriceSnapshot(date(2026, 9, 29), open=200.0, high=205.0, low=198.0, close=200.0),
        )

        scan_df = pd.DataFrame({
            "symbol": ["INFY", "TCS", "UNKNOWN"],
            "ltp": [100.0, 200.0, 150.0],
        })
        result = compare(scan_df, self.source, date(2026, 9, 29), tol_pct=0.5)

        self.assertEqual(len(result), 3)
        self.assertEqual(result.iloc[0]["verdict"], "OK")  # INFY
        self.assertEqual(result.iloc[1]["verdict"], "OK")  # TCS
        self.assertEqual(result.iloc[2]["verdict"], "NO_DATA")  # UNKNOWN


class TestFallbackChain(unittest.TestCase):
    """Test fallback chain ordering and provenance tracking."""

    def test_tries_sources_in_order(self):
        """Should return first source that has data."""
        source1 = MockPriceSource("Source1")
        source2 = MockPriceSource("Source2")
        source3 = MockPriceSource("Source3")

        # Only source2 has INFY
        source2.add_price(
            "INFY",
            PriceSnapshot(date(2026, 9, 29), open=100.0, high=105.0, low=99.0, close=100.0),
        )

        chain = FallbackChain([source1, source2, source3])
        result = chain.close_on("INFY", date(2026, 9, 29))

        self.assertEqual(result, 100.0)
        self.assertEqual(chain.get_provenance("INFY", date(2026, 9, 29)), "Source2")

    def test_prefers_first_source(self):
        """Should prefer earlier sources even if later ones also have data."""
        source1 = MockPriceSource("Source1")
        source2 = MockPriceSource("Source2")

        # Both have the price, but source1 should be used
        source1.add_price(
            "INFY",
            PriceSnapshot(date(2026, 9, 29), open=100.0, high=105.0, low=99.0, close=100.0),
        )
        source2.add_price(
            "INFY",
            PriceSnapshot(date(2026, 9, 29), open=100.0, high=105.0, low=99.0, close=100.5),
        )

        chain = FallbackChain([source1, source2])
        result = chain.close_on("INFY", date(2026, 9, 29))

        self.assertEqual(result, 100.0)
        self.assertEqual(chain.get_provenance("INFY", date(2026, 9, 29)), "Source1")

    def test_no_data_from_any_source(self):
        """Should return None if no source has data."""
        source1 = MockPriceSource("Source1")
        source2 = MockPriceSource("Source2")

        chain = FallbackChain([source1, source2])
        result = chain.close_on("INFY", date(2026, 9, 29))

        self.assertIsNone(result)
        self.assertIsNone(chain.get_provenance("INFY", date(2026, 9, 29)))

    def test_high_between_chain(self):
        """Test high_between through fallback chain."""
        source1 = MockPriceSource("Source1")
        source2 = MockPriceSource("Source2")

        # Only source2 has data
        source2.add_price(
            "TCS",
            PriceSnapshot(date(2026, 9, 27), open=200.0, high=210.0, low=198.0, close=205.0),
        )
        source2.add_price(
            "TCS",
            PriceSnapshot(date(2026, 9, 28), open=205.0, high=215.0, low=203.0, close=212.0),
        )

        chain = FallbackChain([source1, source2])
        result = chain.high_between("TCS", date(2026, 9, 27), date(2026, 9, 28))

        self.assertEqual(result, 215.0)


class TestNseBhavcopyParsing(unittest.TestCase):
    """Test bhavcopy CSV parsing and filtering."""

    def test_parses_eq_series_only(self):
        """Should only parse EQ series, ignore others."""
        csv_text = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TIMESTAMP\n"
        csv_text += "INFY,EQ,100.0,105.0,99.0,102.5,29-Sep-2026\n"
        csv_text += "INFY,BE,110.0,115.0,108.0,112.5,29-Sep-2026\n"  # Bulk Equities
        csv_text += "TCS,EQ,200.0,205.0,198.0,202.5,29-Sep-2026\n"

        source = NseBhavcopy()
        data = source._parse_bhavcopy_csv(csv_text)

        self.assertIn("INFY", data)
        self.assertIn("TCS", data)
        self.assertEqual(len(data), 2)
        self.assertAlmostEqual(data["INFY"].close, 102.5)
        self.assertAlmostEqual(data["TCS"].close, 202.5)

    def test_handles_malformed_csv(self):
        """Should gracefully skip malformed lines."""
        csv_text = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TIMESTAMP\n"
        csv_text += "INFY,EQ,100.0,105.0,99.0,102.5,29-Sep-2026\n"
        csv_text += "BROKEN,EQ,not_a_number,105.0,99.0,102.5,29-Sep-2026\n"  # Bad HIGH
        csv_text += "TCS,EQ,200.0,205.0,198.0,202.5,29-Sep-2026\n"

        source = NseBhavcopy()
        data = source._parse_bhavcopy_csv(csv_text)

        # Should only have valid entries
        self.assertEqual(len(data), 2)
        self.assertIn("INFY", data)
        self.assertIn("TCS", data)

    def test_uppercase_symbols(self):
        """Should uppercase symbol names."""
        csv_text = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TIMESTAMP\n"
        csv_text += "infy,EQ,100.0,105.0,99.0,102.5,29-Sep-2026\n"

        source = NseBhavcopy()
        data = source._parse_bhavcopy_csv(csv_text)

        self.assertIn("INFY", data)
        self.assertNotIn("infy", data)

    def test_date_parsing_formats(self):
        """Should handle date formats with - separator."""
        csv_text = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TIMESTAMP\n"
        csv_text += "INFY,EQ,100.0,105.0,99.0,102.5,29-Sep-2026\n"

        source = NseBhavcopy()
        data = source._parse_bhavcopy_csv(csv_text)

        self.assertEqual(data["INFY"].date, date(2026, 9, 29))


class TestAthCheck(unittest.TestCase):
    """Test ATH verification logic."""

    def setUp(self):
        self.source = MockPriceSource("Test")
        # Add historical highs
        self.source.add_price(
            "INFY",
            PriceSnapshot(date(2026, 1, 1), open=100.0, high=105.0, low=99.0, close=102.0),
        )
        self.source.add_price(
            "INFY",
            PriceSnapshot(date(2026, 6, 15), open=110.0, high=125.0, low=108.0, close=120.0),
        )
        self.source.add_price(
            "INFY",
            PriceSnapshot(date(2026, 9, 29), open=120.0, high=122.0, low=118.0, close=120.0),
        )

    def test_ath_matches_source(self):
        """Scan ATH should match source high within tolerance."""
        scan_df = pd.DataFrame({
            "symbol": ["INFY"],
            "ath_high": [125.0],
            "ath_date": ["2026-06-15"],
        })
        result = check_ath(scan_df, self.source, tol_pct=0.5)
        self.assertEqual(result.iloc[0]["verdict"], "OK")
        self.assertEqual(result.iloc[0]["source_high"], 125.0)

    def test_ath_diverged_lower(self):
        """Scan ATH lower than source high should be DIVERGED."""
        scan_df = pd.DataFrame({
            "symbol": ["INFY"],
            "ath_high": [124.0],  # Lower than source max of 125
            "ath_date": ["2026-06-15"],
        })
        result = check_ath(scan_df, self.source, tol_pct=0.5)
        self.assertEqual(result.iloc[0]["verdict"], "DIVERGED")

    def test_ath_higher_than_source(self):
        """Scan ATH higher than source max should be OK (unadjusted gap)."""
        scan_df = pd.DataFrame({
            "symbol": ["INFY"],
            "ath_high": [126.0],  # Higher than source max of 125
            "ath_date": ["2026-06-15"],
        })
        result = check_ath(scan_df, self.source, tol_pct=0.5)
        self.assertEqual(result.iloc[0]["verdict"], "OK")

    def test_ath_no_data(self):
        """Missing source data should be NO_DATA."""
        scan_df = pd.DataFrame({
            "symbol": ["UNKNOWN"],
            "ath_high": [100.0],
            "ath_date": ["2026-06-15"],
        })
        result = check_ath(scan_df, self.source, tol_pct=0.5)
        self.assertEqual(result.iloc[0]["verdict"], "NO_DATA")

    def test_source_high_after_scan_ath_date(self):
        """Source high on later date than ATH date should not affect check.

        Real case: scan on 2026-09-28 intraday reports ATH high from 2026-06-15,
        but Bhavcopy source only has data up to 2026-09-29. We should only
        compare against highs up to the ATH date.
        """
        # Source has a higher high on 2026-09-29 (after ath_date)
        self.source.add_price(
            "INFY",
            PriceSnapshot(date(2026, 9, 29), open=120.0, high=130.0, low=118.0, close=125.0),
        )

        scan_df = pd.DataFrame({
            "symbol": ["INFY"],
            "ath_high": [125.0],
            "ath_date": ["2026-06-15"],  # Before the 2026-09-29 high
        })
        result = check_ath(scan_df, self.source, tol_pct=0.5)

        # Should only see the max up to 2026-06-15, which is 125
        self.assertEqual(result.iloc[0]["verdict"], "OK")


class TestSummarize(unittest.TestCase):
    """Test result summarization."""

    def test_counts_verdicts(self):
        """Should count each verdict type."""
        result_df = pd.DataFrame({
            "symbol": ["A", "B", "C", "D"],
            "verdict": ["OK", "OK", "DIVERGED", "NO_DATA"],
            "diff_pct": [0.1, 0.2, -1.5, None],
        })
        summary = summarize_comparison(result_df)

        self.assertEqual(summary["ok"], 2)
        self.assertEqual(summary["diverged"], 1)
        self.assertEqual(summary["no_data"], 1)
        self.assertEqual(summary["total"], 4)

    def test_worst_divergences(self):
        """Should identify largest divergences."""
        result_df = pd.DataFrame({
            "symbol": ["A", "B", "C"],
            "verdict": ["DIVERGED", "DIVERGED", "OK"],
            "diff_pct": [-5.0, 2.5, 0.1],
            "scan_ltp": [95.0, 102.5, 100.1],
            "source_close": [100.0, 100.0, 100.0],
        })
        summary = summarize_comparison(result_df)

        self.assertEqual(len(summary["worst_divergences"]), 2)
        # Should be sorted by absolute diff descending
        self.assertEqual(summary["worst_divergences"][0]["symbol"], "A")
        self.assertAlmostEqual(summary["worst_divergences"][0]["diff_pct"], -5.0)
        self.assertEqual(summary["worst_divergences"][1]["symbol"], "B")


class TestNseBhavcopyCache(unittest.TestCase):
    """Test caching behavior."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_file_created(self):
        """Should save downloaded data to cache."""
        source = NseBhavcopy(cache_dir=self.cache_dir)

        # Parse and cache a day's data
        csv_text = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TIMESTAMP\n"
        csv_text += "INFY,EQ,100.0,105.0,99.0,102.5,29-Sep-2026\n"
        csv_text += "TCS,EQ,200.0,205.0,198.0,202.5,29-Sep-2026\n"

        data = source._parse_bhavcopy_csv(csv_text)
        source._save_to_cache_file(date(2026, 9, 29), data)

        cache_file = self.cache_dir / "bhavcopy_20260929.csv"
        self.assertTrue(cache_file.exists())

        # Verify file contains our data
        content = cache_file.read_text(encoding="utf-8")
        self.assertIn("INFY", content)
        self.assertIn("TCS", content)
        self.assertIn("102.5", content)

    def test_loads_from_cache_file(self):
        """Should load from cache file if available."""
        source = NseBhavcopy(cache_dir=self.cache_dir)

        # Pre-create a cache file
        csv_text = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TIMESTAMP\n"
        csv_text += "INFY,EQ,100.0,105.0,99.0,102.5,29-Sep-2026\n"

        data = source._parse_bhavcopy_csv(csv_text)
        source._save_to_cache_file(date(2026, 9, 29), data)

        # Create a new source instance (simulating fresh start)
        source2 = NseBhavcopy(cache_dir=self.cache_dir)
        result = source2._load_from_cache_file("INFY", date(2026, 9, 29))

        self.assertIsNotNone(result)
        self.assertEqual(result.close, 102.5)


if __name__ == "__main__":
    unittest.main()
