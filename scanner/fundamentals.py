"""Company fundamentals from screener.in, for the denominators scoring needs.

An order value means nothing without a scale to measure it against, so this
supplies market cap and the revenue series. It also carries the ratios worth
seeing next to a breakout -- P/E, ROCE, promoter pledge, debt/equity -- since
they come free in the same page fetch.

The fetch and the HTML parsers live in `scanner.screener` (the method the
screener-mcp package uses, kept in-repo so the enrich image needs no MCP package).
The fetch is async, so a batch runs in one event loop with one paced client (see
`_run`). screener.in pages are public but richer when logged in --
SCREENER_USERNAME / SCREENER_PASSWORD in the environment are picked up by the
client, and without them the run still works on the public page.

The parsing is split out into `parse_page` so it can be tested against a saved
page. That is where the risk is: the figures come out of screener's HTML, and a
layout change does not raise -- it quietly yields None for every ratio and an
empty revenue series.

Industry P/E is computed as the **median P/E of the scan's own cohort in the
same industry**, not fetched. screener's peer table loads over AJAX, so pulling
it would mean a second request per company; the constituents CSV already
carries an `industry` column, and a median over the companies actually being
scanned is arguably the more relevant comparison anyway.
"""

from __future__ import annotations

import asyncio
import statistics
from dataclasses import dataclass, field
from typing import Iterable, Optional

from scanner import docstore, screener, significance

# screener quotes market cap and sales in Rs crore.
FIELDS_FROM_OVERVIEW = {
    "Market Cap": "mcap_cr",
    "Current Price": "price",
    "Stock P/E": "pe",
    "ROCE": "roce",
    "ROE": "roe",
    "Dividend Yield": "dividend_yield",
    "Book Value": "book_value",
    "Face Value": "face_value",
}

# How stale cached fundamentals may be before a refresh. Market cap moves with
# price every day, so a week-old cap misstates a ratio by however much the
# stock moved -- which for a stock near its all-time high is the whole point.
MAX_AGE_DAYS = 1.0

# No sleep constant here on purpose: `screener.Client` paces itself
# (SCREENER_MIN_INTERVAL between request starts, SCREENER_MAX_CONCURRENCY in
# flight, and a shared cooldown on a 429). Adding a sleep on top would slow the
# run without making it any politer than the limiter already does.


@dataclass
class Fundamentals:
    """One company's fundamentals. Rupee figures in Rs crore, as screener
    reports them. Every field is Optional: a missing ratio is normal (a
    loss-making company has no P/E) and must not read as zero."""

    symbol: str
    mcap_cr: Optional[float] = None
    pe: Optional[float] = None
    roce: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    pledged_pct: Optional[float] = None
    promoter_holding_pct: Optional[float] = None
    quarterly_sales: list = field(default_factory=list)
    annual_sales: list = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.mcap_cr is not None

    def to_doc(self) -> dict:
        d = dict(self.__dict__)
        d.pop("symbol", None)
        return d


def _clean(value) -> Optional[float]:
    """screener's display strings -> float. Reuses the scoring module's parser
    so both sides read '16,20,656' identically."""
    return significance._num(value)


def _promoter_holding(shareholding: dict | None) -> Optional[float]:
    """Latest promoter holding percentage from the shareholding table.

    Only the holding. Pledge is *not* here: screener's shareholding table
    carries no pledge row even for a company with most of its promoter stake
    pledged, which is why `screener.pledged_pct` reads it out of the
    cons list instead.
    """
    if not isinstance(shareholding, dict):
        return None
    for row in shareholding.get("rows") or []:
        label = str(row.get("category", "")).strip().lower().rstrip("+")
        if label in ("promoters", "promoter"):
            values = row.get("values") or []
            return _clean(values[-1]) if values else None
    return None


# Row labels to try, in order, for a revenue series. `Sales+` is how screener
# labels the row when it has an expandable breakdown, and the marker is not
# always stripped across layouts, so both spellings are tried. Total Income is the last resort: it includes other income, so it
# is not the same quantity, and taking it silently would make one company's
# series incomparable with the next.
SALES_ROWS = ("Sales", "Sales+", "Revenue", "Revenue+", "Total Income")


def _series_from_table(table: dict | None,
                       row_names: Iterable[str] = SALES_ROWS) -> list:
    """One row of a screener financial table as floats, oldest value first.

    The table arrives as `{"years": [...], "rows": [{"label", "values"}]}`, and
    a trailing TTM column is stripped first: it is not a period, and leaving it
    on the end of a quarterly series would put a twelve-month figure where the
    seasonal model expects a three-month one -- roughly a 4x spike that reads as
    explosive growth.

    Non-numeric cells become None rather than being dropped, so position is
    preserved: a quarterly series is only seasonal if index k really is k
    quarters back. The revenue callers drop blanks themselves.
    """
    if not isinstance(table, dict) or not table.get("rows"):
        return []
    try:
        _, rows, _ = screener.split_ttm(table)
    except Exception:  # noqa: BLE001 - shape varies; fall back to the raw rows
        rows = table.get("rows") or []
    by_label = {}
    for row in rows:
        label = str(row.get("label", "")).strip()
        by_label.setdefault(label, row)
        by_label.setdefault(label.rstrip("+"), row)
    for name in row_names:
        row = by_label.get(name) or by_label.get(name.rstrip("+"))
        if row:
            return [_clean(v) for v in (row.get("values") or [])]
    return []


def parse_page(symbol: str, html: str) -> Fundamentals:
    """Everything this module extracts from one company page. No network.

    Separated from the fetch so the parsing -- which is where the bugs live,
    since it depends on screener's HTML -- can be tested against a saved page instead of only in production.
    """
    f = Fundamentals(symbol=symbol)
    cp = screener

    try:
        overview = cp.parse_overview(html) or {}
    except Exception as e:  # noqa: BLE001
        f.error = f"overview parse failed: {type(e).__name__}: {e}"
        return f

    # The ratios live under `key_ratios`; the top level carries name, sectors
    # and the 52-week range. Fall back to the top level so a layout change that
    # flattens the dict does not silently zero every ratio.
    ratios = overview.get("key_ratios")
    if not isinstance(ratios, dict):
        ratios = overview
    for label, attr in FIELDS_FROM_OVERVIEW.items():
        if attr in ("price", "dividend_yield", "book_value", "face_value"):
            continue  # fetched but not carried: the scan has its own price
        value = _clean(ratios.get(label))
        if value is not None:
            setattr(f, attr, value)

    # Derived from the balance sheet: screener's top ratios do
    # not carry debt-to-equity at all.
    for fn, attr in ((cp.debt_to_equity, "debt_to_equity"),
                     (cp.pledged_pct, "pledged_pct")):
        try:
            setattr(f, attr, fn(html))
        except Exception:  # noqa: BLE001 - optional, absence is normal
            pass

    try:
        f.promoter_holding_pct = _promoter_holding(cp.parse_shareholding(html))
    except Exception:  # noqa: BLE001
        pass

    for parser, attr in ((cp.parse_quarterly_results, "quarterly_sales"),
                         (cp.parse_profit_loss, "annual_sales")):
        try:
            setattr(f, attr, _series_from_table(parser(html)))
        except Exception:  # noqa: BLE001
            pass

    if f.mcap_cr is None and not f.error:
        f.error = "market cap absent from page"
    return f


async def _fetch_page(client: screener.Client, symbol: str) -> Fundamentals:
    """One company page, fetched and parsed. Never raises."""
    try:
        page = await screener.fetch_page(client, symbol)
    except screener.ScreenerError as e:
        return Fundamentals(symbol=symbol, error=f"fetch failed: {e}")
    except Exception as e:  # noqa: BLE001 - network shapes vary too much
        return Fundamentals(symbol=symbol,
                            error=f"fetch failed: {type(e).__name__}: {e}")
    try:
        return parse_page(symbol, page.html)
    except Exception as e:  # noqa: BLE001
        return Fundamentals(symbol=symbol,
                            error=f"parse failed: {type(e).__name__}: {e}")


def _run(coro_fn):
    """Run `coro_fn(client)` on a fresh event loop with one paced client.

    The client is created inside the loop and closed before it ends, so nothing
    is left bound to a dead loop. One client per batch means one login and one
    shared rate limiter for every request in it.
    """
    async def wrapper():
        async with screener.Client() as client:
            return await coro_fn(client)
    return asyncio.run(wrapper())


def fetch_one(symbol: str) -> Fundamentals:
    """Fetch and parse one company page. Never raises: a failure is recorded on
    the returned object so a 300-symbol run does not stop on one bad page."""
    return _run(lambda client: _fetch_page(client, symbol))


def cached(db, symbol: str, max_age_days: float = MAX_AGE_DAYS
           ) -> Optional[Fundamentals]:
    """Cached fundamentals, if any are fresh enough. No network."""
    age = docstore.fundamentals_age_days(db, symbol)
    if age is None or age > max_age_days:
        return None
    doc = docstore.get_fundamentals(db, symbol) or {}
    known = set(Fundamentals.__dataclass_fields__)
    f = Fundamentals(symbol=symbol,
                     **{k: v for k, v in doc.items()
                        if k in known and k != "symbol"})
    # A cached failure is not a cache hit. `_store` no longer writes one, but
    # documents written before it did are still on disk, and honouring them
    # would keep a stage that is now fixed reporting the old breakage.
    return None if f.error else f


def load_or_fetch(db, symbol: str, max_age_days: float = MAX_AGE_DAYS,
                  force: bool = False) -> Fundamentals:
    """Cached fundamentals if fresh enough, otherwise a fetch. One request max."""
    if not force:
        hit = cached(db, symbol, max_age_days)
        if hit is not None:
            return hit
    f = fetch_one(symbol)
    _store(db, symbol, f)
    return f


def _store(db, symbol: str, f: Fundamentals) -> None:
    """Cache a result, unless it is a failure.

    A failed fetch has nothing worth keeping and caching it does real harm: the
    document is fresh, so every re-run for the next day returns the failure
    without trying again. One transient timeout -- or one bug in this module --
    then reads as a company with no market cap, for a day, across every symbol
    it touched. Re-fetching costs one request; being stuck costs the stage.
    """
    if f.error:
        return
    docstore.put_fundamentals(db, symbol, f.to_doc())


def fetch_many(db, symbols: Iterable[str], max_age_days: float = MAX_AGE_DAYS,
               force: bool = False, progress_every: int = 25
               ) -> dict[str, Fundamentals]:
    """Fetch fundamentals for many symbols, caching as it goes.

    Cache hits are resolved first and never reach the network, so a re-run over
    warm cache returns immediately. The rest go out in one event loop, which
    matters twice over: the client logs in once per loop, and its
    pacing -- a minimum interval between request starts, bounded concurrency,
    and a shared cooldown when screener answers 429 -- is only a rate limit if
    every request shares one client. A sleep in this loop would be a second,
    worse rate limiter on top of a working one.
    """
    symbols = list(symbols)
    out: dict[str, Fundamentals] = {}
    todo = []
    for symbol in symbols:
        hit = None if force else cached(db, symbol, max_age_days)
        if hit is not None:
            out[symbol] = hit
        else:
            todo.append(symbol)
    if not todo:
        print(f"  all {len(symbols)} cached")
        return out

    print(f"  {len(out)} cached, fetching {len(todo)}")
    for symbol, f in _run(lambda client: _fetch_batch(client, todo, progress_every)):
        out[symbol] = f
        _store(db, symbol, f)
    return out


async def _fetch_batch(client: screener.Client, symbols: list[str],
                       progress_every: int = 25) -> list[tuple[str, Fundamentals]]:
    """Every symbol, concurrently, reporting as results land.

    Results are returned rather than written, because the docstore is not
    async-safe and writing from inside the loop would interleave with it.
    """
    done = 0
    out: list[tuple[str, Fundamentals]] = []
    tasks = [asyncio.ensure_future(_fetch_page(client, s)) for s in symbols]
    for task in asyncio.as_completed(tasks):
        f = await task
        out.append((f.symbol, f))
        done += 1
        if progress_every and done % progress_every == 0:
            print(f"  fundamentals {done}/{len(symbols)}", flush=True)
    return out


def industry_pe(fundamentals: dict[str, Fundamentals],
                industries: dict[str, str]) -> dict[str, float]:
    """Median P/E per industry, over the cohort actually scanned.

    Loss-making and absurd P/Es are excluded: a company with no earnings has no
    meaningful P/E, and leaving one in would drag the median of a small cohort.
    A median (not a mean) so one 300x outlier cannot define the peer level.
    """
    buckets: dict[str, list[float]] = {}
    for symbol, f in fundamentals.items():
        industry = (industries.get(symbol) or "").strip()
        if not industry or f.pe is None or not (0 < f.pe < 300):
            continue
        buckets.setdefault(industry, []).append(f.pe)
    return {k: statistics.median(v) for k, v in buckets.items() if v}


def pe_vs_industry(pe: Optional[float], industry_median: Optional[float]
                   ) -> Optional[float]:
    """How far a stock's P/E sits from its industry's, in percent.

    Negative means cheaper than peers -- which for the demerger case is the
    interesting direction: value not being recognised inside the current entity.
    """
    if pe is None or industry_median is None or industry_median <= 0:
        return None
    return (pe - industry_median) / industry_median * 100.0
