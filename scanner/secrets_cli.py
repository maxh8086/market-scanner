"""Admin command line for app secrets (docs/designs/secrets-and-roles.md, S3 and S4).

Run inside the API container, where the master key is mounted:

    python -m scanner.secrets_cli list
    python -m scanner.secrets_cli set NAME [--created YYYY-MM-DD] [--expires YYYY-MM-DD|none] [--by WHO]
    python -m scanner.secrets_cli meta NAME
    python -m scanner.secrets_cli import-env [--dry-run]
    python -m scanner.secrets_cli test NAME
    python -m scanner.secrets_cli rotate NAME --created YYYY-MM-DD --expires YYYY-MM-DD|none [--by WHO]

`test` runs the live check for the stored value (no write). `rotate` reads a new value from the
hidden prompt, runs the live check on it, and saves it only if the check passes.

A value is never a command-line argument. `set` reads it from a hidden prompt. `import-env`
reads the plaintext data/secrets.env, stores the mapped values encrypted, and checks each one
by decrypting it. It does NOT delete the plaintext file; that step needs the user's yes.
Output never includes a value, only names, dates and masked hints.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import os
import secrets
import sys
from typing import Callable

from . import app_secrets, secret_crypto, secrets_store
from . import secret_checks

# Plaintext name in data/secrets.env -> app secret name. Screener is cut from v1 (decision 9).
ENV_TO_APP = {
    "UPSTOX_ANALYTICS_ACCESS_TOKEN": "upstox_analytics_token",
    "KITE_API_KEY": "kite_api_key",
    "KITE_API_SECRET": "kite_api_secret",
    "KITE_ACCESS_TOKEN": "kite_access_token",
}
# Known dates from the Upstox Developer Apps page (screenshot 2026-11-10, fundamentals doc).
KNOWN_DATES = {"upstox_analytics_token": (dt.date(2026, 5, 18), dt.date(2027, 5, 18))}


def _parse_date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"not a date (YYYY-MM-DD): {text}") from None


def cmd_list(conn, out: Callable[[str], None]) -> int:
    rows = app_secrets.list_meta(conn)
    if not rows:
        out("no app secrets stored")
        return 0
    for r in rows:
        out(f"{r['name']:<28} ...{r['last4']:<6} created {r['created_on']}  expires {r['expires_on'] or '-'}  by {r['updated_by']}")
    return 0


def cmd_meta(conn, name: str, out: Callable[[str], None]) -> int:
    r = app_secrets.get_meta(conn, name)
    if r is None:
        out(f"not found: {name}")
        return 1
    out(f"{r['name']}: ...{r['last4']}  created {r['created_on']}  expires {r['expires_on'] or '-'}  updated {r['updated_at']} by {r['updated_by']}")
    return 0


def cmd_set(conn, key: bytes, name: str, created: dt.date, expires: dt.date | None, by: str,
            read_value: Callable[[], str], out: Callable[[str], None]) -> int:
    value = read_value()
    app_secrets.put(conn, key, name, value, created_on=created, expires_on=expires, updated_by=by)
    # Check that the stored value decrypts to what was typed, before reporting success.
    if app_secrets.get_value(conn, key, name) != value:
        out(f"stored {name}, but the read-back check failed; check the master key")
        return 1
    out(f"saved {name} (...{app_secrets.last4(value)}), created {created}, expires {expires or '-'}")
    return 0


def cmd_test(conn, key: bytes, name: str, checks: dict, out: Callable[[str], None]) -> int:
    """Run the live check on the stored value. Never writes."""
    check = checks.get(name)
    if check is None:
        out(f"no test for {name}")
        return 2
    try:
        value = app_secrets.get_value(conn, key, name)
    except app_secrets.SecretNotFound:
        out(f"not found: {name}")
        return 1
    try:
        check(value)
    except secret_checks.SecretCheckFailed as exc:
        out(f"test failed: {exc}")
        return 1
    out(f"test passed: {name}")
    return 0


def cmd_rotate(conn, key: bytes, name: str, created: dt.date, expires: dt.date | None, by: str,
               read_value: Callable[[], str], checks: dict, out: Callable[[str], None]) -> int:
    """Check the new value live, then save it. Nothing is written if the check fails."""
    check = checks.get(name)
    if check is None:
        out(f"no test for {name}")
        return 2
    value = read_value()
    try:
        check(value)
    except secret_checks.SecretCheckFailed as exc:
        out(f"not saved: test failed: {exc}")
        return 1
    app_secrets.put(conn, key, name, value, created_on=created, expires_on=expires, updated_by=by)
    if app_secrets.get_value(conn, key, name) != value:
        out("stored, but the read-back check failed; check the master key")
        return 1
    out(f"rotated {name} (...{app_secrets.last4(value)}), created {created}, expires {expires or '-'}")
    return 0


def cmd_service_token(name: str, path: str, out: Callable[[str], None]) -> int:
    """Write a new random token for a service to a file. Never prints the token."""
    if os.path.exists(path):
        print(f"refusing to overwrite existing file: {path}", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(32)
    try:
        with open(path, "x", encoding="utf-8") as f:  # "x": never overwrite
            f.write(token + "\n")
    except FileExistsError:
        print(f"refusing to overwrite existing file: {path}", file=sys.stderr)
        return 1
    out(f"written: {path}")
    return 0


def cmd_import_env(conn, key: bytes, env_values: dict[str, str], by: str, dry_run: bool,
                   out: Callable[[str], None], today: dt.date) -> int:
    planned = [(k, ENV_TO_APP[k], v) for k, v in env_values.items() if k in ENV_TO_APP and v]
    if not planned:
        out("nothing to import: no mapped values in the plaintext file")
        return 0
    for env_name, app_name, _ in planned:
        created, expires = KNOWN_DATES.get(app_name, (today, None))
        out(f"{'would import' if dry_run else 'importing'} {env_name} -> {app_name} (created {created}, expires {expires or '-'})")
    if dry_run:
        return 0
    failures = 0
    for env_name, app_name, value in planned:
        created, expires = KNOWN_DATES.get(app_name, (today, None))
        app_secrets.put(conn, key, app_name, value, created_on=created, expires_on=expires, updated_by=by)
        if app_secrets.get_value(conn, key, app_name) != value:
            failures += 1
            out(f"CHECK FAILED for {app_name}: stored value does not decrypt to the file value")
        else:
            out(f"checked {app_name}: decrypts to the file value")
    out("plaintext file NOT deleted; delete it only after the user confirms" if not failures else "fix the failed checks before deleting anything")
    return 1 if failures else 0


def main(argv: list[str] | None = None, *, conn_factory=None, key_loader=None,
         read_value: Callable[[], str] | None = None, env_values: dict[str, str] | None = None,
         today: dt.date | None = None, out: Callable[[str], None] = print,
         checks: dict | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    m = sub.add_parser("meta"); m.add_argument("name")
    s_ = sub.add_parser("set"); s_.add_argument("name")
    s_.add_argument("--created"); s_.add_argument("--expires"); s_.add_argument("--by", default="admin")
    i = sub.add_parser("import-env"); i.add_argument("--dry-run", action="store_true")
    i.add_argument("--by", default="admin")
    t = sub.add_parser("service-token"); t.add_argument("name", choices=["collector"])
    t.add_argument("--out", required=True)
    te = sub.add_parser("test"); te.add_argument("name")
    r = sub.add_parser("rotate"); r.add_argument("name")
    r.add_argument("--created", required=True); r.add_argument("--expires", required=True)
    r.add_argument("--by", default="admin")
    args = ap.parse_args(argv)
    if checks is None:
        checks = secret_checks.CHECKS

    if args.cmd == "service-token":  # file only: no database connection
        return cmd_service_token(args.name, args.out, out)

    today = today or dt.date.today()
    if conn_factory is None:
        from .pg import db
        conn_factory = db.connect
    if key_loader is None:
        key_loader = secret_crypto.load_master_key

    if args.cmd == "import-env":
        values = env_values if env_values is not None else secrets_store.read()
        key = key_loader() if not args.dry_run else b""
        with conn_factory() as conn:
            code = cmd_import_env(conn, key, values, args.by, args.dry_run, out, today)
            if args.dry_run or code:
                conn.rollback()  # nothing written, or a check failed: leave the table as it was
            else:
                conn.commit()
            return code

    with conn_factory() as conn:
        if args.cmd == "list":
            return cmd_list(conn, out)
        if args.cmd == "meta":
            return cmd_meta(conn, args.name, out)
        if args.cmd == "set":
            name = app_secrets.validate_name(args.name)
            created = _parse_date(args.created) if args.created else today
            expires = None if args.expires in (None, "none") else _parse_date(args.expires)
            reader = read_value or (lambda: getpass.getpass(f"value for {name} (hidden): "))
            code = cmd_set(conn, key_loader(), name, created, expires, args.by, reader, out)
            if code:
                conn.rollback()
            else:
                conn.commit()
            return code
        if args.cmd == "test":
            code = cmd_test(conn, key_loader(), args.name, checks, out)
            conn.rollback()  # test never writes
            return code
        if args.cmd == "rotate":
            created = _parse_date(args.created)
            expires = None if args.expires in (None, "none") else _parse_date(args.expires)
            reader = read_value or (lambda: getpass.getpass(f"new value for {args.name} (hidden): "))
            code = cmd_rotate(conn, key_loader(), args.name, created, expires, args.by, reader, checks, out)
            if code:
                conn.rollback()
            else:
                conn.commit()
            return code
    return 2


if __name__ == "__main__":
    sys.exit(main())
