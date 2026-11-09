"""Load the NSE Total Market Industry column into Postgres table symbol_sector.

    python scanner/symbol_sector.py [--dry-run] [--csv PATH]
    python -m scanner.symbol_sector [--dry-run] [--csv PATH]    (inside the scanner image)

Reads data/ind_niftytotalmarket_list.csv (the cache written by scanner/constituents.py).
The whole file is validated before anything is written; a bad file exits 1 with no rows
written. Rows are upserted by symbol and set nse_industry, isin and as_of.

sub_sector and sub_sector_source are the user's mapping. The upsert never names them,
so a re-run cannot overwrite them. Rows that were in the table before and are no longer
in the file are left alone; nothing is deleted.

--dry-run validates the file and prints counts. It does not connect to the database.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CSV = ROOT / "data" / "ind_niftytotalmarket_list.csv"

# NSE dates are Indian. IST has no daylight saving, so a fixed offset is exact and needs no tz database.
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# Column names in the NSE file. Verified against the cached file (755 rows, 22 industries).
REQUIRED_HEADERS = ("Symbol", "ISIN Code", "Industry")

# Only the NSE-owned columns appear here. sub_sector and sub_sector_source are deliberately absent.
UPSERT_SQL = (
    "INSERT INTO symbol_sector (symbol, isin, nse_industry, as_of, updated_at) "
    "VALUES (%s, %s, %s, %s, now()) "
    "ON CONFLICT (symbol) DO UPDATE SET "
    "isin = EXCLUDED.isin, "
    "nse_industry = EXCLUDED.nse_industry, "
    "as_of = EXCLUDED.as_of, "
    "updated_at = now()"
)


class BadCsv(ValueError):
    """The sector file cannot be loaded."""


def parse_csv(path: Path) -> list[tuple[str, str, str]]:
    """Return [(symbol, isin, industry)] for the file. Raises BadCsv on any problem."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise BadCsv(f"{path.name}: cannot read as UTF-8 text ({exc})") from None
    reader = csv.DictReader(text.splitlines())
    fields = [f.strip() for f in (reader.fieldnames or [])]
    missing = [h for h in REQUIRED_HEADERS if h not in fields]
    if missing:
        raise BadCsv(f"{path.name}: header is missing {missing} (found {fields})")

    rows: list[tuple[str, str, str]] = []
    seen_symbols: set[str] = set()
    seen_isins: set[str] = set()
    for lineno, rec in enumerate(reader, start=2):
        symbol = (rec.get("Symbol") or "").strip()
        isin = (rec.get("ISIN Code") or "").strip()
        industry = (rec.get("Industry") or "").strip()
        if symbol.upper().startswith("DUMMY"):
            continue  # placeholder rows, same rule as scanner/constituents.py
        if not symbol:
            raise BadCsv(f"{path.name}: line {lineno} has no Symbol")
        if not isin:
            raise BadCsv(f"{path.name}: line {lineno} ({symbol}) has no ISIN Code")
        if not industry:
            raise BadCsv(f"{path.name}: line {lineno} ({symbol}) has no Industry")
        if symbol in seen_symbols:
            raise BadCsv(f"{path.name}: line {lineno} repeats Symbol {symbol}")
        if isin in seen_isins:
            raise BadCsv(f"{path.name}: line {lineno} repeats ISIN {isin}")
        seen_symbols.add(symbol)
        seen_isins.add(isin)
        rows.append((symbol, isin, industry))
    if not rows:
        raise BadCsv(f"{path.name}: zero data rows")
    return rows


def today_ist(now: dt.datetime | None = None) -> dt.date:
    """The IST calendar date. The container clock is UTC, so date.today() can be a day behind."""
    moment = now if now is not None else dt.datetime.now(IST)
    return moment.astimezone(IST).date()


def write_rows(rows: list[tuple[str, str, str]], as_of: dt.date) -> int:
    """Upsert every row in one transaction. Returns the number of rows sent."""
    from scanner.pg import db  # imported here so --dry-run never needs psycopg or a DSN

    params = [(symbol, isin, industry, as_of) for symbol, isin, industry in rows]
    with db.connect() as conn:  # psycopg commits on clean exit, rolls back on error
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, params)
    return len(params)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="path to the NSE constituents CSV")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and print counts; write nothing, do not connect")
    args = parser.parse_args(argv)

    try:
        rows = parse_csv(args.csv)
    except BadCsv as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for _, _, industry in rows:
        counts[industry] = counts.get(industry, 0) + 1
    print(f"{len(rows)} symbols in {len(counts)} NSE industries from {args.csv.name}")

    if args.dry_run:
        print("dry run: nothing written")
        return 0

    as_of = today_ist()
    sent = write_rows(rows, as_of)
    print(f"upserted {sent} rows into symbol_sector as_of {as_of.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
