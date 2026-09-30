"""Postgres returns NUMERIC as Decimal; the scanner does float arithmetic on candles and ATH values."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from scanner.marketdata import postgres_backend as pb


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    """Answers the two SELECTs the read path issues, with Decimal values like psycopg."""

    def execute(self, sql, params=()):
        if "FROM candles" in sql:
            return _Result([
                {"date": date(2026, 9, 1), "open": Decimal("10.5"), "high": Decimal("12.25"),
                 "low": Decimal("10.0"), "close": Decimal("11.75"), "volume": 1000},
                {"date": date(2026, 9, 2), "open": None, "high": Decimal("13"),
                 "low": Decimal("11"), "close": Decimal("12"), "volume": 900},
            ])
        return _Result([{"ath_high": Decimal("13"), "ath_date": date(2026, 9, 2),
                         "ath_close": Decimal("12"), "first_date": date(2026, 9, 1),
                         "last_date": date(2026, 9, 2)}])


class PostgresDecimalTests(unittest.TestCase):
    def test_candles_are_floats(self):
        df = pb._load_cached_candles_pg(_Conn(), "X")
        for col in ("open", "high", "low", "close"):
            self.assertTrue(all(isinstance(v, float) for v in df[col]), col)
        self.assertEqual(df["high"].max() - 12.0, 1.0)  # float arithmetic works

    def test_to_float(self):
        self.assertIsNone(pb._to_float(None))
        self.assertIsInstance(pb._to_float(Decimal("1.5")), float)

    def test_distance_pct_accepts_loaded_values(self):
        from scanner.ath import distance_pct
        df = pb._load_cached_candles_pg(_Conn(), "X")
        ath = pb._to_float(Decimal("13"))
        self.assertAlmostEqual(distance_pct(ath, float(df["close"].iloc[-1])), 7.6923, places=3)


if __name__ == "__main__":
    unittest.main()
