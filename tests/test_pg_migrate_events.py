"""The events database migration series (4.5): target selection in scanner.pg.migrate, the
dbname override in scanner.pg.db, and the events table in a throwaway schema.

Tests named in the spec (section 8) run without Postgres, except apply_events_creates_table,
which skips without Postgres. A skip is not a pass.
"""
import contextlib
import io
import os
import unittest
from unittest import mock

from psycopg.conninfo import conninfo_to_dict

from scanner.pg import db, migrate
import tests.pgschema as pgschema


class TestEventsMigrationTargets(unittest.TestCase):
    def test_files_events_dir(self):
        names = [f.name for f in migrate.files("events")]
        self.assertEqual(
            names,
            ["001_home_events.sql", "002_server_role_grants.sql", "003_server_role_select_grant.sql"],
        )
        self.assertEqual(migrate.files("events")[0].parent, migrate.MIGRATION_DIRS["events"])
        self.assertTrue(migrate.MIGRATION_DIRS["events"].name == "events_migrations")

    def test_files_default_is_main(self):
        self.assertEqual(migrate.files(), migrate.files("main"))
        self.assertTrue(all(f.parent == migrate.MIGRATION_DIRS["main"] for f in migrate.files()))
        self.assertNotIn("001_home_events.sql", [f.name for f in migrate.files()])

    def test_cli_db_argument(self):
        with mock.patch.object(migrate, "load_dotenv"), \
                mock.patch.object(migrate, "status", return_value=[("001_home_events.sql", False)]) as st, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(migrate.main(["--db", "events", "--status"]), 0)
        st.assert_called_once_with("events")
        self.assertIn("PENDING  001_home_events.sql", out.getvalue())

    def test_cli_default_db_is_main(self):
        with mock.patch.object(migrate, "load_dotenv"), \
                mock.patch.object(migrate, "apply", return_value=[]) as ap, \
                contextlib.redirect_stdout(io.StringIO()):
            migrate.main([])
        ap.assert_called_once_with("main")

    def test_unknown_db_raises(self):
        with self.assertRaises(ValueError):
            migrate.files("bogus")
        with self.assertRaises(ValueError):
            migrate.apply("bogus")
        with self.assertRaises(ValueError):
            migrate.status("bogus")

    def test_events_dbname_default_and_override(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(migrate._dbname("main"))
            self.assertEqual(migrate._dbname("events"), "market_scanner_events")
        with mock.patch.dict(os.environ, {"POSTGRES_EVENTS_DB": "custom_events"}, clear=True):
            self.assertEqual(migrate._dbname("events"), "custom_events")


class TestDsnDbnameOverride(unittest.TestCase):
    PARTS = {
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "5433",
        "POSTGRES_DB": "market_scanner",
        "POSTGRES_USER": "scanner",
        "POSTGRES_PASSWORD": "s3cret",
    }

    def test_parts_override_database(self):
        with mock.patch.dict(os.environ, self.PARTS, clear=True):
            text = db.dsn("market_scanner_events")
        self.assertIn("dbname=market_scanner_events", text)
        self.assertNotIn("dbname=market_scanner ", text)

    def test_url_override_skips_agreement_check(self):
        url = "postgresql://ath_scanner:s3cret@127.0.0.1:5433/ath_scanner"
        env = dict(self.PARTS, POSTGRES_DSN=url)
        with mock.patch.dict(os.environ, env, clear=True):
            # Without an override this DSN is refused (user and database disagree with POSTGRES_*).
            with self.assertRaises(RuntimeError):
                db.dsn()
            info = conninfo_to_dict(db.dsn("market_scanner_events"))
        self.assertEqual(info["dbname"], "market_scanner_events")
        self.assertEqual(info["user"], "ath_scanner")

    def test_default_dsn_unchanged_for_parts(self):
        with mock.patch.dict(os.environ, self.PARTS, clear=True):
            self.assertEqual(
                db.dsn(),
                "host=127.0.0.1 port=5433 dbname=market_scanner user=scanner password=s3cret",
            )


class TestEventsSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = pgschema.create(cls, target="events")  # raises SkipTest without Postgres

    def test_apply_events_creates_table(self):
        with db.connect() as conn:
            row = conn.execute("SELECT to_regclass('home_events') AS t").fetchone()
            recorded = conn.execute(
                "SELECT filename FROM schema_migrations WHERE filename = '001_home_events.sql'"
            ).fetchall()
        self.assertIsNotNone(row["t"])
        self.assertEqual(len(recorded), 1)


if __name__ == "__main__":
    unittest.main()
