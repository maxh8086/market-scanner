"""Load NSE index constituent CSVs into Postgres table constituent_membership.

    python scanner/constituent_membership.py [--dry-run]
    python -m scanner.constituent_membership [--dry-run]     (inside the scanner image)

Reads data/constituents/nifty_*.csv (written by scripts/fetch_index_constituents.py).
Each file is validated completely before anything is written; a bad file aborts the
whole run with exit 1 and no rows are written. Rows are upserted with as_of = today.
Nothing is deleted, and index_membership is never touched.

--dry-run validates the files and prints per-index row counts. It does not connect
to the database.
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

DATA_DIR = ROOT / "data" / "constituents"

# slug -> index name. Names match INDICES in scripts/fetch_index_constituents.py.
# Duplicated here because the scanner image does not ship the scripts/ folder.
SLUG_TO_INDEX = {
    "nifty_50": "Nifty 50",
    "nifty_next_50": "Nifty Next 50",
    "nifty_midcap_150": "Nifty Midcap 150",
    "nifty_smallcap_250": "Nifty Smallcap 250",
    "nifty_microcap_250": "Nifty Microcap 250",
    "nifty_bank": "Nifty Bank",
}

UPSERT_SQL = (
    "INSERT INTO constituent_membership (index_name, isin, symbol, as_of) "
    "VALUES (%s, %s, %s, %s) "
    "ON CONFLICT (index_name, isin, as_of) DO UPDATE SET symbol = EXCLUDED.symbol"
)


class BadCsv(ValueError):
    """A constituent file that cannot be loaded."""


def parse_csv(path: Path) -> list[tuple[str, str]]:
    """Return [(isin, symbol)] for one file. Raises BadCsv on any problem."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise BadCsv(f"{path.name}: cannot read as UTF-8 text ({exc})") from None
    reader = csv.DictReader(text.splitlines())
    fields = [f.strip() for f in (reader.fieldnames or [])]
    if "Symbol" not in fields or "ISIN Code" not in fields:
        raise BadCsv(f"{path.name}: header must include 'Symbol' and 'ISIN Code' (found {fields})")
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for lineno, rec in enumerate(reader, start=2):
        isin = (rec.get("ISIN Code") or "").strip()
        symbol = (rec.get("Symbol") or "").strip()
        if not isin:
            raise BadCsv(f"{path.name}: line {lineno} has no ISIN Code")
        if isin in seen:
            raise BadCsv(f"{path.name}: line {lineno} repeats ISIN {isin}")
        seen.add(isin)
        rows.append((isin, symbol))
    if not rows:
        raise BadCsv(f"{path.name}: zero data rows")
    return rows


def load_all(data_dir: Path = DATA_DIR) -> dict[str, list[tuple[str, str]]]:
    """Validate every known constituent file. Returns {index_name: rows}.

    Raises BadCsv before anything is returned, so the caller writes nothing on error.
    """
    files = sorted(data_dir.glob("nifty_*.csv"))
    if not files:
        raise BadCsv(f"no nifty_*.csv files in {data_dir}")
    result: dict[str, list[tuple[str, str]]] = {}
    for path in files:
        index_name = SLUG_TO_INDEX.get(path.stem)
        if index_name is None:
            print(f"skipping {path.name}: no index name mapped for this file", file=sys.stderr)
            continue
        result[index_name] = parse_csv(path)
    if not result:
        raise BadCsv(f"no mapped constituent files in {data_dir}")
    return result


def write_rows(data: dict[str, list[tuple[str, str]]], as_of: dt.date) -> int:
    """Upsert every row in one transaction. Returns the number of rows sent."""
    from scanner.pg import db  # imported here so --dry-run never needs psycopg or a DSN

    params = [
        (index_name, isin, symbol, as_of)
        for index_name, rows in data.items()
        for isin, symbol in rows
    ]
    with db.connect() as conn:  # psycopg commits on clean exit, rolls back on error
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, params)
    return len(params)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and print row counts; write nothing, do not connect")
    args = parser.parse_args(argv)

    try:
        data = load_all()
    except BadCsv as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    as_of = dt.date.today()
    total = 0
    for index_name, rows in data.items():
        total += len(rows)
        print(f"{index_name}: {len(rows)} rows as_of {as_of.isoformat()}")

    if args.dry_run:
        print(f"dry run: {total} rows across {len(data)} indices; nothing written")
        return 0

    try:
        sent = write_rows(data, as_of)
    except Exception as exc:  # noqa: BLE001 - report any DB failure as exit 1
        print(f"error: database write failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"upserted {sent} rows as_of {as_of.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
