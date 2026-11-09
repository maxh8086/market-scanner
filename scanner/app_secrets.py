"""App-level secrets stored encrypted in Postgres (docs/designs/secrets-and-roles.md, S2).

Each value is encrypted with the master key (scanner/secret_crypto.py) before it is written.
The API is the only process that decrypts. Nothing here logs a value, and `list_meta`
returns only the masked hint (last four characters), never the value.

Functions take a psycopg connection (rows as dicts, see scanner/pg/db.py) and the master
key bytes, so callers and tests control both.
"""
from __future__ import annotations

import datetime as dt
import re

from . import secret_crypto

TABLE = "app_secret"
KEY_VERSION = 1
OWNER = "app"  # app secrets have one owner; kept in the AAD so the format matches later per-user rows
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class SecretNotFound(KeyError):
    """No app secret with that name."""


class InvalidSecret(ValueError):
    """The name, value or dates break a rule. The message names the rule, never the value."""


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise InvalidSecret("name must be 2-64 characters: lowercase letters, digits and underscores, starting with a letter")
    return name


def last4(value: str) -> str:
    """Masked hint: the last four characters. Values of four characters or fewer show nothing."""
    return "" if len(value) <= 4 else value[-4:]


def validate_dates(created_on: dt.date, expires_on: dt.date | None) -> None:
    if not isinstance(created_on, dt.date):
        raise InvalidSecret("created_on must be a date")
    if expires_on is not None:
        if not isinstance(expires_on, dt.date):
            raise InvalidSecret("expires_on must be a date or None")
        if expires_on < created_on:
            raise InvalidSecret("expires_on is before created_on")


def put(conn, key: bytes, name: str, value: str, *, created_on: dt.date,
        expires_on: dt.date | None, updated_by: str) -> None:
    """Insert or replace one app secret. Replacing keeps the row; the caller sets the dates."""
    validate_name(name)
    if not value:
        raise InvalidSecret("value is empty")
    validate_dates(created_on, expires_on)
    nonce, ciphertext = secret_crypto.encrypt(
        key, value, secret_crypto.aad_for(TABLE, name, OWNER, KEY_VERSION))
    conn.execute(
        f"""INSERT INTO {TABLE} (name, ciphertext, nonce, key_version, last4,
                                 created_on, expires_on, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (name) DO UPDATE SET
              ciphertext = EXCLUDED.ciphertext, nonce = EXCLUDED.nonce,
              key_version = EXCLUDED.key_version, last4 = EXCLUDED.last4,
              created_on = EXCLUDED.created_on, expires_on = EXCLUDED.expires_on,
              updated_by = EXCLUDED.updated_by, updated_at = now()""",
        (name, ciphertext, nonce, KEY_VERSION, last4(value), created_on, expires_on, updated_by),
    )


def get_value(conn, key: bytes, name: str) -> str:
    """Decrypt one app secret. Only the API calls this. Raises SecretNotFound or DecryptError."""
    validate_name(name)
    row = conn.execute(
        f"SELECT ciphertext, nonce, key_version FROM {TABLE} WHERE name = %s", (name,)).fetchone()
    if row is None:
        raise SecretNotFound(name)
    aad = secret_crypto.aad_for(TABLE, name, OWNER, row["key_version"])
    return secret_crypto.decrypt(key, bytes(row["nonce"]), bytes(row["ciphertext"]), aad)


def get_meta(conn, name: str) -> dict | None:
    """Dates and masked hint for one secret. Never the value."""
    validate_name(name)
    return conn.execute(
        f"SELECT name, last4, created_on, expires_on, updated_by, updated_at "
        f"FROM {TABLE} WHERE name = %s", (name,)).fetchone()


def list_meta(conn) -> list[dict]:
    """Every app secret's name, masked hint and dates. No ciphertext, no plaintext."""
    return conn.execute(
        f"SELECT name, last4, created_on, expires_on, updated_by, updated_at "
        f"FROM {TABLE} ORDER BY name").fetchall()
