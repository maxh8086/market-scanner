"""Regression: scanner/pg/db.py loads the project's .env itself, so scripts such as ath_scan.py
see POSTGRES_* without importing another module that loads it. Offline: no database."""
import os
import unittest
from unittest import mock

from scanner.pg import db


class DotenvLoadTests(unittest.TestCase):
    def setUp(self):
        db._dotenv_loaded = False

    def tearDown(self):
        db._dotenv_loaded = False

    def test_dsn_loads_dotenv_once(self):
        clean = {"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_DB": "d",
                 "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p"}
        with mock.patch("dotenv.load_dotenv") as load, \
             mock.patch("dotenv.find_dotenv", return_value="/fake/.env"), \
             mock.patch.dict(os.environ, clean, clear=True):
            db.dsn()
            db.dsn()
        load.assert_called_once_with("/fake/.env")

    def test_available_loads_dotenv_when_no_env_passed(self):
        with mock.patch("dotenv.load_dotenv") as load, \
             mock.patch("dotenv.find_dotenv", return_value="/fake/.env"):
            db.available()
        load.assert_called_once()

    def test_explicit_env_dict_skips_dotenv(self):
        with mock.patch("dotenv.load_dotenv") as load:
            db.available({"POSTGRES_HOST": "127.0.0.1"})
        load.assert_not_called()

    def test_shell_value_is_not_overridden(self):
        # load_dotenv is called with its default override=False, so a value already in the shell wins.
        with mock.patch("dotenv.find_dotenv", return_value="/fake/.env"), \
             mock.patch("dotenv.load_dotenv") as load:
            db._load_project_env()
        self.assertNotIn("override", load.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
