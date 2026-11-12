"""Tests for scanner/fund_writer.py. Offline: synthetic Lines and a fake connection, no DB, no network."""
import unittest
from datetime import date

from scanner.fund_derive import Line
from scanner.fund_writer import (
    SECTIONS,
    SOURCES,
    BankNotSupported,
    _UPSERT,
    fund_line_rows,
    write_fund_lines,
)

# Guards against drift from the fund_line CHECK constraints in migration 027.
MIGRATION_SECTIONS = ("quarters", "profit_loss", "balance_sheet", "cash_flow", "ratios", "shareholding")
MIGRATION_SOURCES = ("screener", "nse")

MAR_2025 = date(2025, 3, 31)
SEP_2025 = date(2025, 9, 30)


def _line(section, period, label, value, canonical=None, period_end=None, raw=None):
    if raw is None:
        raw = "" if value is None else str(value)
    return Line(section=section, period=period, period_end=period_end, label=label,
                canonical=canonical, raw=raw, value=value)


class _FakeTx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.begun = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.conn.committed = exc_type is None
        return False


class _FakeConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.begun = False
        self.committed = False

    def transaction(self):
        return _FakeTx(self)

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))


BANK_LINES = [
    _line("balance_sheet", "Mar 2025", "Deposits", 500.0, canonical="deposits", period_end=MAR_2025),
    _line("balance_sheet", "Mar 2025", "Equity Capital", 100.0, canonical="equity_capital",
          period_end=MAR_2025),
]


class SectionAndSourceGuardTests(unittest.TestCase):
    def test_sections_match_migration_check(self):
        self.assertEqual(SECTIONS, MIGRATION_SECTIONS)

    def test_sources_match_migration_check(self):
        self.assertEqual(SOURCES, MIGRATION_SOURCES)


class RowShapeTests(unittest.TestCase):
    def test_quarters_line_produces_exact_tuple(self):
        line = _line("quarters", "Sep 2025", "Sales", 1234.0, canonical="sales",
                     period_end=SEP_2025, raw="1,234")
        rows = fund_line_rows("ABC", [line])
        self.assertEqual(rows, [("ABC", "quarters", "Sep 2025", SEP_2025, "Sales", "sales",
                                 1234.0, "1,234", "screener")])

    def test_each_of_six_sections_is_kept_in_order(self):
        lines = [
            _line("quarters", "Sep 2025", "Sales", 10.0, canonical="sales", period_end=SEP_2025),
            _line("profit_loss", "Mar 2025", "Net Profit", 20.0, canonical="net_profit",
                  period_end=MAR_2025),
            _line("profit_loss", "TTM", "Net Profit", 30.0, canonical="net_profit", period_end=None),
            _line("balance_sheet", "Mar 2025", "Borrowings", 40.0, canonical="borrowings",
                  period_end=MAR_2025),
            _line("cash_flow", "Mar 2025", "Cash from Operations", 50.0,
                  canonical="cfo", period_end=MAR_2025),
            _line("ratios", "Mar 2025", "ROE %", 60.0, canonical="roe", period_end=MAR_2025),
            _line("shareholding", "Sep 2025", "Promoters", 70.0, canonical="promoter_pct",
                  period_end=SEP_2025),
        ]
        rows = fund_line_rows("ABC", lines)
        self.assertEqual([r[1] for r in rows],
                         ["quarters", "profit_loss", "profit_loss", "balance_sheet",
                          "cash_flow", "ratios", "shareholding"])
        for row in rows:
            self.assertEqual(len(row), 9)
            self.assertEqual(row[0], "ABC")
            self.assertEqual(row[8], "screener")

    def test_ttm_line_keeps_null_period_end(self):
        line = _line("profit_loss", "TTM", "Net Profit", 30.0, canonical="net_profit", period_end=None)
        rows = fund_line_rows("ABC", [line])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "TTM")
        self.assertIsNone(rows[0][3])

    def test_source_is_passed_through(self):
        line = _line("quarters", "Sep 2025", "Sales", 1.0, canonical="sales", period_end=SEP_2025)
        rows = fund_line_rows("ABC", [line], source="nse")
        self.assertEqual(rows[0][8], "nse")

    def test_symbol_is_stripped_but_not_case_changed(self):
        line = _line("quarters", "Sep 2025", "Sales", 1.0, canonical="sales", period_end=SEP_2025)
        rows = fund_line_rows("  AbC ", [line])
        self.assertEqual(rows[0][0], "AbC")

    def test_label_is_not_modified(self):
        line = _line("quarters", "Sep 2025", "Sales (Rs. Cr)", 1.0, canonical="sales",
                     period_end=SEP_2025)
        rows = fund_line_rows("ABC", [line])
        self.assertEqual(rows[0][4], "Sales (Rs. Cr)")


class UnmappedAndBlankTests(unittest.TestCase):
    def test_unmapped_label_is_kept_with_null_canonical(self):
        line = _line("quarters", "Sep 2025", "Odd Custom Row", 5.0, canonical=None,
                     period_end=SEP_2025)
        rows = fund_line_rows("ABC", [line])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0][5])
        self.assertEqual(rows[0][4], "Odd Custom Row")

    def test_blank_cell_is_kept_with_null_value_and_empty_raw(self):
        line = _line("quarters", "Sep 2025", "Sales", None, canonical="sales",
                     period_end=SEP_2025, raw="")
        rows = fund_line_rows("ABC", [line])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0][6])
        self.assertEqual(rows[0][7], "")


class FilteringTests(unittest.TestCase):
    def test_section_outside_allowed_list_is_dropped(self):
        daily = Line(section="daily", period="2025-11-10", period_end=None, label="close",
                     canonical="close", raw="101.5", value=101.5)
        self.assertEqual(fund_line_rows("ABC", [daily]), [])

    def test_mixed_input_keeps_only_allowed_sections_in_input_order(self):
        daily = Line(section="daily", period="2025-11-10", period_end=None, label="close",
                     canonical="close", raw="101.5", value=101.5)
        first = _line("quarters", "Sep 2025", "Sales", 1.0, canonical="sales", period_end=SEP_2025)
        second = _line("ratios", "Mar 2025", "ROE %", 2.0, canonical="roe", period_end=MAR_2025)
        rows = fund_line_rows("ABC", [first, daily, second])
        self.assertEqual([r[1] for r in rows], ["quarters", "ratios"])


class BankRefusalTests(unittest.TestCase):
    def test_bank_input_raises_bank_not_supported_with_reason(self):
        with self.assertRaises(BankNotSupported) as ctx:
            fund_line_rows("HDFCBANK", BANK_LINES)
        self.assertIn("Deposits", str(ctx.exception))

    def test_bank_not_supported_is_a_value_error(self):
        self.assertTrue(issubclass(BankNotSupported, ValueError))

    def test_write_with_bank_input_makes_no_db_calls(self):
        conn = _FakeConn()
        with self.assertRaises(BankNotSupported):
            write_fund_lines(conn, "HDFCBANK", BANK_LINES)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.line = _line("quarters", "Sep 2025", "Sales", 1.0, canonical="sales", period_end=SEP_2025)

    def test_bad_source_raises_value_error_naming_it(self):
        with self.assertRaises(ValueError) as ctx:
            fund_line_rows("ABC", [self.line], source="bse")
        self.assertIn("bse", str(ctx.exception))

    def test_empty_symbol_raises_value_error(self):
        with self.assertRaises(ValueError):
            fund_line_rows("", [self.line])

    def test_whitespace_symbol_raises_value_error(self):
        with self.assertRaises(ValueError):
            fund_line_rows("   ", [self.line])

    def test_write_with_bad_source_makes_no_db_calls(self):
        conn = _FakeConn()
        with self.assertRaises(ValueError):
            write_fund_lines(conn, "ABC", [self.line], source="bse")
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)


class DuplicateKeyTests(unittest.TestCase):
    def test_duplicate_section_period_label_keeps_last_value_in_one_row(self):
        first = _line("quarters", "Sep 2025", "Sales", 1.0, canonical="sales", period_end=SEP_2025)
        second = _line("quarters", "Sep 2025", "Sales", 2.0, canonical="sales", period_end=SEP_2025)
        rows = fund_line_rows("ABC", [first, second])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][6], 2.0)

    def test_duplicate_keeps_position_of_first_occurrence(self):
        first = _line("quarters", "Sep 2025", "Sales", 1.0, canonical="sales", period_end=SEP_2025)
        other = _line("quarters", "Mar 2025", "Other", 5.0, canonical=None, period_end=MAR_2025)
        dup = _line("quarters", "Sep 2025", "Sales", 2.0, canonical="sales", period_end=SEP_2025)
        rows = fund_line_rows("ABC", [first, other, dup])
        self.assertEqual([r[4] for r in rows], ["Sales", "Other"])
        self.assertEqual([r[6] for r in rows], [2.0, 5.0])

    def test_same_label_in_different_period_is_not_a_duplicate(self):
        sep = _line("quarters", "Sep 2025", "Sales", 1.0, canonical="sales", period_end=SEP_2025)
        mar = _line("quarters", "Mar 2025", "Sales", 2.0, canonical="sales", period_end=MAR_2025)
        rows = fund_line_rows("ABC", [sep, mar])
        self.assertEqual(len(rows), 2)


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.lines = [
            _line("quarters", "Sep 2025", "Sales", 1234.0, canonical="sales", period_end=SEP_2025,
                  raw="1,234"),
            _line("profit_loss", "TTM", "Net Profit", 30.0, canonical="net_profit", period_end=None),
        ]

    def test_one_upsert_per_row_inside_one_transaction(self):
        conn = _FakeConn()
        n = write_fund_lines(conn, "ABC", self.lines)
        self.assertEqual(n, 2)
        self.assertEqual(len(conn.calls), 2)
        self.assertTrue(conn.begun)
        self.assertTrue(conn.committed)

    def test_every_call_uses_upsert_constant_with_nine_params(self):
        conn = _FakeConn()
        write_fund_lines(conn, "ABC", self.lines)
        for sql, params in conn.calls:
            self.assertEqual(sql, _UPSERT)
            self.assertEqual(len(params), 9)
        self.assertEqual(conn.calls[0][1][0], "ABC")

    def test_upsert_sql_is_on_conflict_and_never_deletes(self):
        self.assertIn("ON CONFLICT", _UPSERT)
        self.assertNotIn("DELETE", _UPSERT.upper())
        self.assertEqual(_UPSERT.count("%s"), 9)

    def test_values_are_parameters_not_formatted_into_sql(self):
        tricky = _line("quarters", "Sep 2025", "Co's Sales 999", 4321.5, canonical="sales",
                       period_end=SEP_2025, raw="4,321.5")
        conn = _FakeConn()
        write_fund_lines(conn, "ABC", [tricky])
        sql, params = conn.calls[0]
        self.assertNotIn("Co's", sql)
        self.assertNotIn("4321.5", sql)
        self.assertIn("Co's Sales 999", params)
        self.assertIn(4321.5, params)


class EmptyAndDailyTests(unittest.TestCase):
    def test_empty_input_returns_empty_list(self):
        self.assertEqual(fund_line_rows("ABC", []), [])

    def test_write_empty_input_returns_zero_without_db_calls(self):
        conn = _FakeConn()
        self.assertEqual(write_fund_lines(conn, "ABC", []), 0)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)

    def test_only_daily_rows_write_nothing(self):
        daily = Line(section="daily", period="2025-11-10", period_end=None, label="close",
                     canonical="close", raw="101.5", value=101.5)
        conn = _FakeConn()
        self.assertEqual(write_fund_lines(conn, "ABC", [daily]), 0)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)

    def test_daily_is_not_a_known_section(self):
        self.assertNotIn("daily", SECTIONS)


if __name__ == "__main__":
    unittest.main()
