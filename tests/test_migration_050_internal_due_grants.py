"""Static checks for migration 050 (internal due grants) and its down file."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "db" / "migrations" / "050_internal_due_grants.sql"
DOWN = ROOT / "db" / "migrations" / "down" / "050_internal_due_grants.down.sql"
ROLES = ("market_scanner_server", "market_scanner_app")
TABLES = ("collector_settings", "source_cooldown")

STMT_RE = re.compile(
    r"^(GRANT|REVOKE)\s+(.+?)\s+ON\s+(.+?)\s+(TO|FROM)\s+(" + "|".join(ROLES) + r")$",
    re.IGNORECASE,
)
SECRET_WORDS = ("PASSWORD", "SECRET", "TOKEN", "CREATE ROLE", "ALTER ROLE")


def _code_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("--")]


def _statements(path):
    text = "\n".join(_code_lines(path))
    return [s.strip() for s in text.split(";") if s.strip()]


def _triples(statements):
    """Return the set of (privilege, table, role) each statement covers."""
    triples = set()
    for stmt in statements:
        m = STMT_RE.match(stmt)
        if not m:
            raise AssertionError(f"unparseable statement: {stmt!r}")
        privs = [p.strip().upper() for p in m.group(2).split(",")]
        tables = [t.strip() for t in m.group(3).split(",")]
        for p in privs:
            for t in tables:
                triples.add((p, t, m.group(5)))
    return triples


class Migration050Tests(unittest.TestCase):
    def test_up_has_exactly_the_expected_grants(self):
        expected = {
            ("SELECT", table, role) for table in TABLES for role in ROLES
        }
        self.assertEqual(_triples(_statements(UP)), expected)

    def test_up_has_one_statement_per_role(self):
        stmts = _statements(UP)
        self.assertEqual(len(stmts), len(ROLES))
        for stmt in stmts:
            self.assertTrue(stmt.upper().startswith("GRANT "), stmt)

    def test_up_has_no_role_or_password_statements(self):
        code = "\n".join(_code_lines(UP)).upper()
        for word in SECRET_WORDS:
            self.assertNotIn(word, code)

    def test_up_has_no_write_privileges(self):
        code = "\n".join(_code_lines(UP)).upper()
        for priv in ("UPDATE", "INSERT", "DELETE", "ALL PRIVILEGES", "SEQUENCE"):
            self.assertNotIn(priv, code)

    def test_up_does_not_repeat_existing_grants(self):
        code = "\n".join(_code_lines(UP)).lower()
        self.assertNotIn("collector_requests", code)
        self.assertNotIn("collector_runs", code)

    def test_down_statements_are_revokes_from_each_role(self):
        stmts = _statements(DOWN)
        self.assertEqual(len(stmts), len(ROLES))
        for stmt in stmts:
            self.assertTrue(stmt.upper().startswith("REVOKE "), stmt)

    def test_down_mirrors_up(self):
        up = _triples(_statements(UP))
        down = _triples(_statements(DOWN))
        self.assertEqual(up, down)

    def test_down_has_no_secret_words(self):
        code = "\n".join(_code_lines(DOWN)).upper()
        for word in SECRET_WORDS:
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
