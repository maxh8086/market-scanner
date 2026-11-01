"""open_db builds its URI from SCANNER_MONGO_* parts; the generic MONGO_* names are ignored."""
import os
import unittest
from unittest import mock
from urllib.parse import unquote, urlsplit

from scanner import mongo

SCANNER_ENV = {
    "SCANNER_MONGO_USER": "market_scanner_app",
    "SCANNER_MONGO_PASSWORD": "s3cret",
    "SCANNER_MONGO_HOST": "127.0.0.1:27018",
    "SCANNER_MONGO_DB": "market_scanner",
}


class TestOpenDbEnvNames(unittest.TestCase):
    def _open(self, env):
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(mongo, "MongoClient") as client_cls, \
                mock.patch.object(mongo, "MongoDB") as db_cls:
            mongo.open_db()
            return client_cls.call_args.args[0], db_cls.call_args.args[1]

    def test_builds_uri_from_scanner_parts(self):
        uri, db_name = self._open(SCANNER_ENV)
        parts = urlsplit(uri)
        self.assertEqual(parts.username, "market_scanner_app")
        self.assertEqual(parts.password, "s3cret")
        self.assertEqual(parts.hostname, "127.0.0.1")
        self.assertEqual(parts.port, 27018)
        self.assertIn("authSource=market_scanner", parts.query)
        self.assertEqual(db_name, "market_scanner")

    def test_special_characters_in_password_are_encoded(self):
        uri, _ = self._open(dict(SCANNER_ENV, SCANNER_MONGO_PASSWORD="p@ss:/w#1"))
        self.assertEqual(unquote(urlsplit(uri).password), "p@ss:/w#1")
        self.assertEqual(urlsplit(uri).hostname, "127.0.0.1")

    def test_auth_source_can_be_overridden(self):
        uri, _ = self._open(dict(SCANNER_ENV, SCANNER_MONGO_AUTH_SOURCE="admin"))
        self.assertIn("authSource=admin", uri)

    def test_generic_names_are_ignored(self):
        with self.assertRaises(RuntimeError):
            self._open({"MONGO_URI": "mongodb://x:y@h:27017", "MONGO_DB": "d"})

    def test_scanner_names_win_over_generic(self):
        uri, _ = self._open(dict(SCANNER_ENV, MONGO_USER="other", MONGO_PASSWORD="other"))
        self.assertEqual(urlsplit(uri).username, "market_scanner_app")

    def test_missing_password_raises(self):
        env = {k: v for k, v in SCANNER_ENV.items() if k != "SCANNER_MONGO_PASSWORD"}
        with self.assertRaises(RuntimeError):
            self._open(env)

    def test_missing_user_raises(self):
        env = {k: v for k, v in SCANNER_ENV.items() if k != "SCANNER_MONGO_USER"}
        with self.assertRaises(RuntimeError):
            self._open(env)

    def test_db_name_defaults_to_market_scanner(self):
        env = {k: v for k, v in SCANNER_ENV.items() if k != "SCANNER_MONGO_DB"}
        _, db_name = self._open(env)
        self.assertEqual(db_name, "market_scanner")

    def test_redact_hides_password(self):
        self.assertEqual(
            mongo._redact("mongodb://market_scanner_app:s3cret@127.0.0.1:27018/?authSource=x"),
            "mongodb://market_scanner_app:****@127.0.0.1:27018/?authSource=x",
        )


if __name__ == "__main__":
    unittest.main()
