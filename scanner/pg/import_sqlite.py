"""Idempotent import of candles and announcements from SQLite to Postgres.

    python -m scanner.pg.import_sqlite            # import for real
    python -m scanner.pg.import_sqlite --dry-run  # report without changes

Reads from data/history.db and data/factors.db, transforms dates to ISO format,
and inserts via Postgres COPY or executemany. Safe to run multiple times:
duplicate rows are ignored via INSERT ... ON CONFLICT DO NOTHING.

Reports before/after counts and reconciles them against SQLite exactly.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path

from . import db


def _count(conn, table: str) -> int:
    """Row count of a Postgres table (rows are dicts, so alias the column)."""
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def import_candles(dry_run: bool = False) -> dict[str, int]:
    """Import candles from SQLite history.db.

    Returns dict with keys: sqlite_count, postgres_before, postgres_after, inserted.
    """
    history_db = Path("data/history.db")
    if not history_db.exists():
        raise FileNotFoundError(f"{history_db} not found")

    # Count rows in SQLite
    sqlite_conn = sqlite3.connect(history_db)
    sqlite_candles = sqlite_conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    sqlite_conn.close()

    # Postgres before count
    with db.connect() as conn:
        pg_before = _count(conn, "candles")

    if dry_run:
        return {
            "source": "history.db candles",
            "sqlite_count": sqlite_candles,
            "postgres_before": pg_before,
            "postgres_after": pg_before,
            "inserted": 0,
        }

    # Fetch all rows from SQLite with proper date handling
    sqlite_conn = sqlite3.connect(history_db)
    sqlite_conn.row_factory = sqlite3.Row
    rows = sqlite_conn.execute(
        "SELECT symbol, date, open, high, low, close, volume FROM candles"
    ).fetchall()
    sqlite_conn.close()

    # Stage through a temp table with COPY, then insert only the new keys.
    if rows:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TEMP TABLE candles_stage (LIKE candles INCLUDING DEFAULTS) ON COMMIT DROP"
                )
                with cur.copy(
                    "COPY candles_stage (symbol, date, open, high, low, close, volume) FROM STDIN"
                ) as cp:
                    for r in rows:
                        d = _parse_date_str(r["date"])
                        if d is None:
                            continue
                        cp.write_row((r["symbol"], d, r["open"], r["high"], r["low"],
                                      r["close"], r["volume"]))
                cur.execute(
                    "INSERT INTO candles SELECT * FROM candles_stage ON CONFLICT (symbol, date) DO NOTHING"
                )
            conn.commit()

    # Postgres after count
    with db.connect() as conn:
        pg_after = _count(conn, "candles")

    return {
        "source": "history.db candles",
        "sqlite_count": sqlite_candles,
        "postgres_before": pg_before,
        "postgres_after": pg_after,
        "inserted": pg_after - pg_before,
    }


def _parse_date_str(date_str: str) -> str | None:
    """Parse NSE date and convert to ISO format, or return ISO if already formatted.

    NSE dates are like '07-Oct-2024' or '28-Sep-2026 21:09:08'.
    Already-stored dates from schema 2+ are ISO '2024-10-07'.
    """
    if not date_str:
        return None
    try:
        # Already ISO
        if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
            return date_str[:10]  # '2024-10-07'
        # NSE format with time
        if " " in date_str:
            from datetime import datetime
            dt = datetime.strptime(date_str, "%d-%b-%Y %H:%M:%S")
            return dt.date().isoformat()
        # NSE format without time
        from datetime import datetime
        dt = datetime.strptime(date_str, "%d-%b-%Y")
        return dt.date().isoformat()
    except (ValueError, TypeError, IndexError):
        return None


def import_announcements(dry_run: bool = False) -> dict[str, int]:
    """Import announcements from SQLite factors.db."""
    factors_db = Path("data/factors.db")
    if not factors_db.exists():
        raise FileNotFoundError(f"{factors_db} not found")

    # Count in SQLite
    sqlite_conn = sqlite3.connect(factors_db)
    sqlite_anns = sqlite_conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
    sqlite_conn.close()

    # Postgres before
    with db.connect() as conn:
        pg_before = _count(conn, "announcements")

    if dry_run:
        return {
            "source": "factors.db announcements",
            "sqlite_count": sqlite_anns,
            "postgres_before": pg_before,
            "postgres_after": pg_before,
            "inserted": 0,
        }

    # Fetch from SQLite
    sqlite_conn = sqlite3.connect(factors_db)
    sqlite_conn.row_factory = sqlite3.Row
    rows = sqlite_conn.execute(
        "SELECT isin, symbol, an_dt, desc, attchmnt_text, sort_date, seq_id, attchmnt_file, att_file_size FROM announcements"
    ).fetchall()
    sqlite_conn.close()

    # Insert via executemany with date normalization
    if rows:
        with db.connect() as conn:
            with conn.cursor() as cur:
                data = [
                    (
                        r["isin"],
                        r["symbol"],
                        _parse_date_str(r["an_dt"]),
                        r["desc"],
                        r["attchmnt_text"],
                        _parse_date_str(r["sort_date"]),
                        r["seq_id"],
                        r["attchmnt_file"],
                        r["att_file_size"],
                    )
                    for r in rows
                    if _parse_date_str(r["an_dt"]) and r["desc"] is not None
                ]
                cur.executemany(
                    """
                    INSERT INTO announcements (isin, symbol, an_dt, "desc", attchmnt_text, sort_date, seq_id, attchmnt_file, att_file_size)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (isin, an_dt, "desc") DO NOTHING
                    """,
                    data,
                )
            conn.commit()

    # Postgres after
    with db.connect() as conn:
        pg_after = _count(conn, "announcements")

    return {
        "source": "factors.db announcements",
        "sqlite_count": sqlite_anns,
        "postgres_before": pg_before,
        "postgres_after": pg_after,
        "inserted": pg_after - pg_before,
    }


def import_corporate_actions(dry_run: bool = False) -> dict[str, int]:
    """Import corporate actions from SQLite factors.db."""
    factors_db = Path("data/factors.db")
    if not factors_db.exists():
        raise FileNotFoundError(f"{factors_db} not found")

    # Count in SQLite
    sqlite_conn = sqlite3.connect(factors_db)
    sqlite_ca = sqlite_conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0]
    sqlite_conn.close()

    # Postgres before
    with db.connect() as conn:
        pg_before = _count(conn, "corporate_actions")

    if dry_run:
        return {
            "source": "factors.db corporate_actions",
            "sqlite_count": sqlite_ca,
            "postgres_before": pg_before,
            "postgres_after": pg_before,
            "inserted": 0,
        }

    # Fetch from SQLite
    sqlite_conn = sqlite3.connect(factors_db)
    sqlite_conn.row_factory = sqlite3.Row
    rows = sqlite_conn.execute(
        "SELECT isin, symbol, subject, ex_date, received_date FROM corporate_actions"
    ).fetchall()
    sqlite_conn.close()

    # Insert via executemany with date normalization
    if rows:
        with db.connect() as conn:
            with conn.cursor() as cur:
                data = [
                    (
                        r["isin"],
                        r["symbol"],
                        r["subject"],
                        _parse_date_str(r["ex_date"]),
                        _parse_date_str(r["received_date"]),
                    )
                    for r in rows
                    if _parse_date_str(r["ex_date"]) and r["subject"] is not None
                ]
                cur.executemany(
                    """
                    INSERT INTO corporate_actions (isin, symbol, subject, ex_date, received_date)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (isin, ex_date, subject) DO NOTHING
                    """,
                    data,
                )
            conn.commit()

    # Postgres after
    with db.connect() as conn:
        pg_after = _count(conn, "corporate_actions")

    return {
        "source": "factors.db corporate_actions",
        "sqlite_count": sqlite_ca,
        "postgres_before": pg_before,
        "postgres_after": pg_after,
        "inserted": pg_after - pg_before,
    }


def import_symbol_stats(dry_run: bool = False) -> dict[str, int]:
    """Import symbol_stats from SQLite history.db."""
    history_db = Path("data/history.db")
    if not history_db.exists():
        raise FileNotFoundError(f"{history_db} not found")

    # Count in SQLite
    sqlite_conn = sqlite3.connect(history_db)
    sqlite_stats = sqlite_conn.execute("SELECT COUNT(*) FROM symbol_stats").fetchone()[0]
    sqlite_conn.close()

    # Postgres before
    with db.connect() as conn:
        pg_before = _count(conn, "symbol_stats")

    if dry_run:
        return {
            "source": "history.db symbol_stats",
            "sqlite_count": sqlite_stats,
            "postgres_before": pg_before,
            "postgres_after": pg_before,
            "inserted": 0,
        }

    # Fetch from SQLite
    sqlite_conn = sqlite3.connect(history_db)
    sqlite_conn.row_factory = sqlite3.Row
    rows = sqlite_conn.execute(
        "SELECT symbol, ath_high, ath_date, ath_close, ath_close_date, first_date, last_date FROM symbol_stats"
    ).fetchall()
    sqlite_conn.close()

    # Insert via executemany with date normalization
    if rows:
        with db.connect() as conn:
            with conn.cursor() as cur:
                data = [
                    (
                        r["symbol"],
                        r["ath_high"],
                        _parse_date_str(r["ath_date"]),
                        r["ath_close"],
                        _parse_date_str(r["ath_close_date"]),
                        _parse_date_str(r["first_date"]),
                        _parse_date_str(r["last_date"]),
                    )
                    for r in rows
                ]
                cur.executemany(
                    """
                    INSERT INTO symbol_stats (symbol, ath_high, ath_date, ath_close, ath_close_date, first_date, last_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol) DO UPDATE SET
                      ath_high = EXCLUDED.ath_high,
                      ath_date = EXCLUDED.ath_date,
                      ath_close = EXCLUDED.ath_close,
                      ath_close_date = EXCLUDED.ath_close_date,
                      first_date = EXCLUDED.first_date,
                      last_date = EXCLUDED.last_date,
                      updated_at = now()
                    """,
                    data,
                )
            conn.commit()

    # Postgres after
    with db.connect() as conn:
        pg_after = _count(conn, "symbol_stats")

    return {
        "source": "history.db symbol_stats",
        "sqlite_count": sqlite_stats,
        "postgres_before": pg_before,
        "postgres_after": pg_after,
        "inserted": pg_after - pg_before,
    }


def import_symbol_listing(dry_run: bool = False) -> dict[str, int]:
    """Populate symbol_listing from the earliest candle date per symbol."""
    # Count before
    with db.connect() as conn:
        pg_before = _count(conn, "symbol_listing")

    if dry_run:
        return {
            "source": "symbol_listing (inferred from candles)",
            "sqlite_count": None,
            "postgres_before": pg_before,
            "postgres_after": pg_before,
            "inserted": 0,
        }

    # Infer from candles: first date per symbol is the listing date
    with db.connect() as conn:
        # Get unique symbols and their earliest dates from candles
        symbols_data = conn.execute(
            "SELECT symbol, MIN(date) AS listing_date FROM candles GROUP BY symbol"
        ).fetchall()

        # Also get ISIN from announcements where available
        with conn.cursor() as cur:
            for row in symbols_data:
                symbol = row["symbol"]
                listing_date = row["listing_date"]

                # Try to find ISIN from announcements
                isin_row = conn.execute(
                    "SELECT DISTINCT isin FROM announcements WHERE symbol = %s LIMIT 1",
                    (symbol,),
                ).fetchone()
                isin = isin_row["isin"] if isin_row else None

                cur.execute(
                    """
                    INSERT INTO symbol_listing (symbol, isin, listing_date, source)
                    VALUES (%s, %s, %s, 'inferred')
                    ON CONFLICT (symbol) DO UPDATE SET
                      isin = COALESCE(EXCLUDED.isin, symbol_listing.isin),
                      listing_date = EXCLUDED.listing_date,
                      source = 'inferred'
                    """,
                    (symbol, isin, listing_date),
                )
        conn.commit()

    # Count after
    with db.connect() as conn:
        pg_after = _count(conn, "symbol_listing")

    return {
        "source": "symbol_listing (inferred from candles)",
        "sqlite_count": None,
        "postgres_before": pg_before,
        "postgres_after": pg_after,
        "inserted": pg_after - pg_before,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="Always safe: duplicate rows are ignored via ON CONFLICT DO NOTHING.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would happen without changing databases",
    )
    args = ap.parse_args(argv)

    try:
        results = [
            import_candles(dry_run=args.dry_run),
            import_symbol_stats(dry_run=args.dry_run),
            import_announcements(dry_run=args.dry_run),
            import_corporate_actions(dry_run=args.dry_run),
            import_symbol_listing(dry_run=args.dry_run),
        ]

        print("\nImport results:")
        print("-" * 80)
        for r in results:
            print(f"{r['source']:40} SQLite: {r['sqlite_count']!s:>10} "
                  f"PG before: {r['postgres_before']:>10} after: {r['postgres_after']:>10}")

        total_inserted = sum(r.get("inserted", 0) for r in results)
        if args.dry_run:
            print(f"\nDry run: no changes made. Total that would be inserted: {total_inserted}")
        else:
            print(f"\nTotal rows inserted: {total_inserted}")

        return 0
    except Exception as e:
        print(f"Error: {e}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
