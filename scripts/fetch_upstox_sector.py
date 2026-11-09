"""Fill symbol_sector.upstox_sector from the Upstox company profile.

    python scripts/fetch_upstox_sector.py [--dry-run] [--limit N]

Calls GET https://api.upstox.com/v2/fundamentals/{isin}/profile for every symbol_sector row
with an ISIN, using UPSTOX_ANALYTICS_ACCESS_TOKEN. Writes only upstox_sector and
upstox_sector_as_of. Symbols that fail are left unchanged and listed at the end.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from scanner.pg import db  # noqa: E402

URL = "https://api.upstox.com/v2/fundamentals/{isin}/profile"
PACE_SECONDS = 0.25
MAX_RETRIES = 4
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

UPDATE_SQL = (
    "UPDATE symbol_sector SET upstox_sector = %s, upstox_sector_as_of = %s, updated_at = now() "
    "WHERE symbol = %s"
)


def fetch_sector(session: requests.Session, isin: str) -> tuple[str | None, str | None]:
    """Return (sector, error). Retries on 429 and 5xx."""
    for attempt in range(MAX_RETRIES):
        resp = session.get(URL.format(isin=isin), timeout=30)
        if resp.status_code == 200:
            body = resp.json()
            sector = ((body.get("data") or {}).get("sector") or "").strip()
            return (sector or None, None if sector else "empty sector")
        if resp.status_code in (429, 500, 502, 503) and attempt < MAX_RETRIES - 1:
            time.sleep(2 ** (attempt + 1))
            continue
        return None, f"HTTP {resp.status_code}"
    return None, "retries exhausted"


def main(argv: list[str] | None = None) -> int:
    import os

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and print, write nothing")
    parser.add_argument("--limit", type=int, default=0, help="only the first N symbols (testing)")
    args = parser.parse_args(argv)

    token = os.getenv("UPSTOX_ANALYTICS_ACCESS_TOKEN", "")
    if not token:
        print("error: UPSTOX_ANALYTICS_ACCESS_TOKEN is not set", file=sys.stderr)
        return 1

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT symbol, isin FROM symbol_sector WHERE isin IS NOT NULL ORDER BY symbol"
        ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Authorization": f"Bearer {token}"})
    as_of = dt.datetime.now(IST).date()

    ok, failed, results = 0, [], []
    for symbol, isin in ((r["symbol"], r["isin"]) for r in rows):
        sector, error = fetch_sector(session, isin)
        time.sleep(PACE_SECONDS)
        if error:
            failed.append((symbol, error))
            continue
        ok += 1
        results.append((sector, as_of, symbol))

    print(f"fetched {ok} of {len(rows)} symbols; {len(failed)} failed")
    if args.dry_run:
        print("dry run: nothing written")
    elif results:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(UPDATE_SQL, results)
        print(f"wrote upstox_sector for {len(results)} rows as_of {as_of.isoformat()}")
    for symbol, error in failed:
        print(f"  failed {symbol}: {error}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
