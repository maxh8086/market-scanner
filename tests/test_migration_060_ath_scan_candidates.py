"""Static checks for migration 060 (ath_scan_candidates) and its down file.

The column list is parsed from the SQL and compared with the CSV output columns of scanner/report.py
and the type sets of scanner/ath_scan_store.py, so the table and the CSV cannot drift apart.
"""

import re
import unittest
from pathlib import Path

from scanner import ath_scan_store, report

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "db" / "migrations" / "060_ath_scan_candidates.sql"
DOWN = ROOT / "db" / "migrations" / "down" / "060_ath_scan_candidates.down.sql"
TABLE = "ath_scan_candidates"
META_COLUMNS = ("scan_date", "run_id", "created_at")
SECRET_WORDS = ("PASSWORD", "SECRET", "TOKEN", "CREATE ROLE", "ALTER ROLE", "GRANT")


def _code_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("--")]


def _table_body(text):
    """The text between the CREATE TABLE parenthesis and its closing ');', comments removed."""
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("--"))
    m = re.search(r"CREATE TABLE IF NOT EXISTS\s+" + TABLE + r"\s*\((.*)\);", code, re.DOTALL)
    if not m:
        raise AssertionError("no CREATE TABLE ath_scan_candidates statement")
    return m.group(1)


def _columns(path):
    """{name: definition} for each column line; the PRIMARY KEY constraint line is skipped."""
    columns = {}
    for raw in _table_body(path.read_text(encoding="utf-8")).splitlines():
        line = raw.strip().rstrip(",").strip()
        if not line or line.upper().startswith("PRIMARY KEY"):
            continue
        name, _, definition = line.partition(" ")
        columns[name] = " ".join(definition.split()).upper()
    return columns


def _csv_columns():
    return list(report.BASE_COLUMNS) + list(report.TREND_COLUMNS) + list(report.FACTOR_COLUMNS)


def _store_expected_columns():
    """The CSV columns with isin right after company: the table's data columns, in order."""
    cols = _csv_columns()
    cols.insert(cols.index("company") + 1, "isin")
    return cols


class Migration060Tests(unittest.TestCase):
    def setUp(self):
        self.text = UP.read_text(encoding="utf-8")
        self.columns = _columns(UP)

    def test_every_csv_column_is_in_the_table(self):
        missing = [c for c in _csv_columns() if c not in self.columns]
        self.assertEqual(missing, [])

    def test_table_has_only_csv_columns_plus_metadata(self):
        expected = set(_csv_columns()) | set(META_COLUMNS) | {"isin"}
        self.assertEqual(set(self.columns), expected)

    def test_table_has_isin_as_an_extra_text_column(self):
        self.assertEqual(self.columns["isin"], "TEXT NOT NULL DEFAULT ''")
        self.assertNotIn("isin", _csv_columns())  # the CSV drops it; the table keeps it

    def test_store_column_list_matches_csv_columns_plus_isin_in_order(self):
        self.assertEqual(ath_scan_store.ATH_SCAN_COLUMNS, _store_expected_columns())

    def test_store_type_sets_cover_every_column_once(self):
        typed = (list(ath_scan_store.NUMERIC_COLUMNS) + list(ath_scan_store.INTEGER_COLUMNS)
                 + list(ath_scan_store.TEXT_COLUMNS))
        self.assertEqual(sorted(typed), sorted(_store_expected_columns()))

    def test_column_types_match_store(self):
        for col in ath_scan_store.NUMERIC_COLUMNS:
            self.assertEqual(self.columns[col], "DOUBLE PRECISION", col)
        for col in ath_scan_store.INTEGER_COLUMNS:
            self.assertEqual(self.columns[col], "INTEGER", col)
        for col in ath_scan_store.TEXT_COLUMNS:
            expected = "TEXT NOT NULL" if col == "symbol" else "TEXT NOT NULL DEFAULT ''"
            self.assertEqual(self.columns[col], expected, col)

    def test_text_columns_default_to_empty_string_not_null(self):
        for col in ("company", "industry", "ath_date", "bucket", "recent_ipo",
                    "above_ema50", "above_sma200", "trend", "bonus_issue", "demerger",
                    "orderbook_signal", "expansion_signal"):
            self.assertIn("NOT NULL DEFAULT ''", self.columns[col], col)

    def test_numeric_and_integer_columns_are_nullable(self):
        for col in ("ltp", "today_high", "ath_high", "ath_close", "distance_pct", "ema50",
                    "sma200", "days_since_ath", "listed_days", "factors_matched"):
            self.assertNotIn("NOT NULL", self.columns[col], col)

    def test_key_columns(self):
        self.assertEqual(self.columns["scan_date"], "DATE NOT NULL")
        self.assertEqual(self.columns["symbol"], "TEXT NOT NULL")
        self.assertEqual(self.columns["run_id"],
                         "UUID REFERENCES COLLECTOR_RUNS(ID) ON DELETE SET NULL")
        self.assertIn("TIMESTAMPTZ NOT NULL DEFAULT NOW()", self.columns["created_at"])

    def test_primary_key_is_scan_date_and_symbol(self):
        body = _table_body(self.text)
        self.assertRegex(" ".join(body.split()), r"PRIMARY KEY \(scan_date, symbol\)")

    def test_no_index_beyond_primary_key(self):
        code = "\n".join(_code_lines(UP)).upper()
        self.assertNotIn("CREATE INDEX", code)
        self.assertNotIn("UNIQUE", code)

    def test_no_grants_roles_or_secrets(self):
        code = "\n".join(_code_lines(UP)).upper()
        for word in SECRET_WORDS:
            self.assertNotIn(word, code)

    def test_up_creates_only_this_table(self):
        code = "\n".join(_code_lines(UP)).upper()
        self.assertEqual(len(re.findall(r"CREATE TABLE", code)), 1)
        self.assertNotIn("DROP ", code)

    def test_header_states_retention_and_rollback(self):
        self.assertIn("90 days", self.text)
        self.assertIn("060_ath_scan_candidates.down.sql", self.text)


class Migration060DownTests(unittest.TestCase):
    def test_down_drops_only_this_table(self):
        code = "\n".join(_code_lines(DOWN))
        drops = re.findall(r"DROP\s+TABLE\s+(IF EXISTS\s+)?(\w+)", code, re.IGNORECASE)
        self.assertEqual([name for _, name in drops], [TABLE])

    def test_down_has_no_grants_or_creates(self):
        code = "\n".join(_code_lines(DOWN)).upper()
        for word in ("GRANT", "REVOKE", "CREATE", "ALTER"):
            self.assertNotIn(word, code)

    def test_down_removes_its_ledger_row(self):
        code = "\n".join(_code_lines(DOWN))
        self.assertIn("DELETE FROM schema_migrations WHERE filename = '060_ath_scan_candidates.sql'", code)


if __name__ == "__main__":
    unittest.main()
