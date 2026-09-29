"""Turn a raw order value into a judgement about whether it matters.

The premise: an order value alone carries almost no information. Rs 2,000 cr
against a Rs 500 cr market cap is transformational; Rs 200 cr against
Rs 2,00,000 cr is a rounding error. The same holds against revenue -- an order
worth a year's sales changes the business, one worth 3% of sales does not.

Everything here is pure: ratios and band lookups over numbers the caller has
already fetched. The bands are **judgement, not fact** -- they are named
constants so they can be argued with and changed in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

CRORE = 1e7

# Materiality bands. Lower bound of each, in percent.
#
# Calibrated against the cases that motivated this: a Rs 2,000 cr order on a
# Rs 500 cr cap is 400% and must read as transformational; a Rs 200 cr order on
# a Rs 2,00,000 cr cap is 0.1% and must read as negligible.
MCAP_BANDS = [
    (50.0, "TRANSFORMATIONAL"),
    (25.0, "LARGE"),
    (10.0, "MATERIAL"),
    (2.0, "MODEST"),
    (0.0, "NEGLIGIBLE"),
]

# Revenue bands sit higher than market-cap bands: an order is a multi-year
# revenue item, so order/revenue is naturally a larger ratio than order/mcap
# for the same order. Crossing 100% means the single order exceeds a full
# year of sales.
REVENUE_BANDS = [
    (100.0, "TRANSFORMATIONAL"),
    (50.0, "LARGE"),
    (20.0, "MATERIAL"),
    (5.0, "MODEST"),
    (0.0, "NEGLIGIBLE"),
]

_RANK = {
    "TRANSFORMATIONAL": 4,
    "LARGE": 3,
    "MATERIAL": 2,
    "MODEST": 1,
    "NEGLIGIBLE": 0,
}
UNKNOWN = "UNKNOWN"


def _band(pct: Optional[float], bands) -> str:
    if pct is None:
        return UNKNOWN
    for floor, label in bands:
        if pct >= floor:
            return label
    return "NEGLIGIBLE"


def _num(x) -> Optional[float]:
    """Parse screener's formatted numbers: '16,20,656', '1,234.5', '' -> float.

    A leading rupee sign and a trailing 'Cr.' are tolerated, because screener
    renders the ratio value with and without them depending on the block. Only
    those, and only as a closed set: stripping every non-numeric character
    instead would turn '1.2 Lakh' into 1.2 and be wrong by five orders of
    magnitude, which is far worse than returning None and reporting it missing.
    """
    if x is None:
        return None
    if isinstance(x, bool):
        # `isinstance(True, int)` is True, so without this a boolean becomes 1.0
        # and is reported as a one-crore figure or a 1% ratio.
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace("%", "").replace("₹", "")
    s = re.sub(r"(?i)\s*(cr\.?|crore s?)$", "", s.strip()).strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    """part/whole as a percentage, or None if not computable.

    A zero or negative denominator yields None rather than infinity: a company
    with no revenue gives no scale to measure an order against.
    """
    p, w = _num(part), _num(whole)
    if p is None or w is None or w <= 0:
        return None
    return p / w * 100.0


def growth_pct(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Percentage change. None when the base is absent or non-positive, since
    growth from zero or from a loss is not a meaningful percentage."""
    c, p = _num(current), _num(previous)
    if c is None or p is None or p <= 0:
        return None
    return (c - p) / p * 100.0


def trailing_sum(values: Sequence, n: int = 4) -> Optional[float]:
    """Sum of the last `n` parsed values, or None if fewer than `n` are usable.

    Used for trailing-four-quarter sales: the right denominator for an order,
    because a single quarter understates annual scale by ~4x.
    """
    nums = [v for v in (_num(x) for x in values) if v is not None]
    if len(nums) < n:
        return None
    return sum(nums[-n:])


@dataclass
class Significance:
    """One symbol's order value placed in context. Rupee fields are in crore,
    matching how screener reports market cap and sales."""

    order_cr: Optional[float] = None
    mcap_cr: Optional[float] = None
    ttm_sales_cr: Optional[float] = None
    annual_sales_cr: Optional[float] = None

    order_to_mcap_pct: Optional[float] = None
    order_to_ttm_sales_pct: Optional[float] = None

    qoq_growth_pct: Optional[float] = None
    yoy_growth_pct: Optional[float] = None
    annual_growth_pct: Optional[float] = None

    mcap_band: str = UNKNOWN
    revenue_band: str = UNKNOWN
    verdict: str = UNKNOWN

    def summary(self) -> str:
        """One human-readable cell for the spreadsheet."""
        if self.order_cr is None:
            return ""
        bits = [f"Rs {self.order_cr:,.0f} cr"]
        if self.order_to_mcap_pct is not None:
            bits.append(f"{self.order_to_mcap_pct:.1f}% of mcap")
        if self.order_to_ttm_sales_pct is not None:
            bits.append(f"{self.order_to_ttm_sales_pct:.1f}% of TTM sales")
        return f"{self.verdict}: " + ", ".join(bits)


def score(
    order_rupees: Optional[float],
    mcap_cr: Optional[float],
    quarterly_sales: Optional[Sequence] = None,
    annual_sales: Optional[Sequence] = None,
) -> Significance:
    """Place an order value in context of market cap and revenue.

    `order_rupees` is absolute rupees (as parsed from a filing); `mcap_cr` and
    the sales series are in crore (as screener reports them).
    """
    s = Significance()
    s.order_cr = None if order_rupees is None else order_rupees / CRORE
    s.mcap_cr = _num(mcap_cr)

    q = list(quarterly_sales or [])
    a = list(annual_sales or [])
    s.ttm_sales_cr = trailing_sum(q, 4)
    annual_nums = [v for v in (_num(x) for x in a) if v is not None]
    s.annual_sales_cr = annual_nums[-1] if annual_nums else None

    # Prefer trailing four quarters over the last reported annual figure: it is
    # more current, which matters when an order lands mid-year.
    revenue_base = s.ttm_sales_cr if s.ttm_sales_cr is not None else s.annual_sales_cr

    if s.order_cr is not None:
        s.order_to_mcap_pct = pct(s.order_cr, s.mcap_cr)
        s.order_to_ttm_sales_pct = pct(s.order_cr, revenue_base)

    q_nums = [v for v in (_num(x) for x in q) if v is not None]
    if len(q_nums) >= 2:
        s.qoq_growth_pct = growth_pct(q_nums[-1], q_nums[-2])
    if len(q_nums) >= 5:
        s.yoy_growth_pct = growth_pct(q_nums[-1], q_nums[-5])
    if len(annual_nums) >= 2:
        s.annual_growth_pct = growth_pct(annual_nums[-1], annual_nums[-2])

    s.mcap_band = _band(s.order_to_mcap_pct, MCAP_BANDS)
    s.revenue_band = _band(s.order_to_ttm_sales_pct, REVENUE_BANDS)

    # An order that is large on either measure is large. Taking the max avoids
    # a cash-rich, low-revenue company hiding a big order behind its market cap
    # (and vice versa for a thin-margin, high-revenue one).
    known = [b for b in (s.mcap_band, s.revenue_band) if b != UNKNOWN]
    s.verdict = max(known, key=lambda b: _RANK[b]) if known else UNKNOWN
    return s


def rank(verdict: str) -> int:
    """Sortable rank; UNKNOWN sorts below NEGLIGIBLE."""
    return _RANK.get(verdict, -1)
