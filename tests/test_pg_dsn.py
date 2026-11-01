"""dsn() prefers POSTGRES_DSN, but refuses one whose user or database contradicts the POSTGRES_* parts."""
import os
import unittest
from unittest import mock

from scanner.pg import db

PARTS_ENV = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5433",
    "POSTGRES_DB": "market_scanner",
    "POSTGRES_USER": "scanner",
    "POSTGRES_PASSWORD": "s3cret",
}
GOOD_DSN = "postgresql://scanner:s3cret@127.0.0.1:5433/market_scanner"


def _dsn(env):
    with mock.patch.dict(os.environ, env, clear=True):
        return db.dsn()


class TestDsnGuard(unittest.TestCase):
    def test_mismatched_user_raises(self):
        env = dict(PARTS_ENV, POSTGRES_DSN=GOOD_DSN.replace("scanner:", "ath_scanner:"))
        with self.assertRaises(RuntimeError) as ctx:
            _dsn(env)
        msg = str(ctx.exception)
        self.assertIn("POSTGRES_USER", msg)
        self.assertIn("ath_scanner", msg)
        self.assertIn("scanner", msg)

    def test_mismatched_database_raises(self):
        env = dict(PARTS_ENV, POSTGRES_DSN=GOOD_DSN.replace("/market_scanner", "/ath_scanner"))
        with self.assertRaises(RuntimeError) as ctx:
            _dsn(env)
        msg = str(ctx.exception)
        self.assertIn("POSTGRES_DB", msg)
        self.assertIn("ath_scanner", msg)
        self.assertIn("market_scanner", msg)

    def test_agreeing_values_return_the_dsn(self):
        self.assertEqual(_dsn(dict(PARTS_ENV, POSTGRES_DSN=GOOD_DSN)), GOOD_DSN)

    def test_dsn_only_works(self):
        self.assertEqual(_dsn({"POSTGRES_DSN": GOOD_DSN}), GOOD_DSN)

    def test_parts_only_work(self):
        self.assertEqual(
            _dsn(PARTS_ENV),
            "host=127.0.0.1 port=5433 dbname=market_scanner user=scanner password=s3cret",
        )

    def test_error_message_does_not_contain_password_or_host(self):
        env = dict(PARTS_ENV,
                   POSTGRES_DSN="postgresql://ath_scanner:hunter2@db.internal:5432/ath_scanner")
        with self.assertRaises(RuntimeError) as ctx:
            _dsn(env)
        msg = str(ctx.exception)
        self.assertNotIn("hunter2", msg)
        self.assertNotIn("db.internal", msg)
        self.assertNotIn("postgresql://", msg)


class TestUnconfiguredPostgres(unittest.TestCase):
    """No POSTGRES_* at all: the error names the missing key and both exits, and connect() never dials."""

    def test_unconfigured_message_names_key_and_both_exits(self):
        with self.assertRaises(RuntimeError) as ctx:
            _dsn({})
        msg = str(ctx.exception)
        self.assertIn("POSTGRES_HOST", msg)
        self.assertIn("POSTGRES_* values in .env", msg)
        self.assertIn("scripts/ensure_postgres.ps1", msg)
        self.assertIn("MARKETDATA_BACKEND=sqlite", msg)

    def test_connect_fails_before_dialing(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("scanner.pg.db.psycopg.connect") as dial:
            with self.assertRaises(RuntimeError) as ctx:
                db.connect()
            dial.assert_not_called()
        self.assertIn("Postgres is not configured", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
