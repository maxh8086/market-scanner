"""Fill the screener_* classification columns on symbol_sector from Screener company pages.

    python scripts/fetch_screener_sector.py [--dry-run] [--limit N]

Fetches /company/{symbol}/ with scanner.screener.Client (paced), parses the breadcrumb with
parse_sector_path, and writes only screener_sector, screener_industry,
screener_basic_industry, screener_sub_industry and screener_as_of. A page that is missing or
has no breadcrumb leaves the row unchanged and is listed at the end.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from scanner import screener  # noqa: E402
from scanner.pg import db  # noqa: E402

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

UPDATE_SQL = (
    "UPDATE symbol_sector SET screener_sector = %s, screener_industry = %s, "
    "screener_basic_industry = %s, screener_sub_industry = %s, screener_as_of = %s, "
    "updated_at = now() WHERE symbol = %s"
)


async def collect(symbols: list[str]) -> tuple[list[tuple], list[tuple[str, str]]]:
    results, failed = [], []
    async with screener.Client() as client:
        for symbol in symbols:
            try:
                html = await client.get_html(f"/company/{symbol}/")
            except screener.ScreenerError as exc:
                failed.append((symbol, str(exc)))
                continue
            if html is None:
                failed.append((symbol, "404"))
                continue
            path = screener.parse_sector_path(html)
            if not path["screener_sector"]:
                failed.append((symbol, "no breadcrumb"))
                continue
            results.append((symbol, path))
    return results, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and parse; write nothing")
    parser.add_argument("--limit", type=int, default=0, help="only the first N symbols (testing)")
    args = parser.parse_args(argv)

    with db.connect() as conn:
        symbols = [r["symbol"] for r in conn.execute(
            "SELECT symbol FROM symbol_sector ORDER BY symbol").fetchall()]
    if args.limit:
        symbols = symbols[: args.limit]

    results, failed = asyncio.run(collect(symbols))
    as_of = dt.datetime.now(IST).date()
    print(f"parsed {len(results)} of {len(symbols)} symbols; {len(failed)} failed")
    if args.dry_run:
        print("dry run: nothing written")
    elif results:
        params = [
            (p["screener_sector"], p["screener_industry"], p["screener_basic_industry"],
             p["screener_sub_industry"], as_of, symbol)
            for symbol, p in results
        ]
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(UPDATE_SQL, params)
        print(f"wrote screener_* for {len(params)} rows as_of {as_of.isoformat()}")
    for symbol, reason in failed:
        print(f"  failed {symbol}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
