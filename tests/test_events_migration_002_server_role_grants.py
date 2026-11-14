"""Static checks for events migration 002 (server role grants) and its down file."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "db" / "events_migrations" / "002_server_role_grants.sql"
DOWN = ROOT / "db" / "events_migrations" / "down" / "002_server_role_grants.down.sql"

UP_STATEMENT = "GRANT INSERT ON home_events TO market_scanner_server;"
DOWN_STATEMENT = "REVOKE INSERT ON home_events FROM market_scanner_server;"


def _code_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("--")]


class EventsMigration002Tests(unittest.TestCase):
    def test_up_is_exactly_one_insert_grant(self):
        self.assertEqual(_code_lines(UP), [UP_STATEMENT])

    def test_up_has_no_forbidden_keywords(self):
        code = "\n".join(_code_lines(UP)).upper()
        for word in ("CREATE ROLE", "PASSWORD", "UPDATE", "SELECT", "ALL"):
            self.assertIsNone(re.search(r"\b" + word + r"\b", code), word)

    def test_down_is_exactly_one_insert_revoke(self):
        self.assertEqual(_code_lines(DOWN), [DOWN_STATEMENT])


if __name__ == "__main__":
    unittest.main()
