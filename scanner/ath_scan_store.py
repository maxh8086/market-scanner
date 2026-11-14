"""Machine store for the ATH scan candidates (table ath_scan_candidates, migration 060).

ath_scan writes one row per candidate per scan date. The readers (portfolio.py, crosscheck.py and
the collector's AthScan source) read the newest scan date back. Column names and order are the CSV
columns of scanner/report.py, so a reader gets the frame it used to read from
output/ath_scan_<date>.csv.

Connections are passed in by the caller; connect() opens one from scanner.pg.db.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from scanner import report

TABLE = "ath_scan_candidates"
DEFAULT_RETENTION_DAYS = 90

# The CSV columns, in the order report.write_outputs writes them, plus isin right after company.
# ath_scan has isin in memory but the CSV drops it; the table keeps it for the Filings reader.
_BASE_WITH_ISIN: list[str] = list(report.BASE_COLUMNS)
_BASE_WITH_ISIN.insert(_BASE_WITH_ISIN.index("company") + 1, "isin")
ATH_SCAN_COLUMNS: list[str] = _BASE_WITH_ISIN + list(report.TREND_COLUMNS) + list(report.FACTOR_COLUMNS)
NUMERIC_COLUMNS: tuple[str, ...] = ("ltp", "today_high", "ath_high", "ath_close", "distance_pct", "ema50", "sma200")
INTEGER_COLUMNS: tuple[str, ...] = ("days_since_ath", "listed_days", "factors_matched")
TEXT_COLUMNS: tuple[str, ...] = tuple(
    c for c in ATH_SCAN_COLUMNS if c not in NUMERIC_COLUMNS and c not in INTEGER_COLUMNS
)


def connect():
    """A new connection to the main database (scanner.pg.db.connect). The caller commits or closes."""
    from scanner.pg import db

    return db.connect()


def _is_missing(value) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _to_db(column: str, value):
    """One frame value as the database value: '' for missing text, NULL for missing numbers."""
    if column in TEXT_COLUMNS:
        return "" if _is_missing(value) else str(value)
    if _is_missing(value):
        return None
    if column in INTEGER_COLUMNS:
        return int(value)
    return float(value)


def _first(row):
    """The first value of a row, for dict rows (the db.connect row factory) and tuple rows."""
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def write_scan(conn, scan_date: date, df: pd.DataFrame, run_id: Optional[str] = None,
               retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Replace the candidates of scan_date with df, prune older rows, return the rows inserted.

    One transaction: delete the scan date's rows, insert df, delete rows older than
    scan_date minus retention_days. An empty frame writes nothing and returns 0, so an earlier
    good run of the same day is kept; the caller decides that zero rows is a failure.
    A duplicate symbol raises (primary key), as does a bad run_id.
    """
    if df is None or df.empty:
        return 0
    run_uuid = uuid.UUID(str(run_id)) if run_id else None
    frame = df.reindex(columns=ATH_SCAN_COLUMNS)  # columns absent from df become missing values
    records = [
        (scan_date, run_uuid, *[_to_db(col, val) for col, val in zip(ATH_SCAN_COLUMNS, row)])
        for row in frame.itertuples(index=False, name=None)
    ]
    cols = ["scan_date", "run_id", *ATH_SCAN_COLUMNS]
    insert_sql = (f"INSERT INTO {TABLE} ({', '.join(cols)}) "
                  f"VALUES ({', '.join(['%s'] * len(cols))})")
    with conn.transaction():
        conn.execute(f"DELETE FROM {TABLE} WHERE scan_date = %s", (scan_date,))
        with conn.cursor() as cur:
            cur.executemany(insert_sql, records)
        conn.execute(f"DELETE FROM {TABLE} WHERE scan_date < %s",
                     (scan_date - timedelta(days=retention_days),))
    return len(records)


def latest_scan_date(conn, as_of: Optional[date] = None) -> Optional[date]:
    """The newest scan_date (<= as_of when given), or None when there is no matching row."""
    if as_of is None:
        row = conn.execute(f"SELECT max(scan_date) AS d FROM {TABLE}").fetchone()
    else:
        row = conn.execute(f"SELECT max(scan_date) AS d FROM {TABLE} WHERE scan_date <= %s",
                           (as_of,)).fetchone()
    return _first(row)


def read_latest_scan(conn, as_of: Optional[date] = None) -> Optional[tuple[pd.DataFrame, date]]:
    """The candidates of the newest scan date, as the CSV frame, and that date. None when empty.

    Text columns stay str with '' kept (the effect of keep_default_na=False). Numeric columns are
    float with NaN for NULL; integer columns are Int64. Rows are sorted as report.write_outputs
    sorted them.
    """
    scan_date = latest_scan_date(conn, as_of)
    if scan_date is None:
        return None
    rows = conn.execute(
        f"SELECT {', '.join(ATH_SCAN_COLUMNS)} FROM {TABLE} WHERE scan_date = %s", (scan_date,)
    ).fetchall()
    if not rows:
        return None
    frame = pd.DataFrame(rows, columns=ATH_SCAN_COLUMNS)
    for col in TEXT_COLUMNS:
        frame[col] = frame[col].map(lambda v: "" if _is_missing(v) else str(v))
    for col in NUMERIC_COLUMNS:
        frame[col] = frame[col].astype("float64")
    for col in INTEGER_COLUMNS:
        frame[col] = frame[col].astype("Int64")
    return report.sort_results(frame), scan_date


def scan_row_count(conn, scan_date: date) -> int:
    """The number of candidate rows stored for scan_date."""
    row = conn.execute(f"SELECT count(*) AS n FROM {TABLE} WHERE scan_date = %s", (scan_date,)).fetchone()
    return int(_first(row))


def as_csv_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Give a read_latest_scan frame the dtypes pd.read_csv gave the CSV it replaces.

    read_csv turns a text column whose every value is 'True' or 'False' into bool; a column with
    any other value (such as an empty cell) stays text. The table keeps the text, so this applies
    the same rule. Only the readers that compare these columns with booleans need it.
    """
    out = frame.copy()
    for col in TEXT_COLUMNS:
        values = set(out[col].unique())
        if values and values <= {"True", "False"}:
            out[col] = out[col].map({"True": True, "False": False})
    return out


def main(argv: Optional[list[str]] = None) -> int:
    """`python -m scanner.ath_scan_store latest`: print 'YYYY-MM-DD <rows>' for the newest scan.

    Exit 0 with that one line on stdout. Exit 2 with nothing on stdout when the table has no rows
    or Postgres cannot be reached; the reason goes to stderr.
    """
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["latest"]:
        print("usage: python -m scanner.ath_scan_store latest", file=sys.stderr)
        return 2
    from scanner.pg import db

    try:
        if not db.available():
            raise RuntimeError("Postgres is not configured")
        with connect() as conn:
            scan_date = latest_scan_date(conn)
            rows = scan_row_count(conn, scan_date) if scan_date else 0
    except Exception as exc:  # noqa: BLE001 - any failure is the same answer to start.ps1
        print(f"ath_scan_candidates unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2
    if not rows:
        print("ath_scan_candidates has no rows", file=sys.stderr)
        return 2
    print(f"{scan_date.isoformat()} {rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
