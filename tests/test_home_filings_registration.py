"""Migration 052 (home_filings registration): static checks, then Postgres checks in throwaway schemas.

The static tests run without Postgres. The Postgres tests skip when it is unreachable (a skip is not a pass).
Only throwaway schemas created by pgschema.create are written to.
"""
import re
import unittest
from pathlib import Path

from scanner.pg import db
import tests.pgschema as pgschema

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "db" / "migrations" / "052_home_filings_registration.sql"
DOWN = ROOT / "db" / "migrations" / "down" / "052_home_filings_registration.down.sql"

SOURCE = "home_filings"
MODE = "manual"
CRON = "*/5 8-20 * * 1-5"
DESTRUCTIVE_RE = re.compile(r"\b(DROP|DELETE|UPDATE|ALTER)\b", re.IGNORECASE)
SECRET_RE = re.compile(r"password|token|secret", re.IGNORECASE)


def _settings_row(conn=None):
    sql = ("SELECT source, mode, cron, params::jsonb AS params FROM collector_settings "
           "WHERE source = %s")
    if conn is not None:
        return conn.execute(sql, (SOURCE,)).fetchall()
    with db.connect() as c:
        return c.execute(sql, (SOURCE,)).fetchall()


def _source_rows(name=SOURCE):
    with db.connect() as c:
        return c.execute("SELECT source FROM collector_sources WHERE source = %s",
                         (name,)).fetchall()


class Migration052StaticTests(unittest.TestCase):
    def test_up_file_exists(self):
        self.assertTrue(UP.is_file(), UP)

    def test_down_file_exists(self):
        self.assertTrue(DOWN.is_file(), DOWN)

    def test_up_has_no_destructive_statements(self):
        text = UP.read_text(encoding="utf-8")
        self.assertIsNone(DESTRUCTIVE_RE.search(text), "up file must not DROP, DELETE, UPDATE or ALTER")

    def test_up_has_no_secret_words(self):
        text = UP.read_text(encoding="utf-8")
        self.assertIsNone(SECRET_RE.search(text))

    def test_up_registers_source_and_manual_settings_row(self):
        code = "\n".join(ln for ln in UP.read_text(encoding="utf-8").splitlines()
                         if ln.strip() and not ln.lstrip().startswith("--"))
        self.assertIn("INSERT INTO collector_sources (source) VALUES ('home_filings') "
                      "ON CONFLICT (source) DO NOTHING", code)
        self.assertIn("INSERT INTO collector_settings (source, mode, cron, params)", code)
        self.assertIn("('home_filings', 'manual', '*/5 8-20 * * 1-5', '{}')", code)
        self.assertEqual(code.count("ON CONFLICT (source) DO NOTHING"), 2)


class Migration052PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = pgschema.create(cls)  # raises SkipTest without Postgres

    def test_source_row_exists(self):
        self.assertEqual(len(_source_rows()), 1)

    def test_settings_row_is_manual_with_cron_and_empty_params(self):
        rows = _settings_row()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["mode"], MODE)
        self.assertEqual(row["cron"], CRON)
        self.assertEqual(row["params"], {})

    def test_rerunning_up_sql_is_a_noop(self):
        self.own_schema = pgschema.create(self)
        up_sql = UP.read_text(encoding="utf-8")
        before = _settings_row()
        with db.connect() as conn:
            conn.execute(up_sql)
            conn.commit()
        self.assertEqual(len(_source_rows()), 1)
        self.assertEqual(_settings_row(), before)
        self.assertEqual(len(before), 1)

    def test_changed_mode_and_cron_are_kept_on_rerun(self):
        self.own_schema = pgschema.create(self)
        with db.connect() as conn:
            conn.execute("UPDATE collector_settings SET mode = 'scheduled', cron = '7 9 * * 1-5' "
                         "WHERE source = %s", (SOURCE,))
            conn.commit()
        with db.connect() as conn:
            conn.execute(UP.read_text(encoding="utf-8"))
            conn.commit()
        rows = _settings_row()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mode"], "scheduled")
        self.assertEqual(rows[0]["cron"], "7 9 * * 1-5")

    def test_down_removes_home_filings_and_keeps_other_sources(self):
        self.own_schema = pgschema.create(self)
        self.assertEqual(len(_source_rows("candles_eod")), 1, "precondition: candles_eod seeded")
        self.assertEqual(len(_source_rows()), 1, "precondition: up applied")
        with db.connect() as conn:
            conn.execute(DOWN.read_text(encoding="utf-8"))
            conn.commit()
        self.assertEqual(_source_rows(), [])
        self.assertEqual(_settings_row(), [])
        self.assertEqual(len(_source_rows("candles_eod")), 1, "down must not touch other sources")
        with db.connect() as conn:
            other = conn.execute("SELECT source FROM collector_settings WHERE source = 'candles_eod'"
                                 ).fetchall()
        self.assertEqual(len(other), 1)


if __name__ == "__main__":
    unittest.main()
