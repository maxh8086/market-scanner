"""Offline tests for scanner/secrets_cli.py (S3 and S4). A fake connection stands in for Postgres."""
import datetime as dt
import os
import unittest

from scanner import app_secrets as s
from scanner import secrets_cli as cli
from tests.test_app_secrets import FakeConn

KEY = os.urandom(32)
TODAY = dt.date(2026, 11, 10)


class Conn(FakeConn):
    """FakeConn with the context-manager and commit/rollback calls main() makes."""

    def __init__(self):
        super().__init__()
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class ImportEnv(unittest.TestCase):
    ENV = {
        "UPSTOX_ANALYTICS_ACCESS_TOKEN": "upstox-token-ABCD1234",
        "KITE_API_KEY": "kitekey-WXYZ",
        "KITE_API_SECRET": "",
        "KITE_ACCESS_TOKEN": "kitetok-9999",
        "SCREENER_PASSWORD": "screener-should-not-import",
    }

    def run_import(self, conn, dry_run=False):
        lines = []
        code = cli.main(["import-env"] + (["--dry-run"] if dry_run else []),
                        conn_factory=lambda: conn, key_loader=lambda: KEY,
                        env_values=dict(self.ENV), today=TODAY, out=lines.append)
        return code, "\n".join(lines)

    def test_dry_run_writes_nothing(self):
        conn = Conn()
        code, out = self.run_import(conn, dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(conn.rows, {})
        self.assertIn("would import UPSTOX_ANALYTICS_ACCESS_TOKEN -> upstox_analytics_token", out)

    def test_import_maps_known_keys_and_skips_screener_and_empty(self):
        conn = Conn()
        code, out = self.run_import(conn)
        self.assertEqual(code, 0)
        self.assertEqual(set(conn.rows), {"upstox_analytics_token", "kite_api_key", "kite_access_token"})
        self.assertNotIn("screener", out.lower())
        self.assertNotIn("kite_api_secret", conn.rows)

    def test_import_applies_known_upstox_dates(self):
        conn = Conn()
        self.run_import(conn)
        row = conn.rows["upstox_analytics_token"]
        self.assertEqual(row["created_on"], dt.date(2026, 5, 18))
        self.assertEqual(row["expires_on"], dt.date(2027, 5, 18))
        self.assertEqual(conn.rows["kite_api_key"]["created_on"], TODAY)
        self.assertIsNone(conn.rows["kite_api_key"]["expires_on"])

    def test_import_is_checked_and_commits_only_on_success(self):
        conn = Conn()
        code, _ = self.run_import(conn)
        self.assertEqual(code, 0)
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)

    def test_import_output_never_contains_values(self):
        conn = Conn()
        _, out = self.run_import(conn)
        for v in self.ENV.values():
            if v:
                self.assertNotIn(v, out)
        self.assertIn("plaintext file NOT deleted", out)


class SetAndRead(unittest.TestCase):
    def test_set_reads_value_from_prompt_not_args_and_checks_back(self):
        conn = Conn()
        lines = []
        code = cli.main(["set", "kite_api_key", "--created", "2026-11-01", "--by", "admin"],
                        conn_factory=lambda: conn, key_loader=lambda: KEY,
                        read_value=lambda: "typed-value-5678", today=TODAY, out=lines.append)
        self.assertEqual(code, 0)
        self.assertEqual(s.get_value(conn, KEY, "kite_api_key"), "typed-value-5678")
        self.assertEqual(conn.commits, 1)
        self.assertNotIn("typed-value-5678", "\n".join(lines))

    def test_set_rejects_bad_name_before_prompting(self):
        conn = Conn()
        prompted = []
        with self.assertRaises(s.InvalidSecret):
            cli.main(["set", "Bad Name"], conn_factory=lambda: conn, key_loader=lambda: KEY,
                     read_value=lambda: prompted.append(1) or "x", today=TODAY, out=lambda _: None)
        self.assertEqual(prompted, [])

    def test_set_bad_date_exits(self):
        with self.assertRaises(SystemExit):
            cli.main(["set", "kite_api_key", "--expires", "2026-13-40"], conn_factory=Conn,
                     key_loader=lambda: KEY, read_value=lambda: "v", today=TODAY, out=lambda _: None)

    def test_list_and_meta_show_hint_not_value(self):
        conn = Conn()
        s.put(conn, KEY, "kite_api_key", "hidden-value-AB12", created_on=TODAY, expires_on=None, updated_by="admin")
        lines = []
        cli.main(["list"], conn_factory=lambda: conn, key_loader=lambda: KEY, out=lines.append)
        cli.main(["meta", "kite_api_key"], conn_factory=lambda: conn, key_loader=lambda: KEY, out=lines.append)
        text = "\n".join(lines)
        self.assertIn("AB12", text)
        self.assertNotIn("hidden-value-AB12", text)

    def test_meta_missing_returns_1(self):
        lines = []
        code = cli.main(["meta", "nothing_here"], conn_factory=Conn, key_loader=lambda: KEY, out=lines.append)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
