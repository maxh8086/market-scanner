"""Derive key ratios and daily valuation series from screener financial tables.

Pure functions, no I/O. The database writer calls these; tests run them on saved pages.

Definitions here are ours. They are checked against the values screener shows on the
same page (see tests/test_fund_derive.py). Where a definition does not match the page,
the test reports the gap instead of hiding it.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from bs4 import BeautifulSoup

from scanner.screener import _yearly_table

# Section keys -> element ids on the saved screener page. Confirmed in the saved pages.
SECTION_IDS = {
    "quarters": "quarters",
    "profit_loss": "profit-loss",
    "balance_sheet": "balance-sheet",
    "cash_flow": "cash-flow",
    "ratios": "ratios",
    "shareholding": "shareholding",
}

# Row label (footnote '+' already removed) -> canonical field. Companies differ: banks
# use Revenue, Financing Profit, Deposits and Borrowing; non-banks use Sales and Borrowings.
# Labels not listed here stay in fund_line under their own name and are not mapped.
LABEL_MAP = {
    "Sales": "sales",
    "Revenue": "sales",
    "Net Profit": "pat",
    "EPS in Rs": "eps",
    "Profit before tax": "pbt",
    "Interest": "interest",
    "OPM %": "opm_pct",
    "Dividend Payout %": "payout_pct",
    "Equity Capital": "equity_capital",
    "Reserves": "reserves",
    "Borrowings": "borrowings",
    "Borrowing": "borrowings",
    "Deposits": "deposits",
    "Total Assets": "total_assets",
    "Cash from Operating Activity": "cfo",
    "ROCE %": "roce_pct",
    "ROE %": "roe_pct",
}

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_PERIOD_RE = re.compile(r"^([A-Za-z]{3})\s+(\d{4})$")
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


@dataclass(frozen=True)
class Line:
    section: str
    period: str                 # as shown: "Mar 2025", "Sep 2025", "TTM"
    period_end: Optional[date]  # None for TTM
    label: str                  # as shown, footnote removed
    canonical: Optional[str]    # from LABEL_MAP, or None
    raw: str                    # cell text as shown
    value: Optional[float]


def to_number(text: str) -> Optional[float]:
    """'1,21,000' -> 121000.0, '859%' -> 859.0, '₹ 9,38,307 Cr.' -> 938307.0.
    Blank, '-' and non-numeric text give None."""
    match = _NUMBER_RE.search((text or "").replace("₹", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def period_end(text: str) -> Optional[date]:
    """'Mar 2025' -> 2025-03-31. 'TTM' and anything else -> None."""
    match = _PERIOD_RE.match((text or "").strip())
    if not match or match.group(1).lower() not in _MONTHS:
        return None
    month, year = _MONTHS[match.group(1).lower()], int(match.group(2))
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_lines(html: str) -> list[Line]:
    """Every value on the six financial sections, in long format."""
    soup = BeautifulSoup(html, "lxml")
    out: list[Line] = []
    for section, element_id in SECTION_IDS.items():
        table = _yearly_table(soup, element_id)
        periods = table.get("years", [])
        for row in table.get("rows", []):
            label = row["label"]
            for i, cell in enumerate(row["values"]):
                if i >= len(periods):
                    break
                out.append(Line(
                    section=section,
                    period=periods[i],
                    period_end=period_end(periods[i]),
                    label=label,
                    canonical=LABEL_MAP.get(label),
                    raw=cell,
                    value=to_number(cell),
                ))
    return out


def _by_canonical(lines: list[Line], section: str) -> dict[str, dict[str, float]]:
    """canonical field -> {period: value} for one section."""
    result: dict[str, dict[str, float]] = {}
    for line in lines:
        if line.section == section and line.canonical and line.value is not None:
            result.setdefault(line.canonical, {})[line.period] = line.value
    return result


def _latest(values: dict[str, float], periods: list[str]) -> Optional[float]:
    """Value at the most recent period in `periods` (the page lists oldest first)."""
    for period in reversed(periods):
        if period in values:
            return values[period]
    return None


def _eps_cagr_ttm_pct(annual_eps: dict[str, float], annual_periods: list[str],
                     eps_ttm: Optional[float], ttm_end: Optional[date], years: int = 5) -> Optional[float]:
    """CAGR % from the Mar column `years` years before the latest annual year, to TTM EPS.
    The end point is the TTM EPS, so the latest quarters count. The span is the real gap in
    years between the base year-end and the TTM end (about 5.5 years when the TTM ends in September).
    None when the base EPS, TTM EPS or dates are missing, or when either EPS is not positive."""
    if len(annual_periods) < years + 1 or eps_ttm is None or ttm_end is None:
        return None
    base_period = annual_periods[-(years + 1)]
    start = annual_eps.get(base_period)
    base_end = period_end(base_period)
    if start is None or base_end is None or start <= 0 or eps_ttm <= 0:
        return None
    span = (ttm_end - base_end).days / 365.25
    if span <= 0:
        return None
    return 100 * ((eps_ttm / start) ** (1 / span) - 1)


def is_bank(lines: list[Line]) -> bool:
    """Banks report Deposits on the balance sheet; other companies do not. Rows come from the page,
    so a bank is detected from its own table, not from a name list."""
    return any(l.section == "balance_sheet" and l.canonical == "deposits" and l.value is not None
               for l in lines)


def key_ratios(lines: list[Line], price: float, face_value: Optional[float] = None) -> dict[str, Any]:
    """Current key ratios from stored line items and a price.

    Every figure in the output is one of:
      - price-based (needs `price`): market cap, P/E, dividend yield
      - from annual columns (latest 'Mar YYYY' in balance sheet): book value, ROE, ROCE
      - from the TTM column of the P&L: EPS, PAT, PBT, interest

    Returns {"values": {name: float|None}, "basis": {name: str}}. A value is None when the
    inputs are missing. face_value is not in these tables; the caller supplies it from the
    overview page (face_value_from_overview). 52-week high/low is not wired yet."""
    pl = _by_canonical(lines, "profit_loss")
    bs = _by_canonical(lines, "balance_sheet")
    annual_bs_periods = [p for p in _periods(lines, "balance_sheet") if p.startswith("Mar")]

    eps_ttm = _latest(pl.get("eps", {}), ["TTM"])
    pat_ttm = _latest(pl.get("pat", {}), ["TTM"])
    pbt_ttm = _latest(pl.get("pbt", {}), ["TTM"])
    interest_ttm = _latest(pl.get("interest", {}), ["TTM"])
    # The payout row has no TTM value on screener pages (the TTM cell is blank), so use the
    # latest annual payout.
    annual_pl_periods = [p for p in _periods(lines, "profit_loss") if p.startswith("Mar")]
    payout_ttm = _latest(pl.get("payout_pct", {}), annual_pl_periods)

    equity = _latest(bs.get("equity_capital", {}), annual_bs_periods)
    reserves = _latest(bs.get("reserves", {}), annual_bs_periods)
    borrowings = _latest(bs.get("borrowings", {}), annual_bs_periods)
    net_worth = (equity + reserves) if equity is not None and reserves is not None else None

    # Shares = equity capital (Rs crore) / face value (Rs). PAT / EPS is not used: the Net Profit
    # row includes minority interest, while EPS is per owner share, so PAT / EPS overstates shares.
    shares_cr = (equity / face_value) if equity and face_value else None  # crore shares

    values: dict[str, Optional[float]] = {}
    basis: dict[str, str] = {}

    values["market_cap_cr"] = price * shares_cr if shares_cr else None
    basis["market_cap_cr"] = "price x shares (equity capital / face value)"

    values["pe"] = price / eps_ttm if eps_ttm and eps_ttm > 0 else None
    basis["pe"] = "price / TTM EPS"

    values["book_value"] = net_worth / shares_cr if net_worth and shares_cr else None
    basis["book_value"] = "(equity capital + reserves, latest Mar) / shares"

    # Owner-attributable profit = TTM EPS x shares. The Net Profit row includes minority interest.
    attributable_pat = eps_ttm * shares_cr if eps_ttm is not None and shares_cr else None
    values["roe"] = 100 * attributable_pat / net_worth if attributable_pat is not None and net_worth else None
    basis["roe"] = "TTM EPS x shares / (equity capital + reserves, latest Mar)"

    if is_bank(lines):
        # Borrowings are a bank's raw material, so this capital base has no meaning for a bank.
        values["roce"] = None
        basis["roce"] = "not applicable to banks (borrowings are operating funding)"
    else:
        capital_employed = (net_worth or 0) + (borrowings or 0) if net_worth is not None else None
        values["roce"] = (100 * (pbt_ttm + (interest_ttm or 0)) / capital_employed
                          if pbt_ttm is not None and capital_employed else None)
        basis["roce"] = "(TTM PBT + interest) / (net worth + borrowings, latest Mar)"

    dps = (payout_ttm / 100 * eps_ttm) if payout_ttm is not None and eps_ttm else None
    values["dividend_yield"] = 100 * dps / price if dps is not None and price else None
    basis["dividend_yield"] = "(payout % x TTM EPS) / price"

    # PEG = P/E / 5-year EPS CAGR (in %). Applies to banks and non-banks alike. None when the
    # growth rate is not meaningful (negative or zero EPS at either end of the window).
    quarter_ends = [end for end in (period_end(p) for p in _by_canonical(lines, "quarters").get("eps", {})) if end]
    ttm_end = max(quarter_ends) if quarter_ends else None
    eps_cagr = _eps_cagr_ttm_pct(pl.get("eps", {}), annual_pl_periods, eps_ttm, ttm_end)
    values["eps_cagr_5y_pct"] = eps_cagr
    basis["eps_cagr_5y_pct"] = ("CAGR from the Mar year 5 years before the latest annual year to TTM EPS; "
                                "None if EPS is not positive at both ends")
    pe = values.get("pe")
    values["peg"] = pe / eps_cagr if pe is not None and eps_cagr and eps_cagr > 0 else None
    basis["peg"] = "P/E / 5-year EPS CAGR (%)"

    values["face_value"] = face_value
    basis["face_value"] = ("screener #top-ratios 'Face Value' (Rs per share)" if face_value is not None
                           else "not supplied by the caller (not in the financial tables)")
    return {"values": values, "basis": basis}


def face_value_from_overview(overview: dict[str, Any]) -> Optional[float]:
    """Face value (Rs per share) from parse_overview's #top-ratios list. None when absent or not a number."""
    return to_number((overview.get("key_ratios") or {}).get("Face Value", ""))


def _periods(lines: list[Line], section: str) -> list[str]:
    seen: list[str] = []
    for line in lines:
        if line.section == section and line.period not in seen:
            seen.append(line.period)
    return seen


# --- Daily series for charts (EOD) -------------------------------------------------------

RESULT_LAG_DAYS = 45  # quarterly results are due within 45 days of quarter end (SEBI LODR)


def quarterly_eps(lines: list[Line]) -> list[tuple[date, float]]:
    """(effective date, quarterly EPS) for each reported quarter, oldest first.

    Effective date = quarter end + RESULT_LAG_DAYS. This is an assumption. The true result
    date should come from the announcements table when it is stored, to avoid using EPS
    before it was published."""
    out = []
    for period, value in _by_canonical(lines, "quarters").get("eps", {}).items():
        end = period_end(period)
        if end is not None:
            out.append((end + timedelta(days=RESULT_LAG_DAYS), value))
    return sorted(out)


def ttm_eps_on(day: date, quarters: list[tuple[date, float]]) -> Optional[float]:
    """Sum of the last four quarterly EPS values published on or before `day`."""
    published = [eps for when, eps in quarters if when <= day][-4:]
    return sum(published) if len(published) == 4 else None


def daily_valuation(closes: list[tuple[date, float]], lines: list[Line]) -> list[dict[str, Any]]:
    """One row per trading day: close, TTM EPS in force that day, and P/E.

    `closes` is (date, close) from the candles table. A day with no published TTM EPS
    gets pe=None, not zero."""
    quarters = quarterly_eps(lines)
    rows = []
    for day, close in sorted(closes):
        ttm = ttm_eps_on(day, quarters)
        pe = close / ttm if ttm and ttm > 0 else None
        rows.append({"date": day, "close": close, "ttm_eps": ttm, "pe": pe})
    return rows
