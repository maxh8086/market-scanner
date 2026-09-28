"""NSE corporate-event factors: bonuses, demergers, order-book wins, expansion.

Fetches structured corporate actions and free-text announcements from NSE,
caches both to disk, and provides pure classifiers to enrich ATH scan output.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

DB_PATH = Path("data/factors.db")
SCHEMA_VERSION = 2  # 2: dates stored ISO-normalised so range filters work

# Lookback windows for matching announcements
BONUS_LOOKBACK_MONTHS = 24
DEMERGER_LOOKBACK_MONTHS = 24  # structured CA feed: one cheap request
# Free-text demerger announcements are only fetched this far back: a demerger
# announced two years ago with still no ex-date is not news, and each extra
# month of announcements is ~17k rows of text to download.
DEMERGER_ANN_LOOKBACK_MONTHS = 12
ORDERBOOK_LOOKBACK_MONTHS = 12
EXPANSION_LOOKBACK_MONTHS = 6
DEMERGER_FORWARD_MONTHS = 12  # announced but not yet ex

# Browser-like headers required by NSE
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# NSE's announcement `desc` field is a CONTROLLED vocabulary -- 132 fixed
# categories chosen from a dropdown, not free text. Matching those categories
# exactly is far more reliable than guessing at how a filing might be phrased,
# so each classifier has two tiers: a category match (high confidence) and a
# keyword match over the attachment text (heuristic).

# Upper-cased exact `desc` values meaning "we won work".
ORDERBOOK_DESC_CATEGORIES = {
    "BAGGING/RECEIVING OF ORDERS/CONTRACTS",
    "AWARDING OF ORDER(S)/CONTRACT(S)",
}

# Categories that contain the word "orders" but mean regulatory or court action
# against the company -- the opposite signal. Excluded outright so no keyword
# tier can pick them up.
ORDERBOOK_DESC_EXCLUDE = {
    "ACTION(S) TAKEN OR ORDERS PASSED",
    "ACTION(S) INITIATED OR ORDERS PASSED",
    "PENDENCY OF LITIGATION(S)/DISPUTE(S) OR THE OUTCOME IMPACTING THE COMPANY",
}

# Secondary tier, matched against attachment text only. Matching these against
# `desc` is what made "Trading Window" register as an order win via "WIN".
ORDERBOOK_KEYWORDS = {
    "ORDER BOOK",
    "ORDER WIN",
    "RECEIPT OF ORDER",
    "LETTER OF AWARD",
    "LETTER OF INTENT",
    "WORK ORDER",
    "CONTRACT WIN",
    "BAGGED",
    "BAGGING",
    "SECURED AN ORDER",
    "AWARDED",
    "AWARDING OF ORDER",
    "ORDER INFLOW",
}

EXPANSION_DESC_CATEGORIES = {
    "CAPACITY ADDITION",
    "COMMENCEMENT OF COMMERCIAL PRODUCTION/OPERATIONS",
}

# Bare "CAPACITY" and "COMMISSION" were removed: they matched "capacity
# utilisation", "in his capacity as", "Commissioner" and commission payments,
# firing on 526 and 433 filings respectively with no expansion content.
EXPANSION_KEYWORDS = {
    "EXPANSION",
    "CAPACITY ADDITION",
    "CAPACITY EXPANSION",
    "INSTALLED CAPACITY",
    "EXPANDED CAPACITY",
    "CAPEX",
    "COMMERCIAL PRODUCTION",
    "COMMISSIONED",
    "NEW PLANT",
    "NEW FACILITY",
    "GREENFIELD",
    "BROWNFIELD",
    "DEBOTTLENECK",
}

# "DEMERGER" is the exact category name. "SCHEME OF ARRANGEMENT" is also a
# category, but covers mergers, amalgamations and capital reductions too, so it
# is reported as a weaker signal rather than a confirmed demerger.
DEMERGER_DESC_CATEGORIES = {"DEMERGER"}
DEMERGER_KEYWORDS = {
    "DEMERGER",
    "DE-MERGER",
    "SPIN-OFF",
    "SPIN OFF",
}
DEMERGER_WEAK_DESC_CATEGORIES = {"SCHEME OF ARRANGEMENT"}
DEMERGER_WEAK_KEYWORDS = {"SCHEME OF ARRANGEMENT"}

BONUS_DESC_CATEGORIES = {"BONUS"}


def _add_months(d: date, months: int) -> date:
    """Add months to a date, handling year/month boundaries."""
    month = d.month + months
    year = d.year
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    try:
        return d.replace(year=year, month=month)
    except ValueError:
        # Day doesn't exist in target month (e.g., Feb 30), use last day of month
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        return d.replace(year=year, month=month, day=last_day)


def _subtract_months(d: date, months: int) -> date:
    """Subtract months from a date, handling year/month boundaries.

    For example, subtract_months(date(2026, 9, 28), 24) returns date(2024, 9, 28).
    """
    return _add_months(d, -months)


def _connect() -> sqlite3.Connection:
    """Open or create the factors cache database.

    Schema 2 stores dates ISO-normalised. Rows written by schema 1 hold raw
    NSE strings, which no longer compare correctly, so they are dropped and
    re-fetched rather than migrated -- the whole database is a rebuildable
    cache of a public feed.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        for table in ("corporate_actions", "announcements", "fetch_metadata"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_actions (
            isin TEXT NOT NULL,
            symbol TEXT NOT NULL,
            subject TEXT NOT NULL,
            ex_date TEXT,
            received_date TEXT,
            PRIMARY KEY (isin, ex_date, subject)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            isin TEXT NOT NULL,
            symbol TEXT NOT NULL,
            an_dt TEXT NOT NULL,
            desc TEXT,
            attchmnt_text TEXT,
            sort_date TEXT,
            PRIMARY KEY (isin, an_dt, desc)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fetch_metadata (
            feed_name TEXT PRIMARY KEY,
            from_date TEXT,
            to_date TEXT,
            fetched_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def _parse_date_str(date_str: str) -> date | None:
    """Parse an NSE date ('07-Oct-2024', '28-Sep-2026 21:09:08') or an ISO one.

    Rows read back out of the cache are stored ISO-normalised, so both the
    live NSE shape and the cached shape have to parse here.
    """
    if not date_str:
        return None
    try:
        # ISO, as stored in the cache ('2024-10-07' or '2024-10-07 21:09:08')
        if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
            return date.fromisoformat(date_str[:10])
        # Try with time (announcements)
        if " " in date_str:
            return datetime.strptime(date_str, "%d-%b-%Y %H:%M:%S").date()
        # Try without time (corporate actions)
        return datetime.strptime(date_str, "%d-%b-%Y").date()
    except (ValueError, TypeError, IndexError):
        return None


def _to_iso(date_str: str) -> str:
    """NSE date string -> sortable ISO 'YYYY-MM-DD', or '' if unparseable.

    Dates must be stored ISO so that the SQL range filters in the cache-read
    path compare correctly; '08-Oct-2024' >= '2024-10-08' is lexicographically
    False, which silently empties every cached read.
    """
    parsed = _parse_date_str(date_str)
    return parsed.isoformat() if parsed else ""


def _month_end(d: date) -> date:
    """Last day of d's month. Always >= d, which keeps chunk loops advancing."""
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _was_fetched_today(feed_name: str, from_date: date, to_date: date) -> bool:
    """Check if this range was already fetched today."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT fetched_at FROM fetch_metadata WHERE feed_name = ?",
            (feed_name,),
        ).fetchone()
        if not row:
            return False
        fetched_at_str = row[0]
        fetched_date = datetime.fromisoformat(fetched_at_str).date()
        today = date.today()
        # Re-fetch if date ranges don't match or it was fetched on a different day
        stored_row = conn.execute(
            "SELECT from_date, to_date FROM fetch_metadata WHERE feed_name = ?",
            (feed_name,),
        ).fetchone()
        if stored_row:
            stored_from, stored_to = stored_row
            return (
                stored_from == from_date.isoformat()
                and stored_to == to_date.isoformat()
                and fetched_date == today
            )
        return False
    finally:
        conn.close()


def _mark_fetched(feed_name: str, from_date: date, to_date: date) -> None:
    """Mark feed as fetched at this date range and time."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO fetch_metadata (feed_name, from_date, to_date, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(feed_name) DO UPDATE SET
                from_date=excluded.from_date,
                to_date=excluded.to_date,
                fetched_at=excluded.fetched_at
            """,
            (
                feed_name,
                from_date.isoformat(),
                to_date.isoformat(),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _save_corporate_actions(rows: list[dict]) -> None:
    """Cache corporate actions to SQLite."""
    if not rows:
        return
    conn = _connect()
    try:
        data = [
            (
                row.get("isin", ""),
                row.get("symbol", ""),
                row.get("subject", ""),
                _to_iso(row.get("exDate", "")),
                datetime.now().isoformat(),
            )
            for row in rows
        ]
        conn.executemany(
            """
            INSERT INTO corporate_actions (isin, symbol, subject, ex_date, received_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(isin, ex_date, subject) DO NOTHING
            """,
            data,
        )
        conn.commit()
    finally:
        conn.close()


def _save_announcements(rows: list[dict]) -> None:
    """Cache announcements to SQLite, storing only needed columns."""
    if not rows:
        return
    conn = _connect()
    try:
        data = [
            (
                row.get("sm_isin", ""),
                row.get("symbol", ""),
                _to_iso(row.get("an_dt", "")),
                row.get("desc", ""),
                row.get("attchmntText", ""),
                # sort_date is the column the range filter compares against;
                # fall back to an_dt when NSE omits it, or the row becomes
                # invisible to every cached read.
                _to_iso(row.get("sort_date", "")) or _to_iso(row.get("an_dt", "")),
            )
            for row in rows
        ]
        conn.executemany(
            """
            INSERT INTO announcements (isin, symbol, an_dt, desc, attchmnt_text, sort_date)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(isin, an_dt, desc) DO NOTHING
            """,
            data,
        )
        conn.commit()
    finally:
        conn.close()


def _load_cached_corporate_actions(from_date: date, to_date: date) -> list[dict]:
    """Load cached corporate actions for the date range."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT isin, symbol, subject, ex_date FROM corporate_actions
            WHERE ex_date >= ? AND ex_date <= ?
            """,
            (from_date.isoformat(), to_date.isoformat()),
        ).fetchall()
        return [
            {
                "isin": r[0],
                "symbol": r[1],
                "subject": r[2],
                "exDate": r[3],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_cached_announcements(from_date: date, to_date: date) -> list[dict]:
    """Load cached announcements for the date range."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT isin, symbol, an_dt, desc, attchmnt_text, sort_date FROM announcements
            WHERE sort_date >= ? AND sort_date <= ?
            """,
            (from_date.isoformat(), to_date.isoformat()),
        ).fetchall()
        return [
            {
                "sm_isin": r[0],
                "symbol": r[1],
                "an_dt": r[2],
                "desc": r[3],
                "attchmntText": r[4],
                "sort_date": r[5],
            }
            for r in rows
        ]
    finally:
        conn.close()


def fetch_corporate_actions(
    from_date: date, to_date: date, session: requests.Session | None = None, refresh: bool = False
) -> list[dict]:
    """Fetch corporate actions from NSE, cache on disk.

    Returns list of dicts with keys: isin, symbol, subject, exDate.
    """
    # Check cache first
    if not refresh and _was_fetched_today("corporate_actions", from_date, to_date):
        cached = _load_cached_corporate_actions(from_date, to_date)
        if cached:
            return cached

    if session is None:
        session = requests.Session()

    url = "https://www.nseindia.com/api/corporates-corporateActions"
    params = {
        "index": "equities",
        "from_date": from_date.strftime("%d-%m-%Y"),
        "to_date": to_date.strftime("%d-%m-%Y"),
    }

    try:
        print(f"  Fetching corporate actions ({from_date} to {to_date})...")
        resp = session.get(url, params=params, headers=UA, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            rows = []
        _save_corporate_actions(rows)
        _mark_fetched("corporate_actions", from_date, to_date)
        print(f"    Fetched {len(rows)} corporate action rows")
        return rows
    except Exception as e:
        print(f"  Warning: corporate actions fetch failed: {e}")
        # Fall back to cache if available
        cached = _load_cached_corporate_actions(from_date, to_date)
        return cached if cached else []


def fetch_announcements(
    from_date: date, to_date: date, session: requests.Session | None = None, refresh: bool = False
) -> list[dict]:
    """Fetch announcements from NSE, cache on disk.

    Fetches by month internally to keep requests bounded and tolerate partial failures.
    Returns list of dicts with keys: sm_isin, symbol, an_dt, desc, attchmntText, sort_date.
    """
    # Check cache first
    if not refresh and _was_fetched_today("announcements", from_date, to_date):
        cached = _load_cached_announcements(from_date, to_date)
        if cached:
            return cached

    if session is None:
        session = requests.Session()

    if from_date > to_date:
        return []

    all_rows: list[dict] = []
    url = "https://www.nseindia.com/api/corporate-announcements"

    # Slice into calendar months to keep individual requests bounded. _month_end
    # is always >= current and the cap is to_date, which the loop guard already
    # holds current below, so each chunk end is >= current and the next start is
    # strictly greater -- the loop cannot stall.
    chunks: list[tuple[date, date]] = []
    current = from_date
    while current <= to_date:
        chunk_end = min(_month_end(current), to_date)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)

    failures = 0
    for chunk_from, chunk_to in chunks:
        params = {
            "index": "equities",
            "from_date": chunk_from.strftime("%d-%m-%Y"),
            "to_date": chunk_to.strftime("%d-%m-%Y"),
        }

        try:
            print(f"  Fetching announcements ({chunk_from} to {chunk_to})...")
            resp = session.get(url, params=params, headers=UA, timeout=30)
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list):
                rows = []
            # Trim to the fields the classifiers use before accumulating. The
            # raw NSE rows carry long attachment URLs and metadata; keeping all
            # of them for a multi-month window runs to hundreds of megabytes.
            trimmed = [
                {
                    "sm_isin": r.get("sm_isin", ""),
                    "symbol": r.get("symbol", ""),
                    "an_dt": r.get("an_dt", ""),
                    "desc": r.get("desc", ""),
                    "attchmntText": r.get("attchmntText", ""),
                    "sort_date": r.get("sort_date", ""),
                }
                for r in rows
                if isinstance(r, dict)
            ]
            # Persist per chunk so an interrupted or partly failed run still
            # leaves usable data behind.
            _save_announcements(trimmed)
            all_rows.extend(trimmed)
            print(f"    Fetched {len(trimmed)} announcement rows")
        except Exception as e:
            failures += 1
            print(f"  Warning: announcements fetch for {chunk_from}-{chunk_to} failed: {e} (continuing)")

        time.sleep(1)  # Polite rate-limiting, on the failure path too

    # Only claim the range as fetched if every chunk landed; a partial cache
    # marked complete would be served as authoritative for the rest of the day.
    if all_rows and not failures:
        _mark_fetched("announcements", from_date, to_date)

    if not all_rows:
        return _load_cached_announcements(from_date, to_date)
    return all_rows


def classify_bonus(
    ca_rows: list[dict], isin: str, today: date, ann_rows: list[dict] | None = None
) -> str:
    """Classify bonus issues from the corporate actions feed.

    Returns empty string or a compact string like 'Bonus 1:1 ex 2025-08-27',
    marked UPCOMING when the ex-date is still ahead. When ann_rows is given and
    the structured feed has nothing, falls back to a 'Bonus' announcement, which
    catches an issue that is announced but has no ex-date yet.
    """
    cutoff = _subtract_months(today, BONUS_LOOKBACK_MONTHS)

    bonus_rows = []
    for row in ca_rows:
        if row.get("isin") != isin:
            continue
        subj = str(row.get("subject", ""))
        if "BONUS" not in subj.upper():
            continue
        ex_date_str = row.get("exDate", "")
        ex_date = _parse_date_str(ex_date_str)
        if ex_date is None or ex_date < cutoff:
            continue
        bonus_rows.append((ex_date, subj))

    if bonus_rows:
        # Use most recent
        bonus_rows.sort(reverse=True)
        ex_date, subj = bonus_rows[0]
        count_str = (
            f" ({len(bonus_rows)} in {BONUS_LOOKBACK_MONTHS}m)" if len(bonus_rows) > 1 else ""
        )
        upcoming = " UPCOMING" if ex_date > today else ""
        return f"{subj}{upcoming} ex {ex_date.isoformat()}{count_str}"

    announced = None
    for row in ann_rows or ():
        if row.get("sm_isin") != isin:
            continue
        if str(row.get("desc", "")).upper().strip() not in BONUS_DESC_CATEGORIES:
            continue
        an_dt = _parse_date_str(row.get("an_dt", ""))
        if an_dt is None or an_dt < cutoff:
            continue
        if announced is None or an_dt > announced:
            announced = an_dt

    if announced:
        return f"Bonus announced {announced.isoformat()} (no ex-date yet)"

    return ""


def classify_demerger(ca_rows: list[dict], ann_rows: list[dict], isin: str, today: date) -> str:
    """Classify demerger status: executed, upcoming, or announced-only.

    Returns empty string or one of:
      'Demerger ex 2025-01-06' (executed)
      'Demerger UPCOMING ex 2026-11-10' (future ex-date)
      'Demerger announced 2026-07-14 (no ex-date yet)' (announced only)
    """
    ca_cutoff = _subtract_months(today, DEMERGER_LOOKBACK_MONTHS)
    ann_cutoff = _subtract_months(today, DEMERGER_ANN_LOOKBACK_MONTHS)
    forward_cutoff = _add_months(today, DEMERGER_FORWARD_MONTHS)

    # Check structured CA feed first
    for row in ca_rows:
        if row.get("isin") != isin:
            continue
        subj = str(row.get("subject", "")).upper()
        if "DEMERGER" not in subj:
            continue
        ex_date_str = row.get("exDate", "")
        ex_date = _parse_date_str(ex_date_str)
        if ex_date is None or ex_date < ca_cutoff:
            continue

        if ex_date <= today:
            return f"Demerger ex {ex_date.isoformat()}"
        else:
            return f"Demerger UPCOMING ex {ex_date.isoformat()}"

    # Fall back to announcements if no structured match. A 'Demerger' category
    # or an explicit demerger word is a real signal; a bare 'Scheme of
    # Arrangement' is not -- that category also covers mergers, amalgamations
    # and capital reductions, so it is reported as possible, not confirmed.
    announced_date = None
    weak_date = None
    for row in ann_rows:
        if row.get("sm_isin") != isin:
            continue
        desc = str(row.get("desc", "")).upper().strip()
        text = str(row.get("attchmntText", "")).upper()
        strong = desc in DEMERGER_DESC_CATEGORIES or any(
            kw in desc or kw in text for kw in DEMERGER_KEYWORDS
        )
        weak = desc in DEMERGER_WEAK_DESC_CATEGORIES or any(
            kw in desc or kw in text for kw in DEMERGER_WEAK_KEYWORDS
        )
        if not (strong or weak):
            continue
        an_dt = _parse_date_str(row.get("an_dt", ""))
        if an_dt is None or an_dt < ann_cutoff or an_dt > forward_cutoff:
            continue
        if strong:
            if announced_date is None or an_dt > announced_date:
                announced_date = an_dt
        elif weak_date is None or an_dt > weak_date:
            weak_date = an_dt

    if announced_date:
        return f"Demerger announced {announced_date.isoformat()} (no ex-date yet)"
    if weak_date:
        return f"Scheme of Arrangement {weak_date.isoformat()} (demerger unconfirmed)"

    return ""


def classify_orderbook(ann_rows: list[dict], isin: str, today: date) -> str:
    """Classify order-book wins from announcements.

    Returns empty string or 'N order announcements (latest YYYY-MM-DD)',
    suffixed ', text-match only' when no filing used one of NSE's own
    order-win categories and the match rests on attachment-text keywords.
    """
    cutoff = _subtract_months(today, ORDERBOOK_LOOKBACK_MONTHS)

    matches: list[date] = []
    by_category = 0
    for row in ann_rows:
        if row.get("sm_isin") != isin:
            continue
        desc = str(row.get("desc", "")).upper().strip()
        if desc in ORDERBOOK_DESC_EXCLUDE:
            continue  # regulatory action, not an order win
        text = str(row.get("attchmntText", "")).upper()
        is_category = desc in ORDERBOOK_DESC_CATEGORIES
        if not (is_category or any(kw in text for kw in ORDERBOOK_KEYWORDS)):
            continue
        an_dt = _parse_date_str(row.get("an_dt", ""))
        if an_dt is None or an_dt < cutoff:
            continue
        matches.append(an_dt)
        if is_category:
            by_category += 1

    if not matches:
        return ""

    matches.sort(reverse=True)
    count = len(matches)
    tier = "" if by_category else ", text-match only"
    return (
        f"{count} order announcement{'s' if count != 1 else ''}"
        f"{tier} (latest {matches[0].isoformat()})"
    )


def classify_expansion(ann_rows: list[dict], isin: str, today: date) -> str:
    """Classify expansion/capex announcements.

    Returns empty string or 'N expansion announcement(s) (latest YYYY-MM-DD)'.
    """
    cutoff = _subtract_months(today, EXPANSION_LOOKBACK_MONTHS)

    matches: list[date] = []
    by_category = 0
    for row in ann_rows:
        if row.get("sm_isin") != isin:
            continue
        desc = str(row.get("desc", "")).upper().strip()
        text = str(row.get("attchmntText", "")).upper()
        is_category = desc in EXPANSION_DESC_CATEGORIES
        if not (is_category or any(kw in text for kw in EXPANSION_KEYWORDS)):
            continue
        an_dt = _parse_date_str(row.get("an_dt", ""))
        if an_dt is None or an_dt < cutoff:
            continue
        matches.append(an_dt)
        if is_category:
            by_category += 1

    if not matches:
        return ""

    matches.sort(reverse=True)
    count = len(matches)
    tier = "" if by_category else ", text-match only"
    return (
        f"{count} expansion announcement{'s' if count != 1 else ''}"
        f"{tier} (latest {matches[0].isoformat()})"
    )


def build_factor_table(
    ca_rows: list[dict], ann_rows: list[dict], isins: list[str], today: date
) -> dict[str, dict]:
    """Build factors for a list of ISINs.

    Index corporate actions and announcements by ISIN once to avoid repeated
    scanning of large result sets. Returns {isin: {bonus, demerger, orderbook, expansion, factors_matched}}.
    """
    # Index rows by ISIN for efficiency
    ca_by_isin: dict[str, list[dict]] = {}
    ann_by_isin: dict[str, list[dict]] = {}

    for row in ca_rows:
        isin = row.get("isin", "")
        if isin:
            if isin not in ca_by_isin:
                ca_by_isin[isin] = []
            ca_by_isin[isin].append(row)

    for row in ann_rows:
        isin = row.get("sm_isin", "")
        if isin:
            if isin not in ann_by_isin:
                ann_by_isin[isin] = []
            ann_by_isin[isin].append(row)

    # Classify each ISIN
    result = {}
    for isin in isins:
        ca_for_isin = ca_by_isin.get(isin, [])
        ann_for_isin = ann_by_isin.get(isin, [])

        bonus = classify_bonus(ca_for_isin, isin, today, ann_for_isin)
        demerger = classify_demerger(ca_for_isin, ann_for_isin, isin, today)
        orderbook = classify_orderbook(ann_for_isin, isin, today)
        expansion = classify_expansion(ann_for_isin, isin, today)

        factors_matched = sum(1 for f in [bonus, demerger, orderbook, expansion] if f)

        result[isin] = {
            "bonus_issue": bonus,
            "demerger": demerger,
            "orderbook_signal": orderbook,
            "expansion_signal": expansion,
            "factors_matched": factors_matched,
        }

    return result
