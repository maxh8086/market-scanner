"""Tests for scanner.orderval.

The text fixtures are the shapes actually seen in the 40 filings measured on
2026-09-28, including the two that broke the first attempt: WELCORP (largest
money figure was a market-size sentence) and RAILTEL (Indian digit grouping
with no scale word).
"""

import unittest

from scanner import orderval as ov


class TestAnchoredScaled(unittest.TestCase):
    def test_sebi_template_field_g(self):
        text = (
            "g. Broad consideration or size of order(s)/contract(s) (in INR): "
            "Rs. 1,250.50 crore (excluding GST)"
        )
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 1250.50, places=2)
        self.assertTrue(r.trustworthy)

    def test_lakhs_scale(self):
        r = ov.parse_order_value("Order value: Rs. 500 lakhs")
        self.assertAlmostEqual(r.rupees, 5e7)

    def test_million_scale(self):
        r = ov.parse_order_value("Contract value of INR 250 million")
        self.assertAlmostEqual(r.rupees, 2.5e8)

    def test_abbreviated_cr(self):
        r = ov.parse_order_value("Total order value Rs 85.5 Cr.")
        self.assertAlmostEqual(r.crore, 85.5, places=2)

    def test_rupee_symbol(self):
        r = ov.parse_order_value("Size of the order: \u20b9 340 crore")
        self.assertAlmostEqual(r.crore, 340.0)


class TestAnchoredBare(unittest.TestCase):
    def test_railtel_indian_grouping(self):
        """The case a scale-word-only regex missed entirely."""
        text = (
            "Broad consideration or size of order(s)/contract(s) (in INR): "
            "Rs. 21,57,48,840/- (Rupees Twenty One Crore Fifty Seven Lakh...)"
        )
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_BARE)
        self.assertAlmostEqual(r.rupees, 215748840.0)
        self.assertAlmostEqual(r.crore, 21.5748840, places=4)
        self.assertTrue(r.trustworthy)

    def test_western_grouping_reduces_the_same_way(self):
        r = ov.parse_order_value("Order value: INR 1,234,567")
        self.assertAlmostEqual(r.rupees, 1234567.0)

    def test_scaled_wins_over_bare_under_the_same_label(self):
        """Both patterns match here; the scaled reading is the correct one."""
        r = ov.parse_order_value("Order value: Rs. 45 crore")
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 45.0)


class TestWithheld(unittest.TestCase):
    def test_confidentiality_under_the_label(self):
        text = (
            "Broad consideration or size of order(s)/contract(s) (in INR): "
            "The same cannot be disclosed due to confidentiality obligations "
            "with the customer."
        )
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_WITHHELD)
        self.assertIsNone(r.rupees)
        self.assertFalse(r.trustworthy)

    def test_withheld_label_does_not_fall_through_to_a_later_figure(self):
        """A withheld order value must not pick up an unrelated rupee figure
        later in the document -- that would invent a number the issuer refused
        to give."""
        text = (
            "Order value: not disclosed as per confidentiality clause. "
            "The Company's paid up capital is Rs. 500 crore."
        )
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_WITHHELD)
        self.assertIsNone(r.rupees)


class TestForeignCurrency(unittest.TestCase):
    def test_usd_captured_but_not_converted(self):
        r = ov.parse_order_value("Order value: USD 45 million")
        self.assertEqual(r.confidence, ov.CONF_FOREIGN)
        self.assertEqual(r.currency, "USD")
        self.assertIsNone(r.rupees, "no FX rate should ever be applied")
        self.assertFalse(r.trustworthy)

    def test_rupee_figure_preferred_over_a_usd_one(self):
        text = "Order value: Rs. 370 crore (approximately USD 44 million)"
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 370.0)


class TestLoose(unittest.TestCase):
    def test_welcorp_style_market_size_is_flagged_not_trusted(self):
        """No mandated label: the largest figure is returned but marked loose,
        because this is exactly how Rs 45,000 cr got in."""
        text = (
            "The global line pipe market is estimated at Rs. 45,000 crore. "
            "The Company has secured orders worth Rs. 4,000 crore."
        )
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_LOOSE)
        self.assertFalse(r.trustworthy, "a loose parse must never read as filed")

    def test_anchor_beats_a_larger_unanchored_figure(self):
        """With the label present, the smaller anchored figure is correct."""
        text = (
            "The global market is estimated at Rs. 45,000 crore. "
            "Broad consideration or size of order(s)/contract(s) (in INR): "
            "Rs. 4,000 crore."
        )
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 4000.0)
        self.assertTrue(r.trustworthy)


class TestBoundsAndNoise(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(ov.parse_order_value("").confidence, ov.CONF_NONE)
        self.assertEqual(ov.parse_order_value(None).confidence, ov.CONF_NONE)

    def test_no_money_anywhere(self):
        r = ov.parse_order_value(
            "Pursuant to Regulation 30 of SEBI (LODR) Regulations, 2015, "
            "we wish to inform you that the Company has received a Letter of Award."
        )
        self.assertEqual(r.confidence, ov.CONF_NONE)

    def test_tiny_figure_rejected_as_a_clause_number(self):
        """Rs 30 is a regulation reference, not an order value."""
        r = ov.parse_order_value("Order value: Rs. 30")
        self.assertIsNone(r.rupees)

    def test_absurd_figure_rejected(self):
        r = ov.parse_order_value("Order value: Rs. 99,00,000 crore")
        self.assertIsNone(r.rupees)

    def test_pdf_line_breaks_do_not_hide_the_value(self):
        """pypdf output is full of newlines; the label and value are often split."""
        text = "Broad consideration or size of\norder(s)/contract(s) (in INR)\n:\nRs. 512\ncrore"
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 512.0)

    def test_window_does_not_reach_a_distant_figure(self):
        far = "Order value: " + ("filler words " * 40) + "Rs. 900 crore"
        self.assertGreater(len(far), ov._WINDOW)
        r = ov.parse_order_value(far)
        self.assertNotEqual(r.confidence, ov.CONF_ANCHOR_SCALED)


class TestOrderValueDataclass(unittest.TestCase):
    def test_crore_none_when_rupees_none(self):
        self.assertIsNone(ov.OrderValue(None, ov.CONF_NONE).crore)

    def test_only_anchored_tiers_are_trustworthy(self):
        for conf in (ov.CONF_ANCHOR_SCALED, ov.CONF_ANCHOR_BARE):
            self.assertTrue(ov.OrderValue(1e8, conf).trustworthy)
        for conf in (ov.CONF_LOOSE, ov.CONF_WITHHELD, ov.CONF_FOREIGN, ov.CONF_NONE):
            self.assertFalse(ov.OrderValue(1e8, conf).trustworthy)


class TestForeignCurrencyRegressions(unittest.TestCase):
    """Three defects found by measuring the parser's output over 964 real PDFs.

    None of them raised, and none were visible from the test suite: each one
    silently produced a confident-looking wrong answer, which is why they were
    only ever going to be caught by looking at what the code actually returned.
    """

    def test_the_issuers_own_inr_conversion_is_kept(self):
        """WELCORP states both currencies; the rupee value was being discarded.

        The foreign step searched the whole document and returned with
        rupees=None before the rupee fallback ran, throwing away a figure the
        company had supplied two characters from the match.
        """
        text = ("Welspun Corp Wins Largest-Ever Order for HFIW Pipes, Valued "
                "at approx. USD 412.5 Million (~ Rs 4,000 Crore), to be "
                "Supplied from its USA Manufacturing Facility")
        r = ov.parse_order_value(text)
        self.assertIsNotNone(r.rupees, "the stated rupee value was dropped")
        self.assertAlmostEqual(r.crore, 4_000.0)
        self.assertFalse(r.trustworthy,
                         "unanchored: the issuer's number, but not a filed "
                         "answer to the mandated field")

    def test_a_bare_dollar_figure_is_not_a_foreign_reading(self):
        """33 of 191 foreign readings matched '$100', '$5', '$1'.

        The scale word was optional, so a page artefact counted as a currency
        quote -- and because a foreign reading pre-empted the rupee fallback,
        each one suppressed that document's INR figure for nothing.
        """
        r = ov.parse_order_value("Page $100 of the annexure. Orders worth "
                                 "Rs. 250 crore were received.")
        self.assertEqual(r.confidence, ov.CONF_LOOSE)
        self.assertAlmostEqual(r.crore, 250.0)

    def test_a_rupee_figure_outranks_a_bare_foreign_quote(self):
        """Market-size boilerplate was hiding real rupee figures.

        'USD 30 billion' (21 documents) and 'USD 32 billion' (17) are global
        market-size sentences. Matching one returned foreign-currency for the
        whole filing, so any rupee amount in it was never read.
        """
        text = ("The global market is estimated at USD 30 billion. The Company "
                "has received orders worth Rs. 1,200 crore.")
        r = ov.parse_order_value(text)
        self.assertAlmostEqual(r.crore, 1_200.0)

    def test_a_foreign_quote_alone_still_reports_foreign(self):
        """The reordering must not cost the signal where it is the only one."""
        r = ov.parse_order_value("Contract awarded, valued at USD 50 million.")
        self.assertEqual(r.confidence, ov.CONF_FOREIGN)
        self.assertEqual(r.currency, "USD")
        self.assertIsNone(r.rupees, "no FX rate should ever be applied")


class TestUnanchoredRequiresARupeeMarker(unittest.TestCase):
    """A scale word alone does not make a number rupees."""

    def test_a_bare_scaled_number_is_not_read_as_rupees(self):
        """ADANIPORTS got a Rs 100 cr 'order' from a bare '1 billion'.

        With no label and no currency marker, a scaled number in a filing is as
        likely to be USD, a share count or a tonnage as it is to be rupees.
        """
        r = ov.parse_order_value(
            "Execution capacity of 183 Million units across 1 billion sq ft.")
        self.assertIsNone(r.rupees)
        self.assertEqual(r.confidence, ov.CONF_NONE)

    def test_the_anchored_path_still_accepts_a_bare_scaled_number(self):
        """The asymmetry is the point: the mandated field is headed '(in INR)',
        so the label vouches for the unit where nothing else would."""
        r = ov.parse_order_value(
            "Broad consideration or size of the order(s)/contract(s): 5,482 crores")
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 5_482.0)


if __name__ == "__main__":
    unittest.main()
