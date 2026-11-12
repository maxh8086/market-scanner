"""Offline tests for scanner/relative_strength.py. No database or network is contacted."""
from __future__ import annotations

import datetime as dt
import unittest
from decimal import Decimal
from unittest import mock

from scanner import relative_strength as rs

AS_OF = dt.date(2026, 11, 6)
TARGET = dt.date(2026, 8, 6)  # AS_OF minus 3 calendar months


class MonthsBeforeTests(unittest.TestCase):
    def test_three_months_back_keeps_day(self):
        self.assertEqual(rs.months_before(AS_OF, 3), dt.date(2026, 8, 6))

    def test_day_clamped_to_end_of_shorter_month(self):
        self.assertEqual(rs.months_before(dt.date(2026, 5, 31), 3), dt.date(2026, 2, 28))

    def test_crosses_year_boundary(self):
        self.assertEqual(rs.months_before(dt.date(2026, 2, 15), 3), dt.date(2025, 11, 15))


class WindowCloseTests(unittest.TestCase):
    def test_exact_3_month_baseline_is_used(self):
        self.assertEqual(rs.window_close((TARGET, 100), TARGET), Decimal("100"))

    def test_baseline_exactly_7_days_old_is_used(self):
        found = (TARGET - dt.timedelta(days=7), 100)
        self.assertEqual(rs.window_close(found, TARGET), Decimal("100"))

    def test_baseline_8_days_old_gives_none(self):
        found = (TARGET - dt.timedelta(days=8), 100)
        self.assertIsNone(rs.window_close(found, TARGET))

    def test_no_candle_gives_none(self):
        self.assertIsNone(rs.window_close(None, TARGET))

    def test_null_close_gives_none(self):
        self.assertIsNone(rs.window_close((TARGET, None), TARGET))


class PctReturnTests(unittest.TestCase):
    def test_return_is_percent(self):
        self.assertEqual(rs.pct_return(Decimal("150"), Decimal("100")), Decimal("50"))

    def test_zero_base_gives_none(self):
        self.assertIsNone(rs.pct_return(Decimal("150"), Decimal("0")))

    def test_missing_side_gives_none(self):
        self.assertIsNone(rs.pct_return(None, Decimal("100")))
        self.assertIsNone(rs.pct_return(Decimal("100"), None))

    def test_rs_gap_is_difference_and_none_when_either_missing(self):
        self.assertEqual(rs.rs_gap(Decimal("50"), Decimal("20")), Decimal("30"))
        self.assertIsNone(rs.rs_gap(None, Decimal("20")))
        self.assertIsNone(rs.rs_gap(Decimal("50"), None))


class AssignTiersTests(unittest.TestCase):
    def _tier_of(self, assignments, isin):
        found = [a for a in assignments if a.isin == isin]
        return (found[0].tier, found[0].index_name, found[0].symbol) if found else None

    def test_bank_isin_takes_bank_tier_even_when_in_nifty_50(self):
        members = {
            "NIFTY 50": {"INE_BANK": "HDFCBANK"},
            "NIFTY BANK": {"INE_BANK": "HDFCBANK"},
        }
        self.assertEqual(self._tier_of(rs.assign_tiers(members), "INE_BANK"),
                         ("Bank", "NIFTY BANK", "HDFCBANK"))

    def test_bank_isin_outside_the_five_tiers_still_gets_bank(self):
        members = {"NIFTY BANK": {"INE_X": "XBANK"}}
        self.assertEqual(self._tier_of(rs.assign_tiers(members), "INE_X"),
                         ("Bank", "NIFTY BANK", "XBANK"))

    def test_highest_priority_index_wins(self):
        members = {
            "NIFTY NEXT 50": {"INE_A": "ALPHA"},
            "NIFTY MIDCAP 150": {"INE_A": "ALPHA"},
        }
        self.assertEqual(self._tier_of(rs.assign_tiers(members), "INE_A"),
                         ("NIFTY NEXT 50", "NIFTY NEXT 50", "ALPHA"))

    def test_nifty_50_beats_next_50(self):
        members = {
            "NIFTY 50": {"INE_A": "ALPHA"},
            "NIFTY NEXT 50": {"INE_A": "ALPHA"},
        }
        self.assertEqual(self._tier_of(rs.assign_tiers(members), "INE_A"),
                         ("NIFTY 50", "NIFTY 50", "ALPHA"))

    def test_microcap_only_stock_gets_microcap_tier(self):
        members = {"NIFTY MICROCAP 250": {"INE_M": "MICRO"}}
        self.assertEqual(self._tier_of(rs.assign_tiers(members), "INE_M"),
                         ("NIFTY MICROCAP 250", "NIFTY MICROCAP 250", "MICRO"))

    def test_stock_in_no_index_gets_no_row(self):
        members = {"NIFTY 50": {"INE_A": "ALPHA"}}
        self.assertIsNone(self._tier_of(rs.assign_tiers(members), "INE_NONE"))

    def test_symbol_falls_back_to_other_index_when_chosen_row_has_none(self):
        members = {
            "NIFTY 50": {"INE_A": None},
            "NIFTY NEXT 50": {"INE_A": "ALPHA"},
        }
        self.assertEqual(self._tier_of(rs.assign_tiers(members), "INE_A"),
                         ("NIFTY 50", "NIFTY 50", "ALPHA"))


class FakeConn:
    """Stands in for a psycopg connection. Records every statement and write."""

    def __init__(self):
        self.executed = []
        self.cursor_obj = mock.MagicMock()

    def cursor(self):
        cm = mock.MagicMock()
        cm.__enter__.return_value = self.cursor_obj
        cm.__exit__.return_value = False
        return cm


def _closes_for(prices):
    """Fake _latest_closes: returns the (date, close) for each symbol, shifted by date."""
    def fake(conn, symbols, on_or_before):
        return {s: (on_or_before, prices[s]) for s in symbols if s in prices}
    return fake


class MainTests(unittest.TestCase):
    def _members(self):
        return {
            "NIFTY 50": {"INE_A": "ALPHA"},
            "NIFTY BANK": {"INE_B": "BETA"},
        }

    def _patches(self, anchor, members, prices):
        conn = mock.MagicMock()
        ctx = mock.MagicMock()
        ctx.__enter__.return_value = conn
        ctx.__exit__.return_value = False
        return [
            mock.patch.object(rs, "connect", return_value=ctx),
            mock.patch.object(rs, "_anchor_date", return_value=anchor),
            mock.patch.object(rs, "_latest_membership", return_value=members),
            mock.patch.object(rs, "_latest_closes", side_effect=_closes_for(prices)),
        ], conn

    def _run(self, argv, anchor, members, prices):
        patches, conn = self._patches(anchor, members, prices)
        for p in patches:
            p.start()
        self.addCleanup(mock.patch.stopall)
        with mock.patch.object(rs, "write_rows", return_value=0) as write:
            code = rs.main(argv)
        return code, write, conn

    def test_dry_run_writes_nothing(self):
        prices = {"ALPHA": 200, "BETA": 300, "IDX:NIFTY 50": 100, "IDX:NIFTY BANK": 100}
        code, write, _ = self._run(["--dry-run"], AS_OF, self._members(), prices)
        self.assertEqual(code, 0)
        write.assert_not_called()

    def test_dry_run_prints_anchor_and_tier_counts(self):
        prices = {"ALPHA": 200, "BETA": 300, "IDX:NIFTY 50": 100, "IDX:NIFTY BANK": 100}
        with mock.patch("builtins.print") as printer:
            code, _, _ = self._run(["--dry-run"], AS_OF, self._members(), prices)
        self.assertEqual(code, 0)
        output = " ".join(str(c.args[0]) for c in printer.call_args_list)
        self.assertIn("2026-11-06", output)
        self.assertIn("Bank: 1", output)
        self.assertIn("NIFTY 50: 1", output)

    def test_missing_anchor_returns_1(self):
        code, write, _ = self._run([], None, self._members(), {})
        self.assertEqual(code, 1)
        write.assert_not_called()

    def test_no_membership_returns_1(self):
        code, write, _ = self._run([], AS_OF, {}, {})
        self.assertEqual(code, 1)
        write.assert_not_called()

    def test_missing_returns_are_written_as_none(self):
        # No candle exists on the 365-day baseline for any symbol, so both returns are missing.
        members = {"NIFTY 50": {"INE_A": "ALPHA"}}
        prices = {"IDX:NIFTY 50": 100, "ALPHA": 200}
        patches, conn = self._patches(AS_OF, members, prices)
        for p in patches:
            p.start()
        self.addCleanup(mock.patch.stopall)
        real = rs._latest_closes

        def only_as_of(conn_, symbols, on_or_before):
            if on_or_before == TARGET:
                return {}
            return real(conn_, symbols, on_or_before)

        with mock.patch.object(rs, "_latest_closes", side_effect=only_as_of), \
                mock.patch.object(rs, "write_rows", return_value=1) as write:
            code = rs.main([])
        self.assertEqual(code, 0)
        rows = write.call_args[0][1]
        self.assertEqual(len(rows), 1)
        symbol, as_of, stock_ret, index_name, index_ret, gap, tier = rows[0]
        self.assertEqual(symbol, "ALPHA")
        self.assertIsNone(stock_ret)
        self.assertIsNone(index_ret)
        self.assertIsNone(gap)
        self.assertEqual(tier, "NIFTY 50")
        self.assertEqual(index_name, "NIFTY 50")


class WriteRowsTests(unittest.TestCase):
    def test_upsert_keys_on_symbol_and_as_of_and_updates_all_columns(self):
        conn = FakeConn()
        rows = [("ALPHA", AS_OF, None, "NIFTY 50", Decimal("10"), None, "NIFTY 50")]
        self.assertEqual(rs.write_rows(conn, rows), 1)
        sql, params = conn.cursor_obj.executemany.call_args[0]
        self.assertIn("ON CONFLICT (symbol, as_of) DO UPDATE SET", sql)
        for col in ("stock_return_3m", "index_name", "index_return_3m", "rs_gap_pct", "tier"):
            self.assertIn(f"{col} = EXCLUDED.{col}", sql)
        self.assertNotIn("DELETE", sql.upper())
        self.assertEqual(params, rows)


if __name__ == "__main__":
    unittest.main()
