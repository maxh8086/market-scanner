"""Static checks for migration 058 (portfolio snapshots) and its down file. No database is used."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "db" / "migrations" / "058_portfolio_snapshots.sql"
DOWN = ROOT / "db" / "migrations" / "down" / "058_portfolio_snapshots.down.sql"
ROLE = "market_scanner_server"

GRANT_RE = re.compile(r"^GRANT\s+(.+?)\s+ON\s+(.+?)\s+TO\s+" + ROLE + r"$", re.IGNORECASE)
CREATE_RE = re.compile(r"CREATE\s+TABLE\s+(\w+)", re.IGNORECASE)

EXPECTED_TABLES = {"user_profile", "portfolio_sync", "portfolio_holding"}
EXPECTED_GRANTS = {
    ("SELECT", "user_profile"),
    ("SELECT", "portfolio_sync"),
    ("INSERT", "portfolio_sync"),
    ("SELECT", "portfolio_holding"),
    ("INSERT", "portfolio_holding"),
}


def _code_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("--")]


def _code_text(path):
    return "\n".join(_code_lines(path))


def _statements(path):
    return [s.strip() for s in _code_text(path).split(";") if s.strip()]


def _grant_pairs(statements):
    pairs = set()
    for stmt in statements:
        if not stmt.upper().startswith("GRANT "):
            continue
        collapsed = " ".join(stmt.split())
        m = GRANT_RE.match(collapsed)
        if not m:
            raise AssertionError(f"unparseable grant: {stmt!r}")
        privs = [p.strip().upper() for p in m.group(1).split(",")]
        tables = [t.strip() for t in m.group(2).split(",")]
        for p in privs:
            for t in tables:
                pairs.add((p, t))
    return pairs


class Migration058Tests(unittest.TestCase):
    def test_up_creates_the_three_tables_and_seeds_default_profile(self):
        code = _code_text(UP)
        created = set(CREATE_RE.findall(code))
        self.assertEqual(created, EXPECTED_TABLES)
        self.assertRegex(
            code,
            r"INSERT\s+INTO\s+user_profile\s*\(\s*profile_id\s*,\s*display_name\s*\)\s*VALUES\s*\(\s*'default'\s*,\s*'Default'\s*\)\s*ON\s+CONFLICT\s+DO\s+NOTHING",
        )

    def test_up_creates_tables_in_dependency_order(self):
        code = _code_text(UP)
        profile = code.index("CREATE TABLE user_profile")
        sync = code.index("CREATE TABLE portfolio_sync")
        holding = code.index("CREATE TABLE portfolio_holding")
        self.assertLess(profile, sync)
        self.assertLess(sync, holding)

    def test_up_grants_are_exactly_the_least_privilege_set(self):
        stmts = _statements(UP)
        grants = [s for s in stmts if s.upper().startswith("GRANT ")]
        self.assertEqual(len(grants), 2)
        for stmt in grants:
            self.assertTrue(stmt.endswith(f"TO {ROLE}"), stmt)
        self.assertEqual(_grant_pairs(stmts), EXPECTED_GRANTS)

    def test_up_has_no_update_or_delete_or_all_grant(self):
        stmts = _statements(UP)
        privs = {p for p, _ in _grant_pairs(stmts)}
        self.assertNotIn("UPDATE", privs)
        self.assertNotIn("DELETE", privs)
        self.assertNotIn("ALL", privs)
        for stmt in stmts:
            if stmt.upper().startswith("GRANT "):
                self.assertNotRegex(stmt.upper(), r"\b(UPDATE|DELETE|ALL PRIVILEGES)\b", stmt)

    def test_up_has_no_password_secret_or_role_text(self):
        code = _code_text(UP).upper()
        for banned in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "CREATE ROLE", "ALTER ROLE"):
            self.assertNotIn(banned, code, banned)

    def test_down_drops_three_tables_in_dependency_order(self):
        stmts = _statements(DOWN)
        self.assertEqual(
            stmts,
            [
                "DROP TABLE portfolio_holding",
                "DROP TABLE portfolio_sync",
                "DROP TABLE user_profile",
            ],
        )


if __name__ == "__main__":
    unittest.main()
