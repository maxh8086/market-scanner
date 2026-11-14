"""Static checks for events migration 003 (server SELECT grant) and its down file."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "db" / "events_migrations" / "003_server_role_select_grant.sql"
DOWN = ROOT / "db" / "events_migrations" / "down" / "003_server_role_select_grant.down.sql"

UP_STATEMENT = "GRANT SELECT ON home_events TO market_scanner_server;"
DOWN_STATEMENT = "REVOKE SELECT ON home_events FROM market_scanner_server;"
SECRET_WORDS = ("PASSWORD", "SECRET", "TOKEN", "CREATE ROLE", "ALTER ROLE")
WRITE_WORDS = ("INSERT", "UPDATE", "DELETE", "ALL", "TRUNCATE", "REFERENCES")


def _code_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("--")]


class EventsMigration003Tests(unittest.TestCase):
    def test_up_is_exactly_one_select_grant(self):
        self.assertEqual(_code_lines(UP), [UP_STATEMENT])

    def test_up_has_no_role_or_secret_statements(self):
        code = "\n".join(_code_lines(UP)).upper()
        for word in SECRET_WORDS:
            self.assertNotIn(word, code)

    def test_up_has_no_write_privileges(self):
        code = "\n".join(_code_lines(UP)).upper()
        for word in WRITE_WORDS:
            self.assertIsNone(re.search(r"\b" + word + r"\b", code), word)

    def test_up_grants_only_on_home_events_to_the_server_login(self):
        code = "\n".join(_code_lines(UP))
        grants = re.findall(r"\bON\s+(\S+)\s+TO\s+(\S+?);", code, re.IGNORECASE)
        self.assertEqual(grants, [("home_events", "market_scanner_server")])

    def test_down_is_exactly_one_select_revoke(self):
        self.assertEqual(_code_lines(DOWN), [DOWN_STATEMENT])

    def test_down_has_no_secret_words(self):
        code = "\n".join(_code_lines(DOWN)).upper()
        for word in SECRET_WORDS:
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
