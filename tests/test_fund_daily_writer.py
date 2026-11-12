"""Tests for the fund_daily writer in scanner/fund_writer.py. Offline: synthetic Lines and a fake connection, no DB, no network."""
import unittest
from datetime import date
from pathlib import Path

from scanner.fund_derive import Line, daily_valuation
from scanner.fund_writer import (
    SOURCES,
    BankNotSupported,
    _UPSERT_DAILY,
    fund_daily_rows,
    write_fund_daily,
)

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "db" / "migrations" / "053_fund_daily.sql"

SEP_2025 = date(2025, 9, 30)
MAR_2025 = date(2025, 3, 31)
DAY1 = date(2025, 11, 10)
DAY2 = date(2025, 11, 11)


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

NON_BANK_LINES = [
    _line("quarters", "Sep 2025", "Sales", 1234.0, canonical="sales", period_end=SEP_2025),
]


def _daily(day, close, ttm_eps=None, pe=None):
    return {"date": day, "close": close, "ttm_eps": ttm_eps, "pe": pe}


class DailyRowShapeTests(unittest.TestCase):
    def test_daily_rows_map_to_tuples_in_order(self):
        rows = [_daily(DAY1, 101.5, 4.0, 25.375), _daily(DAY2, 102.0, 4.1, 24.878)]
        out = fund_daily_rows("ABC", rows)
        self.assertEqual(out, [
            ("ABC", DAY1, 101.5, 4.0, 25.375, "screener"),
            ("ABC", DAY2, 102.0, 4.1, 24.878, "screener"),
        ])

    def test_source_is_passed_through(self):
        out = fund_daily_rows("ABC", [_daily(DAY1, 1.0)], source="nse")
        self.assertEqual(out[0][5], "nse")

    def test_symbol_is_stripped_but_not_case_changed(self):
        out = fund_daily_rows("  AbC ", [_daily(DAY1, 1.0)])
        self.assertEqual(out[0][0], "AbC")

    def test_rows_without_date_are_skipped(self):
        rows = [
            {"close": 1.0, "ttm_eps": 1.0, "pe": 1.0},
            {"date": None, "close": 2.0, "ttm_eps": 2.0, "pe": 2.0},
            _daily(DAY1, 3.0, 3.0, 3.0),
        ]
        out = fund_daily_rows("ABC", rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], DAY1)

    def test_none_values_are_kept_as_none(self):
        out = fund_daily_rows("ABC", [_daily(DAY1, None, None, None)])
        self.assertEqual(out, [("ABC", DAY1, None, None, None, "screener")])

    def test_missing_optional_keys_default_to_none(self):
        out = fund_daily_rows("ABC", [{"date": DAY1, "close": 9.0}])
        self.assertEqual(out, [("ABC", DAY1, 9.0, None, None, "screener")])

    def test_duplicate_date_keeps_last_value_at_first_position(self):
        rows = [_daily(DAY1, 1.0), _daily(DAY2, 5.0), _daily(DAY1, 2.0)]
        out = fund_daily_rows("ABC", rows)
        self.assertEqual(len(out), 2)
        self.assertEqual([r[1] for r in out], [DAY1, DAY2])
        self.assertEqual(out[0][2], 2.0)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(fund_daily_rows("ABC", []), [])


class DailyValidationTests(unittest.TestCase):
    def test_empty_symbol_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            fund_daily_rows("", [_daily(DAY1, 1.0)])
        self.assertIn("symbol required", str(ctx.exception))

    def test_whitespace_symbol_raises_value_error(self):
        with self.assertRaises(ValueError):
            fund_daily_rows("   ", [_daily(DAY1, 1.0)])

    def test_bad_source_raises_value_error_naming_it(self):
        with self.assertRaises(ValueError) as ctx:
            fund_daily_rows("ABC", [_daily(DAY1, 1.0)], source="bse")
        self.assertIn("bse", str(ctx.exception))


class DailyWriteTests(unittest.TestCase):
    def setUp(self):
        self.rows = [_daily(DAY1, 101.5, 4.0, 25.375), _daily(DAY2, 102.0, None, None)]

    def test_one_call_per_row_inside_one_transaction(self):
        conn = _FakeConn()
        n = write_fund_daily(conn, "ABC", self.rows, lines=NON_BANK_LINES)
        self.assertEqual(n, 2)
        self.assertEqual(len(conn.calls), 2)
        self.assertTrue(conn.begun)
        self.assertTrue(conn.committed)
        for sql, _ in conn.calls:
            self.assertEqual(sql, _UPSERT_DAILY)
        self.assertEqual(conn.calls[0][1], ("ABC", DAY1, 101.5, 4.0, 25.375, "screener"))

    def test_lines_is_required_keyword_only(self):
        conn = _FakeConn()
        with self.assertRaises(TypeError):
            write_fund_daily(conn, "ABC", self.rows)
        self.assertEqual(conn.calls, [])

    def test_bank_lines_refused_with_zero_db_calls(self):
        conn = _FakeConn()
        with self.assertRaises(BankNotSupported) as ctx:
            write_fund_daily(conn, "HDFCBANK", self.rows, lines=BANK_LINES)
        self.assertIn("Deposits", str(ctx.exception))
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)

    def test_bank_check_runs_before_empty_filtering(self):
        conn = _FakeConn()
        with self.assertRaises(BankNotSupported):
            write_fund_daily(conn, "HDFCBANK", [], lines=BANK_LINES)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)

    def test_empty_rows_return_zero_without_transaction(self):
        conn = _FakeConn()
        self.assertEqual(write_fund_daily(conn, "ABC", [], lines=NON_BANK_LINES), 0)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)

    def test_bad_source_makes_no_db_calls(self):
        conn = _FakeConn()
        with self.assertRaises(ValueError):
            write_fund_daily(conn, "ABC", self.rows, source="bse", lines=NON_BANK_LINES)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)


class DailySqlTests(unittest.TestCase):
    def test_upsert_is_parameterised_on_conflict_and_never_deletes(self):
        self.assertIn("ON CONFLICT (symbol, day, source) DO UPDATE", _UPSERT_DAILY)
        self.assertEqual(_UPSERT_DAILY.count("%s"), 6)
        self.assertNotIn("DELETE", _UPSERT_DAILY.upper())

    def test_values_are_parameters_not_formatted_into_sql(self):
        tricky = [_daily(DAY1, 4321.5, 12.25, 99.5)]
        conn = _FakeConn()
        write_fund_daily(conn, "Co's 999", tricky, lines=NON_BANK_LINES)
        sql, params = conn.calls[0]
        self.assertNotIn("Co's", sql)
        self.assertNotIn("4321.5", sql)
        self.assertIn("Co's 999", params)
        self.assertIn(4321.5, params)


class MigrationDriftTests(unittest.TestCase):
    def test_migration_053_matches_writer_contract(self):
        text = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("PRIMARY KEY (symbol, day, source)", text)
        self.assertIn("'screener', 'nse'", text)
        self.assertIn("GRANT SELECT, INSERT, UPDATE ON fund_daily", text)
        self.assertNotIn("DELETE", text.upper())

    def test_sources_match_migration_check(self):
        self.assertEqual(SOURCES, ("screener", "nse"))


class DailyFundDeriveCompatibilityTests(unittest.TestCase):
    def test_daily_valuation_output_feeds_fund_daily_rows(self):
        closes = [(DAY1, 101.5), (DAY2, 102.0)]
        derived = daily_valuation(closes, NON_BANK_LINES)
        out = fund_daily_rows("ABC", derived)
        self.assertEqual(len(out), len(derived))
        self.assertEqual([r[1] for r in out], [d["date"] for d in derived])
        self.assertEqual([r[2] for r in out], [101.5, 102.0])


if __name__ == "__main__":
    unittest.main()
