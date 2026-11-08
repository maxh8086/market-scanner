"""Postgres implementation of announcement and corporate action fetching.

Uses feed_coverage to track fetched windows and only fetch gaps from NSE.
"""
from __future__ import annotations

import functools
import time
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import requests

from scanner.pg.db import connect
from scanner.coverage import missing_windows, record_coverage, required_start

if TYPE_CHECKING:
    import requests


UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# NSE pacing: pause before each request, and a longer pause before a retry.
REQUEST_INTERVAL_SECONDS = 3
RETRY_BACKOFF_SECONDS = 10


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into calendar-month windows so each NSE request is bounded."""
    windows = []
    current = start
    while current <= end:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        window_end = min(next_month - timedelta(days=1), end)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def _fetch_nse_feed(*, feed, gaps, url, save_fn, cached_fn, session, label) -> list[dict]:
    """Fetch every missing month of each gap from NSE.

    A month is recorded in feed_coverage only after it saves successfully, so a
    failed month is retried on the next run. A failed month is retried once after
    a backoff; the loop never aborts, so the whole window is attempted.
    """
    all_rows: list[dict] = []
    for gap_from, gap_to in gaps:
        for win_from, win_to in _month_windows(gap_from, gap_to):
            rows = None
            for attempt in (1, 2):
                time.sleep(REQUEST_INTERVAL_SECONDS if attempt == 1 else RETRY_BACKOFF_SECONDS)
                try:
                    print(f"  Fetching {label}s ({win_from} to {win_to}), attempt {attempt}...")
                    params = {
                        "index": "equities",
                        "from_date": win_from.strftime("%d-%m-%Y"),
                        "to_date": win_to.strftime("%d-%m-%Y"),
                    }
                    resp = session.get(url, params=params, headers=UA, timeout=30)
                    resp.raise_for_status()
                    rows = resp.json()
                    if not isinstance(rows, list):
                        rows = []
                    break
                except Exception as e:
                    print(f"  Error fetching {label}s ({win_from} to {win_to}), attempt {attempt}: {e}")
            if rows is None:
                all_rows.extend(cached_fn(win_from, win_to))
                continue
            try:
                save_fn(rows)
                with connect() as conn:
                    record_coverage(conn, feed, win_from, win_to)
            except Exception as e:
                print(f"  Error saving {label}s ({win_from} to {win_to}): {e}")
                all_rows.extend(cached_fn(win_from, win_to))
                continue
            all_rows.extend(rows)
            print(f"    Fetched {len(rows)} {label} rows")
    return all_rows


def _nse_session() -> requests.Session:
    """Return a session with NSE cookies. A failed warm-up is logged, not fatal."""
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=UA, timeout=30)
    except Exception as e:  # noqa: BLE001 - the API call itself will report the real failure
        print(f"  Warning: NSE cookie warm-up failed: {e}")
    return session


def _parse_date_str(date_str: str) -> date | None:
    """Parse an NSE date string to a date object."""
    if not date_str:
        return None
    from datetime import datetime

    try:
        # ISO, as stored in the cache
        if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
            return date.fromisoformat(date_str[:10])
        # NSE format with time
        if " " in date_str:
            return datetime.strptime(date_str, "%d-%b-%Y %H:%M:%S").date()
        # NSE format without time
        return datetime.strptime(date_str, "%d-%b-%Y").date()
    except (ValueError, TypeError, IndexError):
        return None


def _to_iso(date_str: str) -> str:
    """Convert date string to ISO format, or empty string if unparseable."""
    parsed = _parse_date_str(date_str)
    return parsed.isoformat() if parsed else ""


def _int_or_none(value) -> int | None:
    """Parse size field (may include unit like 'MB')."""
    import re

    _SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    _SIZE_RE = re.compile(r"^([0-9]*\.?[0-9]+)\s*(B|KB|MB|GB)?$", re.I)

    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = _SIZE_RE.match(str(value).strip())
    if not m:
        return None
    number, unit = m.group(1), (m.group(2) or "B").upper()
    try:
        return int(float(number) * _SIZE_UNITS[unit])
    except (TypeError, ValueError, KeyError):
        return None


def was_fetched_today_pg(feed_name: str, from_date: date, to_date: date) -> bool:
    """True when this feed was last fetched today for exactly this window."""
    with connect() as conn:
        row = conn.execute(
            "SELECT from_date, to_date, fetched_at FROM fetch_metadata WHERE feed_name = %s",
            (feed_name,),
        ).fetchone()
    if not row or row["fetched_at"] is None:
        return False
    return (
        row["from_date"] == from_date
        and row["to_date"] == to_date
        and row["fetched_at"].astimezone().date() == date.today()
    )


def mark_fetched_pg(feed_name: str, from_date: date, to_date: date) -> None:
    """Record that this feed was fetched now for this window (one row per feed)."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO fetch_metadata (feed_name, from_date, to_date, fetched_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (feed_name) DO UPDATE SET
                from_date = excluded.from_date,
                to_date = excluded.to_date,
                fetched_at = excluded.fetched_at
            """,
            (feed_name, from_date, to_date, datetime.now().astimezone()),
        )
        conn.commit()


def _save_announcements_pg(rows: list[dict]) -> None:
    """Save announcements to Postgres.

    Dates are written as date objects. A row whose an_dt does not parse is
    skipped: an_dt is NOT NULL and part of the primary key, and such a row
    could never be returned by a date-range read anyway.
    """
    data = []
    for row in rows:
        an_dt = _parse_date_str(row.get("an_dt", ""))
        if an_dt is None:
            continue
        data.append((
            row.get("sm_isin") or "",
            row.get("symbol") or "",
            an_dt,
            row.get("desc") or "",
            row.get("attchmntText") or "",
            _parse_date_str(row.get("sort_date", "")) or an_dt,
            str(row.get("seqId") or row.get("seq_id") or ""),
            row.get("attchmntFile") or "",
            _int_or_none(row.get("attFileSize")),
        ))
    if not data:
        return

    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO announcements
                    (isin, symbol, an_dt, "desc", attchmnt_text, sort_date,
                     seq_id, attchmnt_file, att_file_size)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (isin, an_dt, "desc") DO UPDATE SET
                    seq_id = COALESCE(NULLIF(excluded.seq_id, ''), announcements.seq_id),
                    attchmnt_file = COALESCE(NULLIF(excluded.attchmnt_file, ''), announcements.attchmnt_file),
                    att_file_size = COALESCE(excluded.att_file_size, announcements.att_file_size)
                """,
                data,
            )
        conn.commit()


def _save_corporate_actions_pg(rows: list[dict]) -> None:
    """Save corporate actions to Postgres. A row without a parsable ex_date is skipped
    (ex_date is part of the primary key), as it could never be read back by range."""
    data = []
    for row in rows:
        ex_date = _parse_date_str(row.get("exDate", ""))
        if ex_date is None:
            continue
        data.append((
            row.get("isin") or "",
            row.get("symbol") or "",
            row.get("subject") or "",
            ex_date,
            None,  # received_date
        ))
    if not data:
        return

    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO corporate_actions (isin, symbol, subject, ex_date, received_date)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (isin, ex_date, subject) DO NOTHING
                """,
                data,
            )
        conn.commit()


def _load_cached_announcements_pg(
    from_date: date, to_date: date, symbol: str | None = None
) -> list[dict]:
    """Load cached announcements from Postgres.

    When symbol is given, only that symbol's rows are returned.
    """
    with connect() as conn:
        if symbol is None:
            rows = conn.execute(
                """
                SELECT isin, symbol, an_dt, "desc", attchmnt_text, sort_date,
                       seq_id, attchmnt_file, att_file_size
                FROM announcements
                WHERE sort_date >= %s AND sort_date <= %s
                ORDER BY sort_date
                """,
                (from_date, to_date),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT isin, symbol, an_dt, "desc", attchmnt_text, sort_date,
                       seq_id, attchmnt_file, att_file_size
                FROM announcements
                WHERE sort_date >= %s AND sort_date <= %s AND symbol = %s
                ORDER BY sort_date
                """,
                (from_date, to_date, symbol),
            ).fetchall()

    return [
        {
            "sm_isin": r["isin"],
            "symbol": r["symbol"],
            "an_dt": r["an_dt"].isoformat() if r["an_dt"] else "",
            "desc": r["desc"],
            "attchmntText": r["attchmnt_text"] or "",
            "sort_date": r["sort_date"].isoformat() if r["sort_date"] else "",
            "seqId": r["seq_id"] or "",
            "attchmntFile": r["attchmnt_file"] or "",
            "attFileSize": r["att_file_size"],
        }
        for r in rows
    ]


def _load_cached_corporate_actions_pg(from_date: date, to_date: date) -> list[dict]:
    """Load cached corporate actions from Postgres."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT isin, symbol, subject, ex_date FROM corporate_actions
            WHERE ex_date >= %s AND ex_date <= %s
            ORDER BY ex_date
            """,
            (from_date, to_date),
        ).fetchall()

    return [
        {
            "isin": r["isin"],
            "symbol": r["symbol"],
            "subject": r["subject"],
            "exDate": r["ex_date"].isoformat() if r["ex_date"] else "",
        }
        for r in rows
    ]


def fetch_announcements_pg(
    from_date: date,
    to_date: date,
    session: requests.Session | None = None,
    symbol: str | None = None,
) -> list[dict]:
    """Fetch announcements from NSE using only gaps from feed_coverage.

    Returns list of announcement dicts. When symbol is given, only that
    symbol's rows are returned from cache.
    """
    with connect() as conn:
        gaps = missing_windows(conn, "announcements", from_date, to_date)

    if not gaps:
        # Entire window is covered, load from cache
        return _load_cached_announcements_pg(from_date, to_date, symbol)

    if session is None:
        session = _nse_session()

    # /api/announcements now returns an HTML 404; the corporate-announcements path returns JSON.
    return _fetch_nse_feed(
        feed="announcements",
        gaps=gaps,
        url="https://www.nseindia.com/api/corporate-announcements",
        save_fn=_save_announcements_pg,
        cached_fn=functools.partial(_load_cached_announcements_pg, symbol=symbol),
        session=session,
        label="announcement",
    )


def fetch_corporate_actions_pg(
    from_date: date, to_date: date, session: requests.Session | None = None
) -> list[dict]:
    """Fetch corporate actions from NSE using only gaps from feed_coverage.

    Returns list of corporate action dicts.
    """
    with connect() as conn:
        gaps = missing_windows(conn, "corporate_actions", from_date, to_date)

    if not gaps:
        # Entire window is covered, load from cache
        return _load_cached_corporate_actions_pg(from_date, to_date)

    if session is None:
        session = _nse_session()

    return _fetch_nse_feed(
        feed="corporate_actions",
        gaps=gaps,
        url="https://www.nseindia.com/api/corporates-corporateActions",
        save_fn=_save_corporate_actions_pg,
        cached_fn=_load_cached_corporate_actions_pg,
        session=session,
        label="corporate action",
    )


def collect_announcements(
    symbol: str, listing_date: date | None = None, session: requests.Session | None = None
) -> dict:
    """Collect announcements for a stock, fetching only gaps.

    Args:
        symbol: stock symbol
        listing_date: when the stock was listed (if None, inferred from Postgres)
        session: requests.Session for HTTP calls

    Returns:
        {"fetched": int, "new": int, "from": date|None, "to": date|None}
    """
    today = date.today()

    # Infer listing date if not provided
    if listing_date is None:
        with connect() as conn:
            row = conn.execute(
                "SELECT listing_date FROM symbol_listing WHERE symbol = %s",
                (symbol,),
            ).fetchone()
            listing_date = row["listing_date"] if row else today

    # Required window: max(listing, today-3y) to today
    from_date = required_start(listing_date, today, years=3)

    # Count before
    with connect() as conn:
        before = conn.execute(
            "SELECT COUNT(*) as cnt FROM announcements WHERE symbol = %s",
            (symbol,),
        ).fetchone()["cnt"]

    # Fetch gaps
    rows = fetch_announcements_pg(from_date, today, session, symbol=symbol)

    # Count after
    with connect() as conn:
        after = conn.execute(
            "SELECT COUNT(*) as cnt FROM announcements WHERE symbol = %s",
            (symbol,),
        ).fetchone()["cnt"]

    first_row = min((r for r in rows if r.get("an_dt")), key=lambda x: _to_iso(x.get("an_dt", "")), default=None)
    last_row = max((r for r in rows if r.get("an_dt")), key=lambda x: _to_iso(x.get("an_dt", "")), default=None)

    return {
        "fetched": len(rows),
        "new": after - before,
        "from": _parse_date_str(first_row.get("an_dt")) if first_row else None,
        "to": _parse_date_str(last_row.get("an_dt")) if last_row else None,
    }


def collect_corporate_actions(
    symbol: str, listing_date: date | None = None, session: requests.Session | None = None
) -> dict:
    """Collect corporate actions for a stock, fetching only gaps.

    Args:
        symbol: stock symbol
        listing_date: when the stock was listed (if None, inferred from Postgres)
        session: requests.Session for HTTP calls

    Returns:
        {"fetched": int, "new": int, "from": date|None, "to": date|None}
    """
    today = date.today()

    # Infer listing date if not provided
    if listing_date is None:
        with connect() as conn:
            row = conn.execute(
                "SELECT listing_date FROM symbol_listing WHERE symbol = %s",
                (symbol,),
            ).fetchone()
            listing_date = row["listing_date"] if row else today

    # Corporate actions: 2 years lookback
    from_date = max(listing_date, today - timedelta(days=365 * 2))

    # Count before
    with connect() as conn:
        before = conn.execute(
            "SELECT COUNT(*) as cnt FROM corporate_actions WHERE symbol = %s",
            (symbol,),
        ).fetchone()["cnt"]

    # Fetch gaps
    rows = fetch_corporate_actions_pg(from_date, today, session)

    # Count after
    with connect() as conn:
        after = conn.execute(
            "SELECT COUNT(*) as cnt FROM corporate_actions WHERE symbol = %s",
            (symbol,),
        ).fetchone()["cnt"]

    first_row = min((r for r in rows if r.get("exDate")), key=lambda x: _to_iso(x.get("exDate", "")), default=None)
    last_row = max((r for r in rows if r.get("exDate")), key=lambda x: _to_iso(x.get("exDate", "")), default=None)

    return {
        "fetched": len(rows),
        "new": after - before,
        "from": _parse_date_str(first_row.get("exDate")) if first_row else None,
        "to": _parse_date_str(last_row.get("exDate")) if last_row else None,
    }
