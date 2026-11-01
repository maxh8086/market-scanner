"""Postgres connection for this project's database. Reads POSTGRES_DSN (or the POSTGRES_* parts).

Never logs the DSN: it carries the password.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row


def dsn(env: Optional[dict] = None) -> str:
    env = os.environ if env is None else env
    if env.get("POSTGRES_DSN"):
        return env["POSTGRES_DSN"]
    try:
        return (f"host={env['POSTGRES_HOST']} port={env.get('POSTGRES_PORT', '5432')} "
                f"dbname={env['POSTGRES_DB']} user={env['POSTGRES_USER']} "
                f"password={env['POSTGRES_PASSWORD']}")
    except KeyError as exc:
        raise RuntimeError(f"Postgres is not configured: {exc.args[0]} is unset "
                           "(set the POSTGRES_* values in .env)") from None


def available(env: Optional[dict] = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("POSTGRES_DSN") or env.get("POSTGRES_HOST"))


def connect(**kw) -> psycopg.Connection:
    """A new connection; rows come back as dicts. Caller owns commit/close.

    PG_SEARCH_PATH (tests only) points every statement at a throwaway schema, so a test
    run can never write into the real tables.
    """
    schema = os.environ.get("PG_SEARCH_PATH")
    if schema and "options" not in kw:
        kw["options"] = f"-c search_path={schema},public"
    return psycopg.connect(dsn(), row_factory=dict_row, **kw)


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """One connection, committed on success, rolled back on error."""
    with connect() as conn:  # psycopg's context manager commits or rolls back
        yield conn
