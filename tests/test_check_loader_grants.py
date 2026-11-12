"""Tests for scripts/check_loader_grants.py (task MT5, design rule M-27).

The script is read-only. It asks has_table_privilege for INSERT, DELETE and
SELECT on company_reference and index_constituents, for the loader role.
The database is mocked. Nothing here touches the network or a real database.
"""
import unittest
from pathlib import Path
from unittest import mock

ROLE = "market_scanner_loader"
SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "check_loader_grants.py"
)


def _fake_connection(denied=frozenset()):
    """Return a mock connection.

    has_table_privilege answers False for every (table, privilege) pair in
    `denied`, and True for all others. The query is identified from the last
    execute() call: the table name, then the privilege, with INSERT and DELETE
    checked before SELECT, because the SQL text itself contains SELECT.
    """
    cursor = mock.MagicMock(name="cursor")
    cursor.__enter__.return_value = cursor
    state = {"query": ""}

    def execute(sql, params=None):
        state["query"] = f"{sql} {params!r}"

    def fetchone():
        text = state["query"]
        table = next(
            (t for t in ("company_reference", "index_constituents") if t in text),
            None,
        )
        privilege = next(
            (p for p in ("INSERT", "DELETE", "SELECT") if p in text),
            None,
        )
        return (table, privilege) not in denied

    cursor.execute.side_effect = execute
    cursor.fetchone.side_effect = fetchone

    conn = mock.MagicMock(name="connection")
    conn.cursor.return_value = cursor
    return conn


class CheckLoaderGrantsTests(unittest.TestCase):
    def test_check_loader_grants_reports_missing(self):
        from scripts.check_loader_grants import check_loader_grants

        conn = _fake_connection(denied={("company_reference", "INSERT")})

        missing = check_loader_grants(conn, ROLE)

        self.assertIsInstance(missing, list)
        self.assertIn("company_reference:INSERT", missing)
        cursor = conn.cursor.return_value
        self.assertTrue(
            any(ROLE in repr(c) for c in cursor.execute.call_args_list),
            "every has_table_privilege check must be made for the loader role",
        )

    def test_check_loader_grants_passes_when_granted(self):
        from scripts.check_loader_grants import check_loader_grants

        conn = _fake_connection(denied=frozenset())

        self.assertEqual(check_loader_grants(conn, ROLE), [])

    @unittest.skipUnless(
        SCRIPT_PATH.exists(),
        "scripts/check_loader_grants.py is not written yet",
    )
    def test_check_loader_grants_reads_no_password_file(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")

        offending = [
            line
            for line in text.splitlines()
            if "PASSWORD" in line.upper()
            and "POSTGRES_LOADER_PASSWORD_FILE" not in line
        ]

        self.assertEqual(
            offending,
            [],
            "script may mention a password only in a line naming "
            "POSTGRES_LOADER_PASSWORD_FILE",
        )


if __name__ == "__main__":
    unittest.main()
