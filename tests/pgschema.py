"""A throwaway Postgres schema with every migration applied, for tests that write.

Tests must never write to the real tables: they would show up in the UI. Use

    class T(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.schema = pgschema.create(cls)      # raises SkipTest when Postgres is unreachable
        # no tearDownClass needed: create() registers the drop with addClassCleanup
"""
from __future__ import annotations

import os
import unittest
import uuid


def create(test_cls) -> str:
    """test_cls is a TestCase class (setUpClass) or instance (setUp, one schema per test)."""
    from scanner.pg import db, migrate

    if not db.available():
        raise unittest.SkipTest("Postgres is not configured")
    name = f"test_{uuid.uuid4().hex[:10]}"
    try:
        with db.connect() as conn:
            conn.execute(f"CREATE SCHEMA {name}")
    except Exception as exc:
        raise unittest.SkipTest(f"Postgres is not reachable: {type(exc).__name__}")

    previous = os.environ.get("PG_SEARCH_PATH")
    os.environ["PG_SEARCH_PATH"] = name

    def drop():
        if previous is None:
            os.environ.pop("PG_SEARCH_PATH", None)
        else:
            os.environ["PG_SEARCH_PATH"] = previous
        with db.connect() as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")

    (getattr(test_cls, 'addCleanup', None) or test_cls.addClassCleanup)(drop)
    migrate.apply()
    return name
