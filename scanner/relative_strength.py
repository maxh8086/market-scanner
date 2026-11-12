"""3-month relative strength of index constituents, stored in Postgres table relative_strength.

    python -m scanner.relative_strength [--dry-run]

Anchor date (as_of) is the latest candle date for the Nifty 50 series. The 3-month
baseline target is as_of minus 3 calendar months. A close is used only if the latest close on or
before the target is within BASELINE_TOLERANCE_DAYS of it. The same tolerance applies
to the as_of close.

Membership comes from the latest snapshot of constituent_membership per index. Tier:
  - ISIN in the latest "NIFTY BANK" set -> tier "Bank", comparison index "NIFTY BANK"
  - otherwise the highest of NIFTY 50, NIFTY NEXT 50, NIFTY MIDCAP 150,
    NIFTY SMALLCAP 250, NIFTY MICROCAP 250 that contains the ISIN; the comparison
    index is that tier's own index
  - in no index -> no row

rs_gap_pct = stock_return_3m - index_return_3m (percent). A missing return is stored
as NULL, so the row still exists and the UI can say why.

--dry-run computes the same anchor, tier counts and returns and prints them, but writes
nothing. It does read the database, because the anchor and counts cannot be known
without it.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
import calendar
from datetime import date, timedelta
from decimal import Decimal

from scanner.index_candles import index_symbol
from scanner.pg.db import connect

ANCHOR_SYMBOL = index_symbol("NIFTY 50")
BASELINE_MONTHS = 3
BASELINE_TOLERANCE_DAYS = 7
BANK_INDEX = "NIFTY BANK"
BANK_TIER = "Bank"
# Priority order: first match wins. Each tier is compared to its own index.
TIER_INDEXES = [
    "NIFTY 50",
    "NIFTY NEXT 50",
    "NIFTY MIDCAP 150",
    "NIFTY SMALLCAP 250",
    "NIFTY MICROCAP 250",
]

UPSERT_SQL = (
    "INSERT INTO relative_strength "
    "(symbol, as_of, stock_return_3m, index_name, index_return_3m, rs_gap_pct, tier) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (symbol, as_of) DO UPDATE SET "
    "stock_return_3m = EXCLUDED.stock_return_3m, "
    "index_name = EXCLUDED.index_name, "
    "index_return_3m = EXCLUDED.index_return_3m, "
    "rs_gap_pct = EXCLUDED.rs_gap_pct, "
    "tier = EXCLUDED.tier"
)

# One LATERAL lookup per symbol, so only the needed candle rows are read.
LATEST_CLOSE_SQL = """
SELECT s.symbol, c.date, c.close
FROM unnest(%s::text[]) AS s(symbol)
JOIN LATERAL (
    SELECT date, close FROM candles
    WHERE candles.symbol = s.symbol AND candles.date <= %s
    ORDER BY candles.date DESC
    LIMIT 1
) c ON true
"""


class NoAnchor(Exception):
    """No candles for the anchor index series."""


class NoMembership(Exception):
    """No constituent_membership rows."""


@dataclass(frozen=True)
class Assignment:
    symbol: str
    isin: str
    tier: str
    index_name: str


@dataclass
class Plan:
    as_of: date
    rows: list[tuple] = field(default_factory=list)
    tier_counts: Counter = field(default_factory=Counter)
    no_symbol: int = 0
    missing_stock_return: int = 0
    missing_index_return: int = 0


def months_before(d: date, months: int) -> date:
    """`d` minus whole calendar months, clamping the day to the end of the target month."""
    total = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def window_close(found, target: date) -> Decimal | None:
    """The close from `found` (a (date, close) pair or None) if it is within tolerance of `target`."""
    if found is None:
        return None
    found_date, close = found
    if close is None or target - found_date > timedelta(days=BASELINE_TOLERANCE_DAYS):
        return None
    return Decimal(str(close))


def pct_return(now_close: Decimal | None, base_close: Decimal | None) -> Decimal | None:
    """Percent return from base to now, or None if either close is missing or the base is zero."""
    if now_close is None or base_close is None or base_close == 0:
        return None
    return (now_close / base_close - 1) * 100


def rs_gap(stock_return: Decimal | None, index_return: Decimal | None) -> Decimal | None:
    if stock_return is None or index_return is None:
        return None
    return stock_return - index_return


def assign_tiers(members: dict[str, dict[str, str | None]]) -> list[Assignment]:
    """Map each ISIN to its tier and comparison index from the latest snapshot.

    `members` is {index_name: {isin: symbol}}. The symbol comes from the chosen
    index's row, falling back to any other index row for the same ISIN, and is
    "" if none has one.
    """
    bank = members.get(BANK_INDEX, {})
    isins = sorted({isin for rows in members.values() for isin in rows})
    assignments: list[Assignment] = []
    for isin in isins:
        if isin in bank:
            tier, index_name = BANK_TIER, BANK_INDEX
        else:
            found = next((name for name in TIER_INDEXES if isin in members.get(name, {})), None)
            if found is None:
                continue
            tier, index_name = found, found
        symbol = members[index_name][isin] or next(
            (rows[isin] for rows in members.values() if rows.get(isin)), ""
        )
        assignments.append(Assignment(symbol=symbol, isin=isin, tier=tier, index_name=index_name))
    return assignments


# --- database helpers (patched in tests) -------------------------------------------

def _anchor_date(conn) -> date | None:
    row = conn.execute(
        "SELECT max(date) AS last_date FROM candles WHERE symbol = %s", (ANCHOR_SYMBOL,)
    ).fetchone()
    return row["last_date"] if row else None


def _latest_membership(conn) -> dict[str, dict[str, str | None]]:
    """{index_name: {isin: symbol}} from the latest as_of snapshot of each index."""
    rows = conn.execute(
        "SELECT m.index_name, m.isin, m.symbol FROM constituent_membership m "
        "JOIN (SELECT index_name, max(as_of) AS as_of FROM constituent_membership "
        "GROUP BY index_name) l ON m.index_name = l.index_name AND m.as_of = l.as_of"
    ).fetchall()
    members: dict[str, dict[str, str | None]] = {}
    for row in rows:
        members.setdefault(row["index_name"], {})[row["isin"]] = row["symbol"]
    return members


def _latest_closes(conn, symbols: list[str], on_or_before: date) -> dict[str, tuple[date, object]]:
    """{symbol: (date, close)} for the latest candle on or before `on_or_before`."""
    if not symbols:
        return {}
    rows = conn.execute(LATEST_CLOSE_SQL, (symbols, on_or_before)).fetchall()
    return {row["symbol"]: (row["date"], row["close"]) for row in rows}


def _returns(conn, symbols: list[str], as_of: date, target: date) -> dict[str, Decimal | None]:
    now = _latest_closes(conn, symbols, as_of)
    base = _latest_closes(conn, symbols, target)
    out: dict[str, Decimal | None] = {}
    for symbol in symbols:
        now_close = window_close(now.get(symbol), as_of)
        base_close = window_close(base.get(symbol), target)
        out[symbol] = pct_return(now_close, base_close)
    return out


# --- compute and write --------------------------------------------------------------

def compute(conn) -> Plan:
    """Build the rows to write. Reads only. Raises NoAnchor or NoMembership."""
    as_of = _anchor_date(conn)
    if as_of is None:
        raise NoAnchor(ANCHOR_SYMBOL)
    members = _latest_membership(conn)
    if not members:
        raise NoMembership("constituent_membership is empty")

    target = months_before(as_of, BASELINE_MONTHS)
    assignments = assign_tiers(members)
    plan = Plan(as_of=as_of)

    index_names = sorted({a.index_name for a in assignments})
    index_returns = _returns(conn, [index_symbol(n) for n in index_names], as_of, target)
    stock_symbols = sorted({a.symbol for a in assignments if a.symbol})
    stock_returns = _returns(conn, stock_symbols, as_of, target)

    seen: set[str] = set()
    for a in assignments:
        if not a.symbol:
            plan.no_symbol += 1
            continue
        if a.symbol in seen:
            continue
        seen.add(a.symbol)
        stock_ret = stock_returns.get(a.symbol)
        index_ret = index_returns.get(index_symbol(a.index_name))
        if stock_ret is None:
            plan.missing_stock_return += 1
        if index_ret is None:
            plan.missing_index_return += 1
        plan.tier_counts[a.tier] += 1
        plan.rows.append((
            a.symbol, as_of, stock_ret, a.index_name, index_ret, rs_gap(stock_ret, index_ret), a.tier,
        ))
    return plan


def write_rows(conn, rows: list[tuple]) -> int:
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
    return len(rows)


def _print_plan(plan: Plan, dry_run: bool) -> None:
    print(f"anchor date (as_of): {plan.as_of.isoformat()}")
    for tier in [BANK_TIER, *TIER_INDEXES]:
        if plan.tier_counts.get(tier):
            print(f"  {tier}: {plan.tier_counts[tier]}")
    print(f"rows: {len(plan.rows)}; missing stock return: {plan.missing_stock_return}; "
          f"missing index return: {plan.missing_index_return}; no symbol skipped: {plan.no_symbol}")
    print("dry run: nothing written" if dry_run else f"upserted {len(plan.rows)} rows")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="compute and print counts; write nothing")
    args = parser.parse_args(argv)

    try:
        with connect() as conn:  # psycopg commits on clean exit, rolls back on error
            plan = compute(conn)
            if not args.dry_run:
                write_rows(conn, plan.rows)
    except NoAnchor as exc:
        print(f"error: no candles for anchor series {exc}; run scanner.index_candles first",
              file=sys.stderr)
        return 1
    except NoMembership as exc:
        print(f"error: {exc}; run scanner.constituent_membership first", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - report any DB failure as exit 1
        print(f"error: relative strength failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    _print_plan(plan, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
