"""screener.in company pages: a paced fetcher and the parsers that read them.

This is the method the `screener-mcp` package (MIT, LogeshR15) uses, rewritten here
so the scanner depends on two well-known libraries (httpx, beautifulsoup4) instead of
an MCP server package that needs a newer Python, pulls in the `mcp` SDK, and crashes
at import on Windows without PYTHONUTF8. What is kept from it:

  * the page is plain HTML at /company/<SYMBOL>/consolidated/, parsed by section id
    (#top-ratios, #quarters, #profit-loss, #balance-sheet, #shareholding, #analysis);
  * a company with no subsidiaries serves a blank consolidated page, so the
    standalone page is fetched instead when the first one carries no numbers;
  * requests are paced (minimum spacing, bounded concurrency, one shared cooldown on
    a 429) because screener throttles bursts hard;
  * login is optional: SCREENER_USERNAME / SCREENER_PASSWORD give a richer page, and
    without them the public page is used.

What is left out: fuzzy symbol resolution. The scanner feeds exact NSE symbols, and a
symbol screener does not know is reported as not found rather than guessed at.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://www.screener.in"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": BASE_URL + "/",
}

_MAX_CONCURRENCY = int(os.getenv("SCREENER_MAX_CONCURRENCY", "3"))
_MIN_INTERVAL = float(os.getenv("SCREENER_MIN_INTERVAL", "0.25"))   # seconds between request starts
_MAX_RETRIES = 5
_RETRYABLE = (httpx.ConnectError, httpx.ProxyError, httpx.RemoteProtocolError,
              httpx.ReadError, httpx.TimeoutException)

_SLUG_RE = re.compile(r"^[A-Z0-9&\-_.]+$")


class ScreenerError(Exception):
    """A page could not be fetched; the message is safe to store and show."""


# --------------------------------------------------------------------------- client

class Client:
    """One paced HTTP session. Create it inside the event loop that will use it and
    close it before that loop ends (`async with Client() as c`)."""

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
        self._pace_lock = asyncio.Lock()
        self._next_slot = 0.0          # loop time the next request may start
        self._cooldown_until = 0.0     # any 429 pauses every request
        self.logged_in = False

    async def __aenter__(self) -> "Client":
        self._http = httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30.0)
        await self._login()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _wait_turn(self) -> None:
        async with self._pace_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            start = max(now, self._next_slot, self._cooldown_until)
            self._next_slot = start + _MIN_INTERVAL
        if start > now:
            await asyncio.sleep(start - now)

    def _cool_down(self, seconds: float) -> None:
        until = asyncio.get_running_loop().time() + seconds
        self._cooldown_until = max(self._cooldown_until, until)

    async def _get(self, url: str) -> httpx.Response:
        for attempt in range(_MAX_RETRIES + 1):
            async with self._semaphore:
                await self._wait_turn()
                try:
                    resp = await self._http.get(url)
                except _RETRYABLE:
                    if attempt == _MAX_RETRIES:
                        raise
                    self._cool_down(2 ** attempt)
                    continue
            if resp.status_code not in (429, 503) or attempt == _MAX_RETRIES:
                return resp
            retry_after = resp.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
            self._cool_down(min(delay, 60) + random.uniform(0, 1))
        return resp

    async def _login(self) -> None:
        user, password = os.getenv("SCREENER_USERNAME", ""), os.getenv("SCREENER_PASSWORD", "")
        if not user or not password:
            return                      # public mode
        try:
            page = await self._http.get(f"{BASE_URL}/login/")
            soup = BeautifulSoup(page.text, "lxml")
            tok = soup.find("input", {"name": "csrfmiddlewaretoken"})
            csrf = tok.get("value", "") if tok else self._http.cookies.get("csrftoken", "")
            resp = await self._http.post(
                f"{BASE_URL}/login/", headers={"Referer": f"{BASE_URL}/login/"},
                data={"username": user, "password": password,
                      "csrfmiddlewaretoken": csrf, "next": "/"})
            self.logged_in = "/login/" not in str(resp.url)
            if not self.logged_in:
                log.warning("screener login failed; continuing on the public pages")
        except Exception as e:  # noqa: BLE001 - login is optional
            log.warning("screener login error (%s); continuing on the public pages", type(e).__name__)

    async def get_html(self, path: str) -> Optional[str]:
        """The page's HTML, or None on a 404. Other failures raise ScreenerError."""
        try:
            resp = await self._get(urljoin(BASE_URL, path))
        except _RETRYABLE as e:
            raise ScreenerError(f"network error: {type(e).__name__}") from e
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise ScreenerError(f"HTTP {resp.status_code}")
        if "/login/" in str(resp.url) or "/register/" in str(resp.url):
            raise ScreenerError("screener.in asked for a login")
        return resp.text


# --------------------------------------------------------------------------- pages

@dataclass
class Page:
    symbol: str
    financial_type: str        # "consolidated" or "standalone": which one was served
    html: str


def normalize_symbol(raw: str) -> str:
    """'nse:msumi ', 'MSUMI.NS', '/company/MSUMI/' -> 'MSUMI'."""
    s = (raw or "").strip().upper()
    s = re.sub(r"^(NSE|BSE)\s*:\s*", "", s)
    s = re.sub(r"\.(NS|BO)$", "", s)
    m = re.search(r"/COMPANY/([^/]+)", s)
    if m:
        s = m.group(1)
    return s.strip("/ ")


def page_has_data(html: str) -> bool:
    """True if the page carries a price or any P&L figure. A /consolidated/ page for
    a company without subsidiaries renders the whole layout with every number blank."""
    soup = BeautifulSoup(html, "lxml")
    top = soup.find(id="top-ratios")
    if top and any(s.get_text(strip=True) for s in top.select("span.number")):
        return True
    pl = soup.find(id="profit-loss")
    if pl:
        for tr in pl.select("tbody tr"):
            if any(td.get_text(strip=True) for td in tr.find_all("td")[1:]):
                return True
    return False


async def fetch_page(client: Client, symbol: str) -> Page:
    """Consolidated page, or the standalone one when that is blank."""
    sym = normalize_symbol(symbol)
    if not sym or not _SLUG_RE.match(sym):
        raise ScreenerError(f"not a screener symbol: {symbol!r}")
    html = await client.get_html(f"/company/{sym}/consolidated/")
    if html is not None and page_has_data(html):
        return Page(sym, "consolidated", html)
    standalone = await client.get_html(f"/company/{sym}/")
    if standalone is not None and page_has_data(standalone):
        return Page(sym, "standalone", standalone)
    if html is None and standalone is None:
        raise ScreenerError(f"{sym} not found on screener.in")
    raise ScreenerError(f"{sym} page carries no figures")


# --------------------------------------------------------------------------- parsers

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_label(text: str) -> str:
    """Row label without the ' +' expand-button suffix ('Sales +', 'Borrowings +')."""
    return re.sub(r"\s*\+$", "", _clean(text))


_NON_DATA_ROWS = {"raw pdf"}


def split_ttm(table: dict[str, Any]) -> tuple[list[str], list[dict], Optional[dict]]:
    """(periods, rows without the TTM column, {label: TTM value} or None).

    Screener appends a trailing-twelve-months column to the P&L. It is not a period."""
    years = list(table.get("years", []))
    rows = table.get("rows", [])
    if not years or years[-1].upper() != "TTM":
        return years, rows, None
    n = len(years) - 1
    ttm = {r["label"]: (r["values"][n] if len(r["values"]) > n else "") for r in rows}
    return years[:n], [{**r, "values": r["values"][:n]} for r in rows], ttm


def _yearly_table(soup: BeautifulSoup, section_id: str) -> dict[str, Any]:
    """A financial table with periods as columns:
    {"years": ["Mar 2019", ...], "rows": [{"label": "Sales", "values": ["1000", ...]}]}"""
    section = soup.find(id=section_id)
    table = section.find("table") if section else None
    if not table:
        return {"years": [], "rows": []}
    head = table.find("thead")
    years = [_clean(th.get_text()) for th in head.find_all("th")][1:] if head else []
    rows = []
    for tr in table.select("tbody tr"):
        cells = [_clean(td.get_text()) for td in tr.find_all("td")]
        if not cells:
            continue
        label, values = _clean_label(cells[0]), cells[1:]
        if label.lower() in _NON_DATA_ROWS or not any(values):
            continue
        rows.append({"label": label, "values": values})
    return {"years": years, "rows": rows}


def parse_overview(html: str) -> dict[str, Any]:
    """Name, exchange codes and the #top-ratios list ('Market Cap', 'Stock P/E', ...)."""
    soup = BeautifulSoup(html, "lxml")
    name_tag = soup.find("h1")
    bse = nse = ""
    for a in soup.find_all("a", href=True):
        text = _clean(a.get_text())
        if not bse and "bseindia.com" in a["href"]:
            bse = re.sub(r"(?i)^BSE\s*:?\s*", "", text).strip()
        elif not nse and "nseindia.com/get-quotes/equity" in a["href"]:
            nse = re.sub(r"(?i)^NSE\s*:?\s*", "", text).strip()
    ratios: dict[str, str] = {}
    top = soup.find(id="top-ratios")
    if top:
        for li in top.find_all("li"):
            name_span = li.find("span", class_="name")
            if not name_span:
                continue
            key = _clean(name_span.get_text())
            numbers = li.find_all("span", class_="number")
            if key == "High / Low":
                continue
            ratios[key] = _clean(numbers[0].get_text()) if numbers else ""
    return {"name": _clean(name_tag.get_text()) if name_tag else "",
            "bse_code": bse, "nse_code": nse, "key_ratios": ratios}


def parse_profit_loss(html: str) -> dict[str, Any]:
    return _yearly_table(BeautifulSoup(html, "lxml"), "profit-loss")


def parse_balance_sheet(html: str) -> dict[str, Any]:
    return _yearly_table(BeautifulSoup(html, "lxml"), "balance-sheet")


def parse_quarterly_results(html: str) -> dict[str, Any]:
    return _yearly_table(BeautifulSoup(html, "lxml"), "quarters")


def parse_shareholding(html: str) -> dict[str, Any]:
    """Shareholding by category across quarters: {"quarters": [...], "rows": [{"category", "values"}]}."""
    soup = BeautifulSoup(html, "lxml")
    section = soup.find(id="shareholding")
    table = section.find("table") if section else None
    if not table:
        return {"quarters": [], "rows": []}
    head = table.find("thead")
    quarters = [_clean(th.get_text()) for th in head.find_all("th")][1:] if head else []
    rows = []
    for tr in table.select("tbody tr"):
        cells = [_clean(td.get_text()) for td in tr.find_all("td")]
        if cells:
            rows.append({"category": _clean_label(cells[0]), "values": cells[1:]})
    return {"quarters": quarters, "rows": rows}


def debt_to_equity(html: str) -> Optional[float]:
    """Borrowings / (Equity Capital + Reserves), latest balance-sheet column. Screener's
    top ratios do not carry it. None when the rows are missing or equity is not positive."""
    latest: dict[str, str] = {}
    for row in parse_balance_sheet(html).get("rows", []):
        label = _clean_label(row.get("label", "")).lower()
        if label in ("equity capital", "reserves", "borrowings") and row.get("values"):
            latest[label] = row["values"][-1]

    def num(v):
        try:
            return float(re.sub(r"[^0-9.\-]", "", v or ""))
        except ValueError:
            return None

    equity = (num(latest.get("equity capital")) or 0) + (num(latest.get("reserves")) or 0)
    borrowings = num(latest.get("borrowings"))
    if borrowings is None or equity <= 0:
        return None
    return round(borrowings / equity, 2)


def _cons(html: str) -> list[str]:
    box = BeautifulSoup(html, "lxml").find(id="analysis")
    section = box.find(class_="cons") if box else None
    if not section:
        return []
    return [t for t in (_clean(li.get_text()) for li in section.find_all("li")) if t]


_PLEDGE_RE = re.compile(r"promoters? ha(?:ve|s) pledged ([\d.]+)\s*% of their holding", re.I)


def pledged_pct(html: str) -> Optional[float]:
    """% of the promoter holding pledged. The shareholding table never has a pledge row;
    the page states it in its cons list ('Promoters have pledged 89.4% of their
    holding.'). None when the page does not flag a pledge."""
    for con in _cons(html):
        m = _PLEDGE_RE.search(con)
        if m:
            return float(m.group(1))
    return None
