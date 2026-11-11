"""Monthly reference refresh: NSE CSV and Upstox NSE master rows into company_reference (047).

Runs read only the table. This module parses source bytes and writes the table; it does no
network I/O. The monthly job fetches the sources and then calls refresh().

Settled name rule (both sides): uppercase; "&" becomes " AND "; ".,'()-" become spaces;
LIMITED and LTD become LTD; runs of spaces collapse.
"""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Sequence

SOURCE_CSV = "nse_csv"
SOURCE_MASTER = "upstox_master"
SOURCES = (SOURCE_CSV, SOURCE_MASTER)

_PUNCT = re.compile(r"[.,'()\-]")
_LIMITED = re.compile(r"\b(LIMITED|LTD)\b")


def normalise_name(name: str | None) -> str:
    """Return the name key. Pure: same input, same output; no I/O."""
    s = (name or "").upper().replace("&", " AND ")
    s = _PUNCT.sub(" ", s)
    s = _LIMITED.sub("LTD", s)
    return " ".join(s.split())


@dataclass(frozen=True)
class RefRow:
    source: str
    symbol: str
    isin: str
    company_name: str
    name_key: str
    series: str | None
    as_of: date


def _key(value: Any) -> str:
    return str(value or "").strip().upper()


def _make(source: str, symbol: str, isin: str, name: str, series: str | None, as_of: date) -> RefRow:
    return RefRow(source, symbol, isin, name.strip(), normalise_name(name), series, as_of)


def csv_rows(records: Iterable[dict], as_of: date) -> list[RefRow]:
    """Rows from the NSE constituents CSV, given as dicts with the CSV's own column names.

    Columns used: "Company Name", "Symbol", "ISIN Code", "Series". Blank symbol or ISIN is
    skipped. A repeated (symbol, ISIN) pair keeps its first row.
    """
    out: dict[tuple[str, str], RefRow] = {}
    for rec in records:
        symbol, isin = _key(rec.get("Symbol")), _key(rec.get("ISIN Code"))
        name = str(rec.get("Company Name") or "")
        if not symbol or not isin or not name.strip():
            continue
        series = str(rec.get("Series") or "").strip() or None
        out.setdefault((symbol, isin), _make(SOURCE_CSV, symbol, isin, name, series, as_of))
    return list(out.values())


EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"


def equity_list_rows(records: Iterable[dict], as_of: date) -> list[RefRow]:
    """Rows from NSE's full equity list (EQUITY_L.csv). Keys are stripped first, because the
    file's header has stray spaces (" SERIES"). Uses SYMBOL, NAME OF COMPANY, SERIES and
    ISIN NUMBER. Blank symbol or ISIN is skipped. A repeated (symbol, ISIN) keeps its first row."""
    out: dict[tuple[str, str], RefRow] = {}
    for raw in records:
        rec = {str(k).strip(): v for k, v in raw.items() if k is not None}
        symbol, isin = _key(rec.get("SYMBOL")), _key(rec.get("ISIN NUMBER"))
        name = str(rec.get("NAME OF COMPANY") or "")
        if not symbol or not isin or not name.strip():
            continue
        series = str(rec.get("SERIES") or "").strip() or None
        out.setdefault((symbol, isin), _make(SOURCE_CSV, symbol, isin, name, series, as_of))
    return list(out.values())


def master_rows(raw: bytes, as_of: date) -> list[RefRow]:
    """Rows from the Upstox instrument master (gzipped JSON list). Keeps NSE_EQ with EQ type.

    Uses the fields segment, instrument_type, trading_symbol, isin and name.
    """
    data = json.loads(gzip.decompress(raw).decode("utf-8"))
    out: dict[tuple[str, str], RefRow] = {}
    for rec in data:
        if rec.get("segment") != "NSE_EQ" or rec.get("instrument_type") != "EQ":
            continue
        symbol, isin = _key(rec.get("trading_symbol")), _key(rec.get("isin"))
        name = str(rec.get("name") or "")
        if not symbol or not isin or not name.strip():
            continue
        out.setdefault((symbol, isin), _make(SOURCE_MASTER, symbol, isin, name, None, as_of))
    return list(out.values())


_DELETE = "DELETE FROM company_reference WHERE source = %s"
_INSERT = (
    "INSERT INTO company_reference "
    "(source, symbol, isin, company_name, name_key, series, as_of, loaded_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, now())"
)


@dataclass(frozen=True)
class Index:
    """Lookups built from company_reference rows (decision O1: union of both sources).

    universe : symbol -> ISIN, for symbols whose ISIN agrees across every row.
    by_name  : name_key -> (symbol, ISIN), for names that map to exactly one usable pair.
    conflicts: symbols, ISINs and names that were left out, listed for review.
    """
    universe: dict[str, str]
    by_name: dict[str, tuple[str, str]]
    conflicts: tuple[str, ...]


def build_index(rows: Iterable[tuple[str, str, str, str]]) -> Index:
    """Build an Index from (source, symbol, isin, name_key) tuples. Pure.

    A symbol with two ISINs, an ISIN with two symbols, or a name that maps to two pairs is
    left out and recorded in `conflicts`. Those items then resolve to nothing and are
    rejected as "universe".
    """
    rows = list(rows)
    symbol_isins: dict[str, set[str]] = {}
    isin_symbols: dict[str, set[str]] = {}
    for _src, symbol, isin, _nk in rows:
        symbol_isins.setdefault(symbol, set()).add(isin)
        isin_symbols.setdefault(isin, set()).add(symbol)
    conflicts: list[str] = []
    for symbol, isins in sorted(symbol_isins.items()):
        if len(isins) > 1:
            conflicts.append(f"symbol:{symbol}")
    for isin, symbols in sorted(isin_symbols.items()):
        if len(symbols) > 1:
            conflicts.append(f"isin:{isin}")
    bad_symbols = {s for s, isins in symbol_isins.items() if len(isins) > 1}
    bad_isins = {i for i, symbols in isin_symbols.items() if len(symbols) > 1}
    universe: dict[str, str] = {}
    name_pairs: dict[str, set[tuple[str, str]]] = {}
    for _src, symbol, isin, name_key in rows:
        if symbol in bad_symbols or isin in bad_isins:
            continue
        universe[symbol] = isin
        name_pairs.setdefault(name_key, set()).add((symbol, isin))
    by_name: dict[str, tuple[str, str]] = {}
    for name_key, pairs in sorted(name_pairs.items()):
        if len(pairs) == 1:
            by_name[name_key] = next(iter(pairs))
        else:
            conflicts.append(f"name:{name_key}")
    return Index(universe=universe, by_name=by_name, conflicts=tuple(conflicts))


def fill_from_name(items: Sequence[dict], by_name: dict[str, tuple[str, str]]) -> list[dict]:
    """Fill symbol and ISIN on items that carry a company name but no symbol. Pure.

    An item with a symbol already is passed through unchanged. An unresolved item keeps
    symbol None, so filter_items rejects it as "universe". An item whose own ISIN disagrees
    with the resolved one is also left unresolved. Returns copies; the input is not changed.
    """
    out: list[dict] = []
    for item in items:
        if item.get("symbol") is not None:
            out.append(dict(item))
            continue
        pair = by_name.get(normalise_name(item.get("company")))
        supplied = item.get("isin")
        if pair is None or (supplied and supplied != pair[1]):
            out.append(dict(item))
            continue
        out.append(dict(item, symbol=pair[0], isin=pair[1]))
    return out


def load_index(conn) -> Index:
    """Read company_reference and build the Index. Read only; the app role has SELECT."""
    fetched = conn.execute("SELECT source, symbol, isin, name_key FROM company_reference").fetchall()
    # scanner.pg.db connects with dict_row, so each row is a mapping; plain tuples also work.
    rows = [
        (r["source"], r["symbol"], r["isin"], r["name_key"]) if isinstance(r, dict)
        else (r[0], r[1], r[2], r[3])
        for r in fetched
    ]
    return build_index(rows)


class EmptySourceError(RuntimeError):
    """A source parsed to zero rows. The refresh is refused and last month's rows stay."""


def refresh(conn, rows_by_source: dict[str, Sequence[RefRow]]) -> dict[str, int]:
    """Replace each source's rows in one transaction. Returns row counts per source.

    Refuses the whole refresh if any source is empty or missing, so a bad download cannot
    erase the last good month. The caller owns the connection; the loader role needs DELETE
    and INSERT on company_reference (decision O2).
    """
    for src in SOURCES:
        if not rows_by_source.get(src):
            raise EmptySourceError(f"{src}: no rows parsed; refresh refused, last month's rows kept")
    counts: dict[str, int] = {}
    with conn.transaction():
        for src in SOURCES:
            rows = rows_by_source[src]
            conn.execute(_DELETE, (src,))
            for r in rows:
                conn.execute(_INSERT, (r.source, r.symbol, r.isin, r.company_name,
                                       r.name_key, r.series, r.as_of))
            counts[src] = len(rows)
    return counts


# ---- Index constituents (table index_constituents, migration 048) -----------------------
# The monthly job stores each named index's constituent list here. Scans read one index by
# name; the run path never downloads these lists.

INDEX_CONSTITUENTS_TABLE = "index_constituents"

_DELETE_INDEX = "DELETE FROM index_constituents WHERE index_name = %s"
_INSERT_INDEX = (
    "INSERT INTO index_constituents "
    "(index_name, symbol, isin, company_name, industry, series, as_of, loaded_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, now())"
)
_SELECT_INDEX = (
    "SELECT symbol, isin, company_name, industry, series FROM index_constituents "
    "WHERE index_name = %s ORDER BY symbol"
)
_SELECT_MASTER = "SELECT symbol, isin FROM company_reference WHERE source = %s"


def constituent_rows(records: Iterable[dict], as_of: date, index_name: str) -> list[dict]:
    """Rows from an index constituents CSV, given as dicts with the CSV's own column names.

    Columns used: "Company Name", "Industry", "Symbol", "Series", "ISIN Code". Keys and values
    are stripped. Blank symbol or ISIN is skipped, and so are DUMMY placeholder symbols (the
    same rule as scanner/constituents.py). A repeated (symbol, ISIN) keeps its first row.
    as_of is not stored in the dict; replace_index_constituents takes it.
    """
    out: dict[tuple[str, str], dict] = {}
    for raw in records:
        rec = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items() if k is not None}
        symbol, isin = _key(rec.get("Symbol")), _key(rec.get("ISIN Code"))
        if not symbol or not isin or symbol.startswith("DUMMY"):
            continue
        out.setdefault((symbol, isin), {
            "index_name": index_name,
            "symbol": symbol,
            "isin": isin,
            "company_name": str(rec.get("Company Name") or ""),
            "industry": str(rec.get("Industry") or "").strip() or None,
            "series": str(rec.get("Series") or "").strip() or None,
        })
    return list(out.values())


def replace_index_constituents(conn, index_name: str, rows: Sequence[dict], as_of: date) -> int:
    """Replace one index's rows in one transaction. Returns the number of rows written.

    Refuses an empty list (EmptySourceError), so last month's list stays. Only this index's
    rows are deleted; other indexes are not touched.
    """
    if not rows:
        raise EmptySourceError(f"{index_name}: no constituents parsed; refresh refused, last month's rows kept")
    with conn.transaction():
        conn.execute(_DELETE_INDEX, (index_name,))
        for r in rows:
            conn.execute(_INSERT_INDEX, (index_name, r["symbol"], r["isin"], r["company_name"],
                                         r["industry"], r["series"], as_of))
    return len(rows)


def load_index_constituents(conn, index_name: str) -> list[dict]:
    """Read one index's constituents. Keys match the old CSV columns (see constituents.py).

    Raises RuntimeError when the index has no rows: the monthly job has not loaded it.
    """
    fetched = conn.execute(_SELECT_INDEX, (index_name,)).fetchall()
    out: list[dict] = []
    for r in fetched:
        if isinstance(r, dict):
            symbol, isin, cname, industry, series = r["symbol"], r["isin"], r["company_name"], r["industry"], r["series"]
        else:
            symbol, isin, cname, industry, series = r[0], r[1], r[2], r[3], r[4]
        out.append({
            "Symbol": symbol,
            "ISIN Code": isin,
            "Company Name": cname,
            "Industry": industry,
            "Series": series,
        })
    if not out:
        raise RuntimeError(f"index {index_name!r} has no constituents in the database; the monthly job has not loaded it")
    return out


def load_master_from_db(conn) -> dict:
    """Upstox NSE master as {"by_symbol": {SYMBOL: isin}, "by_isin": {isin: SYMBOL}}.

    Built from company_reference rows with source upstox_master. The shape matches what
    isin_resolver.resolve() expects. Raises RuntimeError when there are no rows.
    """
    fetched = conn.execute(_SELECT_MASTER, (SOURCE_MASTER,)).fetchall()
    by_symbol: dict[str, str] = {}
    by_isin: dict[str, str] = {}
    for r in fetched:
        symbol, isin = (r["symbol"], r["isin"]) if isinstance(r, dict) else (r[0], r[1])
        by_symbol[symbol] = isin
        by_isin[isin] = symbol
    if not by_symbol:
        raise RuntimeError("the Upstox master has no rows in company_reference; the monthly job has not loaded it")
    return {"by_symbol": by_symbol, "by_isin": by_isin}
