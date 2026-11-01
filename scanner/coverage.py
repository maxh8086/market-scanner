"""Feed coverage tracking and gap detection for incremental fetches.

Tracks which date windows have been fetched from each data source (NSE announcements,
corporate actions, etc.) so collectors can fetch only gaps rather than the entire
history every time.

Coverage is recorded as a set of non-overlapping windows per feed. Gaps are
computed by subtracting recorded coverage from the required window.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.pg.db import ConnectionType


def required_start(listing_date: date, today: date, years: int = 3) -> date:
    """Start of the required coverage window for a stock.

    Returns the maximum of:
      - the stock's listing date (or first trade date if not known)
      - today minus the lookback window

    Args:
        listing_date: when the stock was listed (or first candle date as fallback)
        today: current date
        years: lookback window in years (default 3)

    Returns:
        The earliest date that should be covered by the current data fetch.
    """
    try:
        cutoff = today.replace(year=today.year - years)
    except ValueError:  # 29 February
        cutoff = today.replace(year=today.year - years, day=28)
    return max(listing_date, cutoff)


def missing_windows(conn, feed: str, need_from: date, need_to: date) -> list[tuple[date, date]]:
    """Date windows not yet fetched for a feed.

    Subtracts recorded coverage in feed_coverage from the required window,
    returning a list of disjoint gaps that should be fetched.

    Args:
        conn: Postgres connection
        feed: feed name (e.g. 'announcements', 'corporate_actions', 'candles_eod')
        need_from: start of the required window (inclusive)
        need_to: end of the required window (inclusive)

    Returns:
        List of (from_date, to_date) tuples representing unfetched windows.
        Empty list if the entire window is covered.
    """
    # Fetch all coverage for this feed, sorted
    rows = conn.execute(
        "SELECT from_date, to_date FROM feed_coverage WHERE feed = %s ORDER BY from_date, to_date",
        (feed,),
    ).fetchall()

    if not rows:
        return [(need_from, need_to)]

    # Merge overlapping/adjacent windows (coverage might have overlaps from retries)
    merged = []
    for row in rows:
        # Handle both dict-like rows (from Postgres) and tuples (from tests)
        if isinstance(row, dict):
            from_dt, to_dt = row["from_date"], row["to_date"]
        else:
            from_dt, to_dt = row

        if not merged or merged[-1][1] < from_dt - timedelta(days=1):
            merged.append((from_dt, to_dt))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], to_dt))

    # Find gaps
    gaps = []

    # Gap before the first coverage window
    if merged[0][0] > need_from:
        gaps.append((need_from, merged[0][0] - timedelta(days=1)))

    # Gaps between coverage windows
    for i in range(len(merged) - 1):
        gap_from = merged[i][1] + timedelta(days=1)
        gap_to = merged[i + 1][0] - timedelta(days=1)
        if gap_from <= gap_to:
            gaps.append((gap_from, gap_to))

    # Gap after the last coverage window
    if merged[-1][1] < need_to:
        gaps.append((merged[-1][1] + timedelta(days=1), need_to))

    return gaps


def record_coverage(conn, feed: str, from_date: date, to_date: date) -> None:
    """Record that a feed window has been fetched.

    Merges overlapping windows so the coverage table stays lean.

    Args:
        conn: Postgres connection
        feed: feed name
        from_date: start of fetched window (inclusive)
        to_date: end of fetched window (inclusive)
    """
    # Insert the new window
    conn.execute(
        "INSERT INTO feed_coverage (feed, from_date, to_date) VALUES (%s, %s, %s)",
        (feed, from_date, to_date),
    )

    # Merge overlapping windows: find all windows that touch or overlap the new one,
    # delete them, and insert a single merged window
    overlapping = conn.execute(
        "SELECT from_date, to_date FROM feed_coverage "
        "WHERE feed = %s AND NOT (to_date < %s OR from_date > %s) "
        "ORDER BY from_date",
        (feed, from_date - timedelta(days=1), to_date + timedelta(days=1)),
    ).fetchall()

    if len(overlapping) > 1:
        # There are overlaps to merge (including our newly inserted row)
        min_from = min(row[0] for row in overlapping)
        max_to = max(row[1] for row in overlapping)

        # Delete all overlapping windows
        conn.execute(
            "DELETE FROM feed_coverage WHERE feed = %s AND from_date IN (%s)",
            (feed, [row[0] for row in overlapping]),
        )

        # Insert the merged window
        conn.execute(
            "INSERT INTO feed_coverage (feed, from_date, to_date) VALUES (%s, %s, %s)",
            (feed, min_from, max_to),
        )


def announcement_coverage(conn) -> list[dict]:
    """Coverage report per symbol: how much of the required announcements window is missing.

    Returns a list of dicts with:
      - symbol: stock symbol
      - isin: ISIN
      - listing_date: when listed (or first candle date)
      - required_from: earliest date that should be covered (max of listing, today-3y)
      - first_date: earliest stored announcement (None if none)
      - last_date: latest stored announcement (None if none)
      - rows: count of stored announcements
      - ok: True if first_date <= required_from and last_date >= today

    Computed on demand; does not assume anything about the feed coverage table.
    """
    from datetime import date as dateclass
    today = dateclass.today()

    rows = conn.execute("""
        SELECT
          sl.symbol,
          sl.isin,
          sl.listing_date,
          CASE WHEN sl.listing_date IS NULL THEN CURRENT_DATE - '3 years'::interval
               ELSE greatest(sl.listing_date, CURRENT_DATE - '3 years'::interval) END as required_from,
          vs.first_date,
          vs.last_date,
          COALESCE(vs.n, 0) as rows,
          CASE WHEN COALESCE(vs.first_date, vs.last_date) IS NULL THEN FALSE
               WHEN vs.first_date IS NULL OR vs.last_date IS NULL THEN FALSE
               ELSE (vs.first_date <= greatest(sl.listing_date, CURRENT_DATE - '3 years'::interval))
                    AND (vs.last_date >= CURRENT_DATE)
          END as ok
        FROM symbol_listing sl
        LEFT JOIN v_announcement_summary vs ON sl.symbol = vs.symbol AND sl.isin = vs.isin
        ORDER BY sl.symbol
    """).fetchall()

    return [dict(r) for r in rows]
