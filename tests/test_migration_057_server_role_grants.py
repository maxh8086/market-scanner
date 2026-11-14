"""Static checks for migration 057 (server role grants) and its down file."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "db" / "migrations" / "057_server_role_grants.sql"
DOWN = ROOT / "db" / "migrations" / "down" / "057_server_role_grants.down.sql"
ROLE = "market_scanner_server"

STMT_RE = re.compile(
    r"^(GRANT|REVOKE)\s+(.+?)\s+ON\s+(.+?)\s+(TO|FROM)\s+" + ROLE + r"$",
    re.IGNORECASE,
)


def _code_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("--")]


def _statements(path):
    text = "\n".join(_code_lines(path))
    return [s.strip() for s in text.split(";") if s.strip()]


def _pairs(statements):
    pairs = set()
    for stmt in statements:
        m = STMT_RE.match(stmt)
        if not m:
            raise AssertionError(f"unparseable statement: {stmt!r}")
        privs = [p.strip().upper() for p in m.group(2).split(",")]
        tables = [t.strip() for t in m.group(3).split(",")]
        for p in privs:
            for t in tables:
                pairs.add((p, t))
    return pairs


class Migration057Tests(unittest.TestCase):
    def test_up_has_no_role_or_password_statements(self):
        code = "\n".join(_code_lines(UP)).upper()
        self.assertNotIn("CREATE ROLE", code)
        self.assertNotIn("ALTER ROLE", code)
        self.assertNotIn("PASSWORD", code)

    def test_up_statements_are_grants_to_server_role(self):
        stmts = _statements(UP)
        self.assertTrue(stmts, "up file has no statements")
        for stmt in stmts:
            self.assertTrue(stmt.upper().startswith("GRANT "), stmt)
            self.assertTrue(stmt.endswith(f"TO {ROLE}"), stmt)

    def test_up_has_no_update_or_all_privileges(self):
        code = "\n".join(_code_lines(UP)).upper()
        self.assertNotIn("UPDATE", code)
        self.assertNotIn("ALL PRIVILEGES", code)

    def test_down_statements_are_revokes_from_server_role(self):
        stmts = _statements(DOWN)
        self.assertTrue(stmts, "down file has no statements")
        for stmt in stmts:
            self.assertTrue(stmt.upper().startswith("REVOKE "), stmt)
            self.assertTrue(stmt.endswith(f"FROM {ROLE}"), stmt)

    def test_up_and_down_cover_same_privileges_and_tables(self):
        up_pairs = _pairs(_statements(UP))
        down_pairs = _pairs(_statements(DOWN))
        self.assertEqual(up_pairs, down_pairs)


if __name__ == "__main__":
    unittest.main()
