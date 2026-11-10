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


def create(test_cls, target: str = "main") -> str:
    """test_cls is a TestCase class (setUpClass) or instance (setUp, one schema per test).

    target "main" (default) applies the main migrations exactly as before. target "events"
    applies only the events-database migrations into the throwaway schema of the main test
    database (the events SQL refers to nothing outside its own table, 4.5)."""
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

    # A class (setUpClass) registers a class cleanup; an instance (setUp) a test cleanup.
    # getattr(cls, 'addCleanup') is an unbound method, so the class check must come first.
    register = test_cls.addClassCleanup if isinstance(test_cls, type) else test_cls.addCleanup
    register(drop)
    if target == "main":
        migrate.apply()
    else:
        with db.connect() as conn:
            migrate.apply_on(conn, target)
    return name
