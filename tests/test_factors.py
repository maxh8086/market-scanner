"""Unit tests for scanner.factors — pure classifiers with synthetic data, no network."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from scanner.factors import (
    EXPANSION_KEYWORDS,
    _expansion_text,
    _int_or_none,
    _trim_announcement,
    classify_bonus,
    classify_demerger,
    classify_expansion,
    classify_orderbook,
    build_factor_table,
)

D0 = date(2026, 1, 1)


class TestClassifyBonus(unittest.TestCase):
    def test_bonus_within_window_matches(self):
        """Bonus within lookback window should be returned."""
        ca_rows = [
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Bonus 1:1",
                "exDate": "28-Nov-2024",  # Within 24 months of 2026-09-28
            }
        ]
        today = date(2026, 9, 28)
        result = classify_bonus(ca_rows, "INE123A01012", today)
        self.assertIn("Bonus 1:1", result)
        self.assertIn("2024-11-28", result)

    def test_no_bonus_returns_empty(self):
        """No bonus in rows should return empty string."""
        ca_rows = [
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Dividend",
                "exDate": "07-Oct-2024",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_bonus(ca_rows, "INE123A01012", today)
        self.assertEqual(result, "")

    def test_bonus_outside_window_ignored(self):
        """Bonus outside lookback window should be ignored."""
        ca_rows = [
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Bonus 1:1",
                "exDate": "07-Oct-2000",  # Way in the past
            }
        ]
        today = date(2026, 9, 28)
        result = classify_bonus(ca_rows, "INE123A01012", today)
        self.assertEqual(result, "")

    def test_multiple_bonuses_uses_most_recent_and_counts(self):
        """Multiple bonuses should use most recent and note count."""
        ca_rows = [
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Bonus 1:1",
                "exDate": "15-Nov-2024",  # Within 24 months
            },
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Bonus 1:2",
                "exDate": "15-Sep-2026",  # Within 24 months (only ~10 months old)
            },
        ]
        today = date(2026, 9, 28)
        result = classify_bonus(ca_rows, "INE123A01012", today)
        self.assertIn("Bonus", result)
        self.assertIn("2026-09-15", result)
        self.assertIn("2 in 24m", result)

    def test_wrong_isin_ignored(self):
        """Row with different ISIN should be ignored."""
        ca_rows = [
            {
                "isin": "INE999X01012",
                "symbol": "OTHER",
                "subject": "Bonus 1:1",
                "exDate": "07-Oct-2024",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_bonus(ca_rows, "INE123A01012", today)
        self.assertEqual(result, "")


class TestClassifyDemerger(unittest.TestCase):
    def test_demerger_executed_structured_feed(self):
        """Demerger with ex-date in past from CA feed should show as executed."""
        ca_rows = [
            {
                "isin": "INE154A01025",
                "symbol": "ITC",
                "subject": "Demerger",
                "exDate": "06-Jan-2025",
            }
        ]
        ann_rows = []
        today = date(2026, 9, 28)
        result = classify_demerger(ca_rows, ann_rows, "INE154A01025", today)
        self.assertIn("Demerger ex 2025-01-06", result)
        self.assertNotIn("UPCOMING", result)

    def test_demerger_upcoming_structured_feed(self):
        """Demerger with ex-date in future should show as UPCOMING."""
        ca_rows = [
            {
                "isin": "INE154A01025",
                "symbol": "ITC",
                "subject": "Demerger",
                "exDate": "06-Nov-2026",
            }
        ]
        ann_rows = []
        today = date(2026, 9, 28)
        result = classify_demerger(ca_rows, ann_rows, "INE154A01025", today)
        self.assertIn("Demerger UPCOMING", result)
        self.assertIn("2026-11-06", result)

    def test_demerger_announced_only_free_text(self):
        """Demerger from free-text announcement should show as announced-only."""
        ca_rows = []
        ann_rows = [
            {
                "sm_isin": "INE123A01012",
                "symbol": "TEST",
                "an_dt": "15-Jul-2026 10:00:00",
                "desc": "Corporate Announcement",
                "attchmntText": "Scheme of Arrangement: Demerger plan announced",
                "sort_date": "2026-07-15",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_demerger(ca_rows, ann_rows, "INE123A01012", today)
        self.assertIn("Demerger announced 2026-07-15", result)
        self.assertIn("no ex-date yet", result)

    def test_no_demerger_returns_empty(self):
        """No demerger should return empty string."""
        ca_rows = [
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Dividend",
                "exDate": "07-Oct-2024",
            }
        ]
        ann_rows = []
        today = date(2026, 9, 28)
        result = classify_demerger(ca_rows, ann_rows, "INE123A01012", today)
        self.assertEqual(result, "")

    def test_demerger_keyword_variations(self):
        """Various demerger keyword forms should match."""
        ca_rows = []
        for keyword in ["DEMERGER", "DE-MERGER", "SPIN-OFF", "SCHEME OF ARRANGEMENT"]:
            ann_rows = [
                {
                    "sm_isin": "INE123A01012",
                    "symbol": "TEST",
                    "an_dt": "15-Jul-2026 10:00:00",
                    "desc": "Announcement",
                    "attchmntText": keyword,
                    "sort_date": "2026-07-15",
                }
            ]
            today = date(2026, 9, 28)
            result = classify_demerger(ca_rows, ann_rows, "INE123A01012", today)
            self.assertNotEqual(result, "", f"Keyword {keyword} should have matched")


class TestClassifyOrderbook(unittest.TestCase):
    def test_orderbook_matches_keywords(self):
        """Order-book keywords should be matched."""
        ann_rows = [
            {
                "sm_isin": "INE234B01025",
                "symbol": "LT",
                "an_dt": "20-Sep-2026 14:30:00",
                "desc": "Corporate Updates",
                "attchmntText": "Company RECEIPT OF ORDER for major infrastructure project worth 100 crore",
                "sort_date": "2026-09-20",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_orderbook(ann_rows, "INE234B01025", today)
        self.assertNotEqual(result, "")
        self.assertIn("order", result.lower())

    def test_orderbook_counts_multiple_announcements(self):
        """Multiple order announcements should be counted."""
        ann_rows = [
            {
                "sm_isin": "INE234B01025",
                "symbol": "LT",
                "an_dt": "10-Sep-2026 10:00:00",
                "desc": "Updates",
                "attchmntText": "RECEIPT OF ORDER for infrastructure project",
                "sort_date": "2026-09-10",
            },
            {
                "sm_isin": "INE234B01025",
                "symbol": "LT",
                "an_dt": "20-Sep-2026 14:30:00",
                "desc": "Updates",
                "attchmntText": "ORDER WIN announced",
                "sort_date": "2026-09-20",
            },
        ]
        today = date(2026, 9, 28)
        result = classify_orderbook(ann_rows, "INE234B01025", today)
        self.assertIn("2 order", result)
        self.assertIn("2026-09-20", result)  # Most recent

    def test_orderbook_outside_window_ignored(self):
        """Announcements outside lookback window should be ignored."""
        ann_rows = [
            {
                "sm_isin": "INE234B01025",
                "symbol": "LT",
                "an_dt": "01-Jan-2025 10:00:00",
                "desc": "Updates",
                "attchmntText": "Received order",
                "sort_date": "2025-01-01",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_orderbook(ann_rows, "INE234B01025", today)
        # 12-month window from Sep 2026 is Sep 2025 onward; Jan 2025 is outside
        self.assertEqual(result, "")

    def test_no_orderbook_returns_empty(self):
        """No order-book keywords should return empty string."""
        ann_rows = [
            {
                "sm_isin": "INE234B01025",
                "symbol": "LT",
                "an_dt": "20-Sep-2026 14:30:00",
                "desc": "General Updates",
                "attchmntText": "Routine business update, nothing special",
                "sort_date": "2026-09-20",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_orderbook(ann_rows, "INE234B01025", today)
        self.assertEqual(result, "")


class TestClassifyExpansion(unittest.TestCase):
    def test_expansion_keyword_matches(self):
        """Expansion keywords should be matched."""
        ann_rows = [
            {
                "sm_isin": "INE123A01012",
                "symbol": "TEST",
                "an_dt": "15-Sep-2026 10:00:00",
                "desc": "Announcement",
                "attchmntText": "Company announces new CAPEX plan for facility expansion",
                "sort_date": "2026-09-15",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_expansion(ann_rows, "INE123A01012", today)
        self.assertNotEqual(result, "")
        self.assertIn("expansion", result.lower())

    def test_expansion_multiple_announcements(self):
        """Multiple expansion announcements should be counted."""
        ann_rows = [
            {
                "sm_isin": "INE123A01012",
                "symbol": "TEST",
                "an_dt": "01-Aug-2026 10:00:00",
                "desc": "Announcement",
                "attchmntText": "New greenfield project announced",
                "sort_date": "2026-08-01",
            },
            {
                "sm_isin": "INE123A01012",
                "symbol": "TEST",
                "an_dt": "15-Sep-2026 10:00:00",
                "desc": "Announcement",
                "attchmntText": "Capacity expansion plans",
                "sort_date": "2026-09-15",
            },
        ]
        today = date(2026, 9, 28)
        result = classify_expansion(ann_rows, "INE123A01012", today)
        self.assertIn("2 expansion", result)
        self.assertIn("2026-09-15", result)  # Most recent

    def test_expansion_outside_window_ignored(self):
        """Announcements outside lookback window should be ignored."""
        ann_rows = [
            {
                "sm_isin": "INE123A01012",
                "symbol": "TEST",
                "an_dt": "01-Mar-2026 10:00:00",
                "desc": "Announcement",
                "attchmntText": "Expansion plans",
                "sort_date": "2026-03-01",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_expansion(ann_rows, "INE123A01012", today)
        # 6-month window from Sep 2026 is Apr 2026 onward; Mar 2026 is outside
        self.assertEqual(result, "")

    def test_no_expansion_returns_empty(self):
        """No expansion keywords should return empty string."""
        ann_rows = [
            {
                "sm_isin": "INE123A01012",
                "symbol": "TEST",
                "an_dt": "15-Sep-2026 10:00:00",
                "desc": "Announcement",
                "attchmntText": "Routine dividend announcement",
                "sort_date": "2026-09-15",
            }
        ]
        today = date(2026, 9, 28)
        result = classify_expansion(ann_rows, "INE123A01012", today)
        self.assertEqual(result, "")


class TestBuildFactorTable(unittest.TestCase):
    def test_empty_inputs(self):
        """Empty inputs should return empty results."""
        result = build_factor_table([], [], [], date(2026, 9, 28))
        self.assertEqual(result, {})

    def test_factors_matched_count(self):
        """factors_matched should count non-empty factors correctly."""
        ca_rows = [
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Bonus 1:1",
                "exDate": "28-Nov-2024",  # Within 24-month window
            }
        ]
        ann_rows = [
            {
                "sm_isin": "INE123A01012",
                "symbol": "TEST",
                "an_dt": "20-Sep-2026 14:30:00",
                "desc": "Updates",
                "attchmntText": "RECEIPT OF ORDER for major project",
                "sort_date": "2026-09-20",
            }
        ]
        today = date(2026, 9, 28)
        result = build_factor_table(ca_rows, ann_rows, ["INE123A01012"], today)

        self.assertIn("INE123A01012", result)
        row = result["INE123A01012"]
        self.assertNotEqual(row["bonus_issue"], "")
        self.assertNotEqual(row["orderbook_signal"], "")
        self.assertEqual(row["demerger"], "")
        self.assertEqual(row["expansion_signal"], "")
        self.assertEqual(row["factors_matched"], 2)

    def test_all_factors_matched(self):
        """Test case where all four factors are present."""
        ca_rows = [
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Bonus 1:1",
                "exDate": "28-Nov-2024",  # Within 24-month window
            },
            {
                "isin": "INE123A01012",
                "symbol": "TEST",
                "subject": "Demerger",
                "exDate": "06-May-2025",  # Within 24-month window
            },
        ]
        ann_rows = [
            {
                "sm_isin": "INE123A01012",
                "symbol": "TEST",
                "an_dt": "20-Sep-2026 14:30:00",
                "desc": "Updates",
                "attchmntText": "RECEIPT OF ORDER and EXPANSION plan announced",
                "sort_date": "2026-09-20",
            }
        ]
        today = date(2026, 9, 28)
        result = build_factor_table(ca_rows, ann_rows, ["INE123A01012"], today)

        row = result["INE123A01012"]
        self.assertNotEqual(row["bonus_issue"], "")
        self.assertNotEqual(row["demerger"], "")
        self.assertNotEqual(row["orderbook_signal"], "")
        self.assertNotEqual(row["expansion_signal"], "")
        self.assertEqual(row["factors_matched"], 4)

    def test_isin_indexing_efficiency(self):
        """Multiple ISINs should be indexed correctly without duplicates."""
        ca_rows = [
            {"isin": "ISIN1", "symbol": "SYM1", "subject": "Bonus 1:1", "exDate": "07-Oct-2024"},
            {"isin": "ISIN1", "symbol": "SYM1", "subject": "Bonus 1:2", "exDate": "08-Oct-2024"},
            {"isin": "ISIN2", "symbol": "SYM2", "subject": "Dividend", "exDate": "07-Oct-2024"},
        ]
        ann_rows = []
        today = date(2026, 9, 28)
        result = build_factor_table(ca_rows, ann_rows, ["ISIN1", "ISIN2"], today)

        self.assertIn("ISIN1", result)
        self.assertIn("ISIN2", result)
        # ISIN1 has bonuses, ISIN2 doesn't
        self.assertNotEqual(result["ISIN1"]["bonus_issue"], "")
        self.assertEqual(result["ISIN2"]["bonus_issue"], "")

    def test_missing_isin_returns_zeros(self):
        """ISIN not in input list should be handled correctly."""
        ca_rows = []
        ann_rows = []
        today = date(2026, 9, 28)
        result = build_factor_table(ca_rows, ann_rows, ["ISIN_MISSING"], today)

        self.assertIn("ISIN_MISSING", result)
        row = result["ISIN_MISSING"]
        self.assertEqual(row["bonus_issue"], "")
        self.assertEqual(row["demerger"], "")
        self.assertEqual(row["orderbook_signal"], "")
        self.assertEqual(row["expansion_signal"], "")
        self.assertEqual(row["factors_matched"], 0)


class TestFileSize(unittest.TestCase):
    """NSE sends attFileSize as a human string, not a byte count."""

    def test_the_units_nse_actually_sends_are_parsed(self):
        """Probed against the live API: '3.71 MB', '512 KB' are the real shape.

        `int(float("3.71 MB"))` raises, so this returned None for every row and
        the MAX_PDF_BYTES guard in `enrich.stage_filings` never fired -- its
        `isinstance(size, (int, float))` test is False for None.
        """
        self.assertEqual(_int_or_none("3.71 MB"), int(3.71 * 1024 ** 2))
        self.assertEqual(_int_or_none("512 KB"), 512 * 1024)
        self.assertEqual(_int_or_none("1.5 GB"), int(1.5 * 1024 ** 3))
        self.assertEqual(_int_or_none("900 B"), 900)

    def test_a_bare_number_is_still_bytes(self):
        """The column has always been documented as bytes; don't break that."""
        self.assertEqual(_int_or_none("2048"), 2048)
        self.assertEqual(_int_or_none(4096), 4096)

    def test_unusable_values_give_none_rather_than_a_wrong_number(self):
        for bad in (None, "", "   ", "unknown", "3.71 TB", "MB", True):
            self.assertIsNone(_int_or_none(bad), f"{bad!r} should be None")

    def test_a_size_over_the_cap_is_recognised_as_over_it(self):
        """The guard's whole purpose: a 20 MB annual report must read as large.

        Pinned as the comparison `stage_filings` actually makes, because the bug
        was not a wrong number -- it was None silently failing an isinstance
        check, which no assertion about parsing alone would have caught.
        """
        size = _int_or_none("20 MB")
        self.assertIsInstance(size, int)
        self.assertGreater(size, 5 * 1024 ** 2)


class TestAnnouncementTrim(unittest.TestCase):
    def test_nse_sends_seq_id_not_seqId(self):
        """The field is snake_case among camelCase neighbours.

        Reading `seqId` gave "" on every row, and since the trim runs before the
        cache write, `_save_announcements`'s `or row.get("seq_id")` fallback never
        saw the original key. Result: a blank column on all 391,074 cached rows,
        and `enrich._candidate_filings` dropping every candidate on its
        `if not f["seq_id"]` guard while reporting "no filing carried a PDF URL".
        """
        raw = {"sm_isin": "INE001A01036", "symbol": "X", "an_dt": "26-Sep-2026",
               "desc": "Award of Order", "attchmntText": "t",
               "sort_date": "2026-09-26 23:48:22", "seq_id": 106796207,
               "attchmntFile": "https://x/y.pdf", "attFileSize": "3.71 MB"}
        trimmed = _trim_announcement(raw)
        self.assertEqual(trimmed["seqId"], 106796207)

    def test_the_camelCase_spelling_is_still_accepted(self):
        """Older cached payloads and the tests' own fixtures use seqId."""
        self.assertEqual(_trim_announcement({"seqId": "42"})["seqId"], "42")

    def test_a_missing_id_is_empty_not_absent(self):
        """Callers index this key directly, so it must always exist."""
        self.assertEqual(_trim_announcement({})["seqId"], "")


class TestExpansionFalseSenses(unittest.TestCase):
    """"margin expansion" is a profitability metric, not a bigger factory.

    It put AXISCADES in the expansion column off an ordinary earnings headline,
    and through that mislabelled its order as backed by a capacity plan. Found by
    reading which announcement a report label pointed at, not by a unit test.
    """

    def test_margin_expansion_alone_does_not_qualify(self):
        text = _expansion_text(
            "AXISCADES reports FY26 revenue of Rs. 1,159 crore, up 12.4%; "
            "EBITDA up 24.6% with margin expansion")
        self.assertFalse(
            any(kw in text for kw in EXPANSION_KEYWORDS),
            "an earnings headline is not a capacity announcement")

    def test_real_capacity_language_still_qualifies(self):
        for phrase in ("Capacity expansion at the Hyderabad plant",
                       "Commissioned the new line",
                       "Board approved Capex of Rs 500 crore",
                       "Greenfield facility at Sanand"):
            with self.subTest(phrase=phrase):
                text = _expansion_text(phrase)
                self.assertTrue(
                    any(kw in text for kw in EXPANSION_KEYWORDS))

    def test_a_release_mentioning_both_keeps_its_real_content(self):
        """The false sense is removed from the text rather than used to reject
        the row, so genuine content in the same release survives."""
        text = _expansion_text(
            "Commissioned the new line, with margin expansion of 200 bps")
        self.assertIn("COMMISSIONED", text)
        self.assertNotIn("MARGIN EXPANSION", text)

    def test_valuation_multiple_expansion_is_also_excluded(self):
        text = _expansion_text("Re-rating driven by multiple expansion")
        self.assertFalse(any(kw in text for kw in EXPANSION_KEYWORDS))


if __name__ == "__main__":
    unittest.main()
