"""Read-only check that the loader role holds the grants the monthly refresh needs.

Design rule M-27 (docs/designs/home-events-t4f-design.md, task MT5). For the
loader role, asks has_table_privilege for INSERT, DELETE and SELECT on
company_reference and index_constituents. Makes no change to the database.

Usage (from the repo root, with the loader variables set in .env):
    .venv/Scripts/python.exe scripts/check_loader_grants.py
Exit 0 when every grant is present, 1 when any is missing, 2 when the
connection settings are unusable.
"""
import sys
from pathlib import Path

CHECKS = (
    ("company_reference", "INSERT"),
    ("company_reference", "DELETE"),
    ("company_reference", "SELECT"),
    ("index_constituents", "INSERT"),
    ("index_constituents", "DELETE"),
    ("index_constituents", "SELECT"),
)

_HAS_PRIVILEGE_SQL = "SELECT has_table_privilege(%s, %s, %s)"


def _granted(row):
    """Return the answer from a fetchone() result.

    A DB-API row is a sequence, so its first column is the answer. A bare
    value is taken as the answer itself.
    """
    if isinstance(row, (tuple, list)):
        return bool(row[0])
    return bool(row)


def check_loader_grants(conn, role):
    """Return one "table:PRIV" string for each privilege the role lacks."""
    missing = []
    with conn.cursor() as cur:
        for table, privilege in CHECKS:
            cur.execute(_HAS_PRIVILEGE_SQL, (role, table, privilege))
            if not _granted(cur.fetchone()):
                missing.append(f"{table}:{privilege}")
    return missing


if __name__ == "__main__":
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import psycopg

    from scanner.company_reference_job import LOADER_USER_DEFAULT, loader_dsn

    role = os.environ.get("POSTGRES_LOADER_USER") or LOADER_USER_DEFAULT
    # The DSN comes from loader_dsn(), which reads POSTGRES_LOADER_PASSWORD_FILE.
    try:
        dsn = loader_dsn()
    except RuntimeError as exc:
        print(f"check_loader_grants: {exc}", file=sys.stderr)
        sys.exit(2)

    with psycopg.connect(dsn) as conn:
        missing = check_loader_grants(conn, role)

    if missing:
        print(f"missing grants for {role}:")
        for item in missing:
            print(f"  {item}")
        sys.exit(1)
    print(f"all checked grants present for {role}")
    sys.exit(0)
