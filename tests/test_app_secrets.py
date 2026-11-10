"""Offline tests for scanner/app_secrets.py (S2). A fake connection stands in for Postgres."""
import datetime as dt
import os
import unittest

from scanner import app_secrets as s
from scanner import secret_crypto as c


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    """Keeps rows in a dict and answers the three statement shapes app_secrets.py uses."""

    def __init__(self):
        self.rows = {}
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if sql.lstrip().startswith("INSERT"):
            name, ct, nonce, kv, last4, created, expires, by = params[:8]
            self.rows[name] = {"name": name, "ciphertext": ct, "nonce": nonce, "key_version": kv,
                               "last4": last4, "created_on": created, "expires_on": expires,
                               "updated_by": by, "updated_at": "now"}
            return FakeResult([])
        if "ciphertext, nonce, key_version" in sql:
            row = self.rows.get(params[0])
            return FakeResult([row] if row else [])
        if "FROM app_secret WHERE name" in sql:
            row = self.rows.get(params[0])
            return FakeResult([{k: v for k, v in row.items() if k not in ("ciphertext", "nonce", "key_version")}] if row else [])
        if "ORDER BY name" in sql:
            return FakeResult([{k: v for k, v in r.items() if k not in ("ciphertext", "nonce", "key_version")}
                               for _, r in sorted(self.rows.items())])
        raise AssertionError(f"unexpected statement: {sql}")


KEY = os.urandom(32)
D1 = dt.date(2026, 5, 18)
D2 = dt.date(2027, 5, 18)


class NameAndDateRules(unittest.TestCase):
    def test_valid_names_pass(self):
        self.assertEqual(s.validate_name("upstox_analytics_token"), "upstox_analytics_token")
        self.assertEqual(s.validate_name("ab"), "ab")

    def test_bad_names_rejected(self):
        for bad in ["", "a", "Upstox", "1abc", "has space", "x" * 65, "dash-name", None]:
            with self.subTest(name=bad), self.assertRaises(s.InvalidSecret):
                s.validate_name(bad)

    def test_expiry_before_creation_rejected(self):
        with self.assertRaises(s.InvalidSecret):
            s.validate_dates(D2, D1)

    def test_expiry_none_and_same_day_allowed(self):
        s.validate_dates(D1, None)
        s.validate_dates(D1, D1)

    def test_last4_hides_short_values(self):
        self.assertEqual(s.last4("abcd"), "")
        self.assertEqual(s.last4("abcdef"), "cdef")


class PutAndGet(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConn()

    def test_put_stores_ciphertext_not_plaintext(self):
        s.put(self.conn, KEY, "upstox_analytics_token", "SECRETVALUE1234",
              created_on=D1, expires_on=D2, updated_by="admin")
        row = self.conn.rows["upstox_analytics_token"]
        self.assertNotIn(b"SECRETVALUE1234", bytes(row["ciphertext"]))
        self.assertEqual(row["last4"], "1234")
        self.assertEqual(len(row["nonce"]), 12)

    def test_round_trip(self):
        s.put(self.conn, KEY, "upstox_analytics_token", "SECRETVALUE1234",
              created_on=D1, expires_on=D2, updated_by="admin")
        self.assertEqual(s.get_value(self.conn, KEY, "upstox_analytics_token"), "SECRETVALUE1234")

    def test_replace_overwrites_value_and_dates(self):
        s.put(self.conn, KEY, "upstox_analytics_token", "first-value-0001", created_on=D1,
              expires_on=D2, updated_by="admin")
        s.put(self.conn, KEY, "upstox_analytics_token", "second-value-9999", created_on=D1,
              expires_on=None, updated_by="admin")
        self.assertEqual(s.get_value(self.conn, KEY, "upstox_analytics_token"), "second-value-9999")
        self.assertIsNone(self.conn.rows["upstox_analytics_token"]["expires_on"])

    def test_wrong_key_fails_to_decrypt(self):
        s.put(self.conn, KEY, "upstox_analytics_token", "value-abcd", created_on=D1,
              expires_on=None, updated_by="admin")
        with self.assertRaises(c.DecryptError):
            s.get_value(self.conn, os.urandom(32), "upstox_analytics_token")

    def test_ciphertext_copied_to_another_name_fails(self):
        s.put(self.conn, KEY, "upstox_analytics_token", "value-abcd", created_on=D1,
              expires_on=None, updated_by="admin")
        self.conn.rows["telegram_bot_token"] = dict(self.conn.rows["upstox_analytics_token"],
                                                    name="telegram_bot_token")
        with self.assertRaises(c.DecryptError):
            s.get_value(self.conn, KEY, "telegram_bot_token")

    def test_missing_secret_raises_not_found(self):
        with self.assertRaises(s.SecretNotFound):
            s.get_value(self.conn, KEY, "nope_missing")

    def test_empty_value_rejected(self):
        with self.assertRaises(s.InvalidSecret):
            s.put(self.conn, KEY, "upstox_analytics_token", "", created_on=D1, expires_on=None, updated_by="admin")
        self.assertEqual(self.conn.statements, [])


class MetaListing(unittest.TestCase):
    def test_list_and_meta_never_return_ciphertext_or_value(self):
        conn = FakeConn()
        s.put(conn, KEY, "upstox_analytics_token", "value-WXYZ", created_on=D1, expires_on=D2, updated_by="admin")
        rows = s.list_meta(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["last4"], "WXYZ")
        self.assertNotIn("ciphertext", rows[0])
        self.assertNotIn("value-WXYZ", repr(rows))
        meta = s.get_meta(conn, "upstox_analytics_token")
        self.assertEqual(meta["expires_on"], D2)
        self.assertIsNone(s.get_meta(conn, "other_name_x"))


if __name__ == "__main__":
    unittest.main()
