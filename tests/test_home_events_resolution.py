"""Offline fixture-crossing name-resolution test (F-T4f, O2/O3). No DB, no network.

Crosses the eight real NSE fixtures in tests/fixtures/home_events/ with a small
committed name index and records resolved and rejected counts per feed.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from scanner import company_reference as cr
from scanner import home_events as he

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "home_events"
INDEX_PATH = ROOT / "tests" / "fixtures" / "home_events_resolution" / "name_index.json"

# Virinchi Limited appears twice in the index with different symbol and ISIN, so it is a name conflict.
CONFLICT_SYMBOLS = {"VIRINCHIA", "VIRINCHIB"}
CONFLICT_NAME_KEY = "VIRINCHI LTD"

# feed_code -> (parsed, resolved, rejected). Literals were computed by running the code once.
EXPECTED = {
    "nse:Financial_Results": (3, 3, 0),
    "nse:Integrated_Filing_Financials": (20, 6, 14),
    "nse:Sast_Regulation29": (20, 7, 13),
    "nse:Sast_Regulation31": (20, 7, 13),
    "nse:Corporate_action": (58, 4, 54),
    "nse:Corporate_Governance": (0, 0, 0),
    "nse:Related_Party_Trans": (20, 9, 11),
    "nse:Shareholding_Pattern": (1, 1, 0),
}


def _load_index() -> cr.Index:
    rows = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return cr.build_index(
        [(r["source"], r["symbol"], r["isin"], r["name_key"]) for r in rows]
    )


def _fixture_bytes(feed_code: str) -> bytes:
    name = feed_code.split(":", 1)[1]
    return (FIXTURE_DIR / f"nse_{name}.xml").read_bytes()


class HomeEventsResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = _load_index()
        cls.results: dict[str, dict] = {}
        for feed in he.FEEDS:
            parsed = he.parse(feed.feed_code, _fixture_bytes(feed.feed_code))
            filled = cr.fill_from_name(parsed.items, cls.index.by_name)
            kept, counts = he.filter_items(filled, cls.index.universe)
            cls.results[feed.feed_code] = {
                "parsed": len(parsed.items),
                "kept": kept,
                "rejected": counts["universe"],
                "resolved": len(kept),
            }

    def test_index_has_one_name_conflict_left_out_of_by_name(self) -> None:
        self.assertIn(f"name:{CONFLICT_NAME_KEY}", self.index.conflicts)
        self.assertNotIn(CONFLICT_NAME_KEY, self.index.by_name)
        for symbol in CONFLICT_SYMBOLS:
            self.assertIn(symbol, self.index.universe)

    def test_feed_codes_match_expected_table(self) -> None:
        self.assertEqual(sorted(f.feed_code for f in he.FEEDS), sorted(EXPECTED))

    def test_per_feed_parsed_resolved_rejected_counts(self) -> None:
        for feed_code, (parsed, resolved, rejected) in EXPECTED.items():
            with self.subTest(feed=feed_code):
                got = self.results[feed_code]
                self.assertEqual(got["parsed"], parsed)
                self.assertEqual(got["resolved"], resolved)
                self.assertEqual(got["rejected"], rejected)
                self.assertEqual(got["resolved"] + got["rejected"], got["parsed"])

    def test_conflicting_name_is_never_resolved_to_either_pair(self) -> None:
        ambiguous = 0
        for feed_code, result in self.results.items():
            for item in result["kept"]:
                if item.get("symbol") in CONFLICT_SYMBOLS:
                    ambiguous += 1
        self.assertEqual(ambiguous, 0)

    def test_sast_regulation31_has_twenty_items_and_balances(self) -> None:
        got = self.results["nse:Sast_Regulation31"]
        self.assertEqual(got["parsed"], 20)
        self.assertEqual(got["resolved"] + got["rejected"], 20)

    def test_total_parsed_items_across_all_feeds(self) -> None:
        total = sum(r["parsed"] for r in self.results.values())
        self.assertEqual(total, 142)


class CountIsinConflictsTest(unittest.TestCase):
    def test_counts_only_name_resolvable_disagreeing_isin(self) -> None:
        by_name = _load_index().by_name
        disagreeing = {
            "company": "Gammon India Limited",
            "symbol": None,
            "isin": "INEZZZ999999",
            "headline": "x",
        }
        agreeing = {
            "company": "Ajanta Pharma Limited",
            "symbol": None,
            "isin": "INEAJP000001",
            "headline": "y",
        }
        self.assertEqual(he.count_isin_conflicts([disagreeing, agreeing], by_name), 1)


if __name__ == "__main__":
    unittest.main()
