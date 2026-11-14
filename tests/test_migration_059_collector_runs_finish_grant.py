"""Static checks for migration 059 (collector_runs finish grant) and its down file."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "db" / "migrations" / "059_collector_runs_finish_grant.sql"
DOWN = ROOT / "db" / "migrations" / "down" / "059_collector_runs_finish_grant.down.sql"
ROLE = "market_scanner_server"
TABLE = "collector_runs"
COLUMNS = ("status", "finished_at", "message")

GRANT_RE = re.compile(
    r"^GRANT\s+UPDATE\s*\((.+?)\)\s+ON\s+(\S+)\s+TO\s+(\S+)$",
    re.IGNORECASE,
)
REVOKE_RE = re.compile(
    r"^REVOKE\s+UPDATE\s*\((.+?)\)\s+ON\s+(\S+)\s+FROM\s+(\S+)$",
    re.IGNORECASE,
)
SECRET_WORDS = ("PASSWORD", "SECRET", "TOKEN", "CREATE ROLE", "ALTER ROLE")


def _code_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("--")]


def _statements(path):
    text = "\n".join(_code_lines(path))
    return [s.strip() for s in text.split(";") if s.strip()]


def _column_triples(statements, regex):
    """Return the set of (column, table, role) each statement covers."""
    triples = set()
    for stmt in statements:
        m = regex.match(stmt)
        if not m:
            raise AssertionError(f"unparseable statement: {stmt!r}")
        for col in m.group(1).split(","):
            triples.add((col.strip().lower(), m.group(2).lower(), m.group(3)))
    return triples


class Migration059Tests(unittest.TestCase):
    def test_up_grants_exactly_the_three_columns(self):
        expected = {(col, TABLE, ROLE) for col in COLUMNS}
        self.assertEqual(_column_triples(_statements(UP), GRANT_RE), expected)

    def test_up_is_one_statement(self):
        stmts = _statements(UP)
        self.assertEqual(len(stmts), 1)
        self.assertTrue(stmts[0].upper().startswith("GRANT UPDATE"), stmts[0])

    def test_up_has_no_other_privileges(self):
        code = "\n".join(_code_lines(UP)).upper()
        for priv in ("INSERT", "DELETE", "ALL PRIVILEGES", "SEQUENCE", "SELECT", "TRUNCATE"):
            self.assertNotIn(priv, code)

    def test_up_has_no_role_or_password_statements(self):
        code = "\n".join(_code_lines(UP)).upper()
        for word in SECRET_WORDS:
            self.assertNotIn(word, code)

    def test_down_revokes_exactly_the_same_columns(self):
        stmts = _statements(DOWN)
        self.assertEqual(len(stmts), 1)
        self.assertEqual(
            _column_triples(stmts, REVOKE_RE),
            _column_triples(_statements(UP), GRANT_RE),
        )

    def test_down_mirrors_up(self):
        up = _column_triples(_statements(UP), GRANT_RE)
        down = _column_triples(_statements(DOWN), REVOKE_RE)
        self.assertEqual(up, down)

    def test_down_has_no_secret_words(self):
        code = "\n".join(_code_lines(DOWN)).upper()
        for word in SECRET_WORDS:
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
