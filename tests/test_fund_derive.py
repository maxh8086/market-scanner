"""Tests for the face value wiring in scanner/fund_derive.py. Offline: synthetic lines, no page."""
import unittest

from scanner.fund_derive import Line, face_value_from_overview, key_ratios, period_end


def _line(section: str, period: str, canonical: str, value: float) -> Line:
    return Line(section=section, period=period, period_end=period_end(period), label=canonical,
                canonical=canonical, raw=str(value), value=value)


# Rs crore: equity capital 100 and reserves 900 at Mar 2025 -> 50 crore shares at Rs 2 face value.
LINES = [
    _line("balance_sheet", "Mar 2025", "equity_capital", 100.0),
    _line("balance_sheet", "Mar 2025", "reserves", 900.0),
    _line("balance_sheet", "Mar 2025", "borrowings", 500.0),
    _line("profit_loss", "TTM", "eps", 40.0),
]


class FaceValueInKeyRatiosTests(unittest.TestCase):
    def test_face_value_is_output_and_drives_share_count(self):
        out = key_ratios(LINES, price=200.0, face_value=2.0)
        self.assertEqual(out["values"]["face_value"], 2.0)
        self.assertEqual(out["values"]["market_cap_cr"], 10000.0)  # 200 x (100 / 2) shares
        self.assertEqual(out["values"]["book_value"], 20.0)        # 1000 / 50 shares
        self.assertIn("top-ratios", out["basis"]["face_value"])

    def test_missing_face_value_leaves_share_based_values_empty(self):
        out = key_ratios(LINES, price=200.0)
        self.assertIsNone(out["values"]["face_value"])
        self.assertIsNone(out["values"]["market_cap_cr"])
        self.assertIsNone(out["values"]["book_value"])
        self.assertIn("not supplied", out["basis"]["face_value"])
        self.assertEqual(out["values"]["pe"], 5.0)  # price-only ratio still works

    def test_zero_face_value_is_treated_as_missing(self):
        out = key_ratios(LINES, price=200.0, face_value=0.0)
        self.assertIsNone(out["values"]["market_cap_cr"])


class FaceValueFromOverviewTests(unittest.TestCase):
    def test_reads_number_from_top_ratios(self):
        self.assertEqual(face_value_from_overview({"key_ratios": {"Face Value": "2"}}), 2.0)

    def test_reads_number_with_rupee_text(self):
        self.assertEqual(face_value_from_overview({"key_ratios": {"Face Value": "Rs. 10"}}), 10.0)

    def test_blank_or_absent_is_none(self):
        self.assertIsNone(face_value_from_overview({"key_ratios": {"Face Value": ""}}))
        self.assertIsNone(face_value_from_overview({"key_ratios": {}}))
        self.assertIsNone(face_value_from_overview({}))


if __name__ == "__main__":
    unittest.main()
