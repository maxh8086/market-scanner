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
            "The Company has secured orders totalling Rs. 4,000 crore."
        )
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_LOOSE)
        self.assertFalse(r.trustworthy, "a loose parse must never read as filed")

    def test_the_worth_label_rescues_the_welcorp_sentence(self):
        """`worth` is a label, so the same text parses correctly.

        This is the payoff for admitting the variant: the market-size figure
        stops winning, because the Company's own `orders worth` phrase anchors
        the smaller, correct number. 9 of 222 measured order filings label the
        value this way and no other.
        """
        text = (
            "The global line pipe market is estimated at Rs. 45,000 crore. "
            "The Company has secured orders worth Rs. 4,000 crore."
        )
        r = ov.parse_order_value(text)
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 4000.0)

    def test_net_worth_is_not_an_order_value(self):
        """`worth` must not anchor on a balance-sheet figure.

        PIRAMALFIN's Rs 109,542 cr came from a post-merger net worth in an NCLT
        appeal. Admitting `worth` as a label would re-create that misread at the
        *trusted* tier, which is worse than the original, so the lookbehind
        excludes it. It may still surface as `loose`, which nothing ranks on.
        """
        r = ov.parse_order_value(
            "The post-merger net worth of Rs. 109,542 crore per the scheme.")
        self.assertNotEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertFalse(r.trustworthy)

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
        self.assertNotEqual(r.confidence, ov.CONF_FOREIGN)
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


class TestUnquantifiedAnswers(unittest.TestCase):
    """The label is present and its answer holds no rupee figure.

    56 of 222 measured order filings. These used to fall through to the
    largest-figure fallback, which answers a question the company declined to
    answer numerically -- the single most harmful thing this parser can do,
    because a fabricated number looks like data and `none` does not.
    """

    def test_a_capacity_answer_is_unquantified_not_a_rupee_figure(self):
        """ACMESOLAR answers in MW, and the page has rupee figures elsewhere."""
        r = ov.parse_order_value(
            "Broad consideration or size of the order(s)/contract(s); Size of "
            "the project - 190 MW ISTS connected wind solar project. "
            "8. Whether the promoter group has any interest. No. "
            "Paid up capital Rs. 500 crore.")
        self.assertEqual(r.confidence, ov.CONF_UNQUANTIFIED)
        self.assertIsNone(r.rupees)
        self.assertFalse(r.trustworthy)

    def test_a_declined_answer_does_not_borrow_a_number_from_elsewhere(self):
        """JSWINFRA said Not Applicable and was reported a GST demand."""
        for answer in ("Not applicable.", "Not ascertainable at this stage.",
                       "To be determined."):
            with self.subTest(answer=answer):
                r = ov.parse_order_value(
                    f"Size of the order(s)/contract(s); {answer} "
                    "8. Whether the promoter has any interest. No. "
                    "Total debt outstanding Rs 100 crore.")
                self.assertEqual(r.confidence, ov.CONF_UNQUANTIFIED)
                self.assertIsNone(r.rupees)

    def test_a_tariff_is_not_an_order_value(self):
        """Per-unit prices are below MIN_RUPEES, but say so explicitly."""
        r = ov.parse_order_value(
            "Order value: the applicable tariff is Rs. 4.35 per unit for the "
            "entire term. 8. Whether the promoter has any interest.")
        self.assertEqual(r.confidence, ov.CONF_UNQUANTIFIED)

    def test_the_label_winning_means_the_document_is_not_rescanned(self):
        """Once the field is found, its answer is the answer.

        The old code fell back to the whole document, so a filing that stated
        "no value" still reported the biggest number on the page.
        """
        r = ov.parse_order_value(
            "Order value: Not applicable. 9. Other details. "
            "The Company's annual revenue was Rs. 8,000 crore.")
        self.assertEqual(r.confidence, ov.CONF_UNQUANTIFIED)
        self.assertIsNone(r.rupees)

    def test_an_unlabelled_document_is_still_loose_not_unquantified(self):
        """`unquantified` claims the field was found; it must not lie."""
        r = ov.parse_order_value(
            "The Company's annual revenue was Rs. 8,000 crore.")
        self.assertEqual(r.confidence, ov.CONF_LOOSE)


class TestAnchoredForeignConversion(unittest.TestCase):
    """A foreign figure answered with the issuer's own INR conversion.

    Inside the mandated field this is as good as a direct rupee answer -- the
    company supplied both numbers in the field SEBI mandates -- so it earns the
    anchored tier, not `loose`. Before this, the anchored path returned a
    foreign reading with rupees=None and discarded the conversion.
    """

    def test_mtartech_style_conversion_is_trusted(self):
        r = ov.parse_order_value(
            "Broad consideration or size of the order(s)/contract(s); orders "
            "worth USD 85.86 million (approximately Rs. 819.94 crores)")
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 819.94)
        self.assertTrue(r.trustworthy)

    def test_a_foreign_figure_without_a_conversion_stays_foreign(self):
        r = ov.parse_order_value(
            "Broad consideration or size of the order(s)/contract(s); "
            "~USD 54.81 million over the tenure.")
        self.assertEqual(r.confidence, ov.CONF_FOREIGN)
        self.assertIsNone(r.rupees)
        self.assertEqual(r.currency, "USD")

    def test_the_conversion_must_sit_beside_the_foreign_figure(self):
        """A rupee number further down the page is not a conversion of it."""
        r = ov.parse_order_value(
            "Order value: USD 50 million. 9. Unrelated. Some other paragraph "
            "entirely, mentioning Rs. 9,999 crore of borrowings.")
        self.assertNotEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertIsNone(r.rupees)


class TestNextFieldBoundary(unittest.TestCase):
    """The mandated answer ends where the next mandated field begins.

    A flat 240-char window read into the following field, so a paid-up capital
    or total-debt figure could be returned wearing the anchored tier -- the
    `loose` fabrication with false confidence, which is worse. Measured over the
    81 anchored order filings, cutting at `whether` or an enumerated marker
    discarded no figure that was being read correctly.
    """

    def test_a_figure_after_the_next_field_is_not_the_answer(self):
        r = ov.parse_order_value(
            "Order value: Not disclosed by mutual agreement is not claimed. "
            "Whether the promoter group has any interest? Rs. 700 crore.")
        self.assertIsNone(r.rupees)

    def test_an_enumerated_marker_also_ends_the_answer(self):
        r = ov.parse_order_value(
            "Contract value: Not applicable. (9) Details of the counterparty "
            "and consideration of Rs. 640 crore.")
        self.assertEqual(r.confidence, ov.CONF_UNQUANTIFIED)

    def test_prose_before_the_figure_is_still_inside_the_answer(self):
        """Cutting must not be so eager that it loses a real answer."""
        r = ov.parse_order_value(
            "Broad consideration or size of the order(s)/contract(s); "
            "Rs. 2205.23 Crores inclusive of all applicable taxes and GST "
            "h Whether promoter group has any interest")
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 2205.23)


class TestCumulativeIsNotOneOrder(unittest.TestCase):
    """A running total is real data but not a single win.

    Admitting `worth` as a label re-created, at the *trusted* tier, the exact
    misread the confidence gate had just removed -- KPIL's year-to-date inflow
    ranked as one order at 56% of market cap. These tests exist because a
    widened pattern needs a guard measured on the same corpus; the suite passed
    without them.
    """

    def test_year_to_date_inflow_is_not_a_single_order(self):
        r = ov.parse_order_value(
            "We have secured orders worth Rs 13,219 crore so far in the "
            "current fiscal year (YTD FY27).")
        self.assertEqual(r.confidence, ov.CONF_CUMULATIVE)
        self.assertFalse(r.trustworthy)
        self.assertAlmostEqual(r.crore, 13219.0,
                               msg="the figure is kept; only the tier changes")

    def test_framing_before_the_label_still_counts(self):
        """"our order book stands at orders worth X" -- the giveaway precedes
        the number, so a window starting at the label cannot see it."""
        r = ov.parse_order_value(
            "Our consolidated order book stands at orders worth Rs 26,000 "
            "crore as of quarter end.")
        self.assertEqual(r.confidence, ov.CONF_CUMULATIVE)

    def test_period_aggregates_in_their_usual_phrasings(self):
        for framing in (
            "Total order inflow during the quarter comprised orders worth "
            "Rs 5,400 crore.",
            "Orders worth Rs 5,400 crore received till date.",
            "Cumulative orders worth Rs 5,400 crore.",
            "Unexecuted orders worth Rs 5,400 crore remain.",
        ):
            with self.subTest(framing=framing[:40]):
                self.assertEqual(ov.parse_order_value(framing).confidence,
                                 ov.CONF_CUMULATIVE)

    def test_a_single_order_is_untouched(self):
        r = ov.parse_order_value("MIDHANI has secured an order worth Rs. 158 Cr.")
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertTrue(r.trustworthy)

    def test_several_orders_in_one_announcement_are_still_one_event(self):
        """Two orders from one counterparty announced together is the event the
        scan is looking for, not a running total."""
        r = ov.parse_order_value(
            "Atlanta Electricals received two orders from GETCO worth "
            "Rs 297.71 crores on the same day. The orders comprise 25 "
            "transformers.")
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)

    def test_a_delivery_timeline_is_not_a_period_aggregate(self):
        """"to be executed in FY27" dates the work, not the total."""
        r = ov.parse_order_value(
            "Broad consideration or size of the order(s)/contract(s); "
            "Rs. 640 crore, to be executed in FY27. 8. Whether the promoter")
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)
        self.assertAlmostEqual(r.crore, 640.0)


class TestClassificationLegend(unittest.TestCase):
    """A definition of a size bucket is not a disclosure of a value.

    KPIL footnotes its own tiers -- "*Order Classification: Major indicates an
    order value estimated over Rs 4,000 crore" -- and that threshold ranked third
    in the report at 17% of market cap. Found by reading the source text behind
    the ranked rows, not by the suite, which is why these tests exist.
    """

    def test_a_bucket_threshold_is_not_the_order_value(self):
        r = ov.parse_order_value(
            "This win stands as a testament to our expertise. *Order "
            "Classification: Major indicates an order value estimated over "
            "₹4,000 crore About Kalpataru Projects International Limited")
        self.assertEqual(r.confidence, ov.CONF_UNQUANTIFIED)
        self.assertIsNone(r.rupees)

    def test_a_banded_definition_is_also_not_a_value(self):
        r = ov.parse_order_value(
            "Classification: Large denotes an order value between Rs. 1,000 "
            "crore and Rs. 4,000 crore.")
        self.assertEqual(r.confidence, ov.CONF_UNQUANTIFIED)

    def test_classification_alongside_a_real_figure_keeps_it(self):
        """The word `classification` is not itself the problem -- a definition
        verb followed by a bound is."""
        r = ov.parse_order_value(
            "Order Classification: Major. Order value of Rs. 500 crore "
            "received from NHAI.")
        self.assertAlmostEqual(r.crore, 500.0)
        self.assertEqual(r.confidence, ov.CONF_ANCHOR_SCALED)

    def test_a_bound_can_itself_be_the_disclosure(self):
        """"an order worth over Rs 500 crore" is the company disclosing a floor
        for this order, not defining a category. No definition verb, so the
        figure stands."""
        r = ov.parse_order_value(
            "The Company has received an order worth over Rs. 500 crore "
            "from NHAI.")
        self.assertAlmostEqual(r.crore, 500.0)


if __name__ == "__main__":
    unittest.main()
