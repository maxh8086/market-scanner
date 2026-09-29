"""Extract the rupee value of an order win from an NSE filing.

SEBI LODR Schedule III Part A para 4 mandates a disclosure template for order
wins whose field (g) reads `Broad consideration or size of order(s)/contract(s)
(in INR)`. That label is the anchor: the value follows it.

Measured over 964 real filings (2026-09-29), the anchored parse yields a
trustworthy figure on **36.5% of order filings** -- not the ~62% a hand read of
40 filings had suggested. Of the rest: 26.6% carry no value label at all, which
is this module's floor and the case for a model; 25.2% match the label but
answer it with prose or a non-rupee unit ("300 MW at a tariff of Rs. 6.00 per
kWh"); 11.7% use a label variant not covered here, of which `worth` is a real
gap and `order book` is correctly excluded, being cumulative rather than one
order.

Anchoring is not a nicety. Taking the largest money figure in the document gave
WELCORP Rs 45,000 cr -- it had picked up a global-market-size sentence. The
anchored parse gives Rs 4,000 cr.

Parsing is pure and separated from fetching so a better regex can be re-run
over `docstore` text without re-downloading anything.
"""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

# --------------------------------------------------------------------------
# Confidence tiers, best first. Surfaced in the output so a weak parse is never
# mistaken for a filed figure.
# --------------------------------------------------------------------------
CONF_ANCHOR_SCALED = "anchor+scaled"   # label found, value had crore/lakh/mn
CONF_ANCHOR_BARE = "anchor+bare"       # label found, plain rupee amount
CONF_LOOSE = "loose"                   # no label; largest scaled figure. Weak.
CONF_WITHHELD = "withheld"             # company explicitly declined to disclose
CONF_FOREIGN = "foreign-currency"      # value quoted in USD/EUR; not converted
CONF_NONE = "none"                     # nothing usable

# The mandated field label, in the variants issuers actually type.
_ANCHOR = re.compile(
    r"(broad\s+consideration"
    r"|consideration\s+or\s+size"
    r"|size\s+of\s+(?:the\s+)?(?:order|contract)"
    r"|order\s+value"
    r"|value\s+of\s+the\s+(?:order|contract|project|work)"
    r"|contract\s+value"
    r"|total\s+order\s+value"
    r"|aggregate\s+value)",
    re.I,
)

_RUPEE = r"(?:Rs\.?|INR|₹|Rupees)"
_SCALE_WORD = r"(crores?|cr\.?|lakhs?|lacs?|millions?|mn\.?|billions?|bn\.?)"

# Rupee amount with an explicit scale word. The marker is captured rather than
# merely optional, so `_figure_candidates` can require it where nothing else
# vouches for the unit -- see `require_marker` there.
_SCALED = re.compile(
    rf"({_RUPEE})?\s*([\d][\d,]*(?:\.\d+)?)\s*{_SCALE_WORD}", re.I)
# Bare rupee amount -- requires the Rs marker, since a bare number in a filing
# is more often a date, clause number or page number than a value.
_BARE = re.compile(rf"{_RUPEE}\s*([\d][\d,]*(?:\.\d+)?)\s*(?:/-)?", re.I)

# The scale word is required, not optional. Without it this fired on "$100",
# "$5" and "$1" -- 33 of 191 foreign readings measured over 964 real filings had
# no scale word at all, and a bare dollar figure that small is a page artefact,
# not an order value. Since a foreign reading pre-empts the rupee fallback, each
# one of those suppressed the whole document's INR figure for nothing.
_FOREIGN = re.compile(
    rf"(USD|US\$|EUR|GBP|JPY|\$)\s*([\d][\d,]*(?:\.\d+)?)\s*{_SCALE_WORD}", re.I
)

# The INR conversion an issuer supplies next to a foreign figure, as in
# "USD 412.5 Million (~ Rs 4,000 Crore)". Anchored at the start of the slice
# following the foreign match, and requiring both the rupee marker and a scale
# word, so it cannot drift onto an unrelated number further down the page.
_FX_INR_CONVERSION = re.compile(
    rf"^[\s(~\-]*"
    rf"(?:approx\.?|approximately|equivalent\s+to|equal\s+to|circa|about)?"
    rf"[\s~]*{_RUPEE}\s*([\d][\d,]*(?:\.\d+)?)\s*{_SCALE_WORD}", re.I)
_FX_INR_LOOKAHEAD = 48
# The currency marker alone, anchored to the end of a slice, so a figure can be
# tested for "is this preceded by USD?". Necessary because _SCALED makes the
# rupee marker optional: without this check "USD 45 million" parses as
# Rs 4.5 crore -- an 88x silent error, far worse than no answer.
_FX_MARKER = re.compile(r"(USD|US\$|EUR|GBP|JPY|AED|SGD|\$|€|£)\s*$", re.I)
_FX_LOOKBACK = 16

# A scale word immediately after a number: means the bare reading of those same
# digits is wrong, because it would silently drop the scale.
_SCALE_FOLLOWS = re.compile(rf"^\s*{_SCALE_WORD}", re.I)
_WITHHELD = re.compile(
    r"(cannot\s+be\s+disclosed|shall\s+not\s+be\s+disclosed|not\s+be\s+disclosed"
    r"|subject\s+to\s+confidentiality|bound\s+by\s+confidentiality"
    r"|confidentiality\s+(?:clause|agreement|obligations)"
    r"|not\s+disclosed|cannot\s+disclose|non-disclosure"
    r"|restrained\s+from\s+disclosing)",
    re.I,
)

_SCALE = {
    "crore": 1e7, "crores": 1e7, "cr": 1e7, "cr.": 1e7,
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "million": 1e6, "millions": 1e6, "mn": 1e6, "mn.": 1e6,
    "billion": 1e9, "billions": 1e9, "bn": 1e9, "bn.": 1e9,
}

# Sanity bounds in rupees. Below 1 lakh is a clause or page number; above
# Rs 10 lakh crore exceeds any single Indian order ever placed, so it is a
# misparse (a total-market-size sentence, or two numbers run together).
MIN_RUPEES = 1e5
MAX_RUPEES = 1e13

# How far past the label to look. Long enough for "The Estimated Size of Order
# as per LoA is Rs. ...", short enough not to reach the next field's value.
_WINDOW = 240


@dataclass
class OrderValue:
    """One filing's extracted value. `rupees` is None when nothing usable."""

    rupees: Optional[float]
    confidence: str
    raw: str = ""
    currency: str = "INR"

    @property
    def crore(self) -> Optional[float]:
        return None if self.rupees is None else self.rupees / 1e7

    @property
    def trustworthy(self) -> bool:
        """Anchored parses only. A `loose` figure is a guess, not a filed number."""
        return self.confidence in (CONF_ANCHOR_SCALED, CONF_ANCHOR_BARE)


def _digits(num: str) -> float:
    """Indian and Western grouping both reduce correctly by dropping commas:
    '21,57,48,840' -> 215748840 and '1,234,567' -> 1234567."""
    return float(num.replace(",", ""))


def _scaled_value(num: str, unit: str) -> Optional[float]:
    mult = _SCALE.get(unit.lower().rstrip("."))
    if mult is None:
        mult = _SCALE.get(unit.lower())
    if mult is None:
        return None
    return _digits(num) * mult


def _in_bounds(v: Optional[float]) -> bool:
    return v is not None and MIN_RUPEES <= v <= MAX_RUPEES


def normalise_text(text: str) -> str:
    """Collapse PDF whitespace so labels and values land in the same window."""
    return re.sub(r"\s+", " ", text or "").strip()


def _fx_before(text: str, start: int) -> Optional[str]:
    """The foreign-currency marker immediately preceding `start`, if any."""
    m = _FX_MARKER.search(text[max(0, start - _FX_LOOKBACK): start])
    return m.group(1).upper() if m else None


def _figure_candidates(text: str, conf: str, require_marker: bool = False
                       ) -> list[tuple[int, OrderValue]]:
    """Every readable money figure in `text`, as (position, OrderValue).

    Positions matter for the anchored path: the figure nearest the label is the
    label's value. A figure quoted in a foreign currency is returned as a
    `foreign-currency` reading with no rupee amount rather than being silently
    treated as rupees.

    `require_marker` demands an explicit Rs/INR/rupee sign on a scaled figure.
    The anchored path leaves it off, because the mandated field is headed
    "(in INR)" and issuers routinely answer it with a bare "5,482 crores" -- the
    label vouches for the unit. The unanchored path turns it on, because nothing
    does: a bare "183 Million" or "1 billion" adrift in a filing is more often
    USD, a share count or a tonnage than rupees. Read as rupees, that is how
    ADANIPORTS acquired a Rs 100 cr "order" from an investor deck's debt slide.
    """
    out: list[tuple[int, OrderValue]] = []

    for sm in _SCALED.finditer(text):
        fx = _fx_before(text, sm.start())
        if fx:
            out.append((sm.start(), OrderValue(
                None, CONF_FOREIGN, sm.group(0).strip(), currency=fx)))
            continue
        if require_marker and not sm.group(1):
            continue
        v = _scaled_value(sm.group(2), sm.group(3))
        if _in_bounds(v):
            out.append((sm.start(), OrderValue(v, conf, sm.group(0).strip())))

    for bm in _BARE.finditer(text):
        # A scale word follows: the scaled pass owns these digits. Reading them
        # bare would drop the scale, turning "Rs. 99,00,000 crore" into
        # Rs 99 lakh -- an in-bounds number that is off by a factor of a crore.
        if _SCALE_FOLLOWS.match(text[bm.end():]):
            continue
        if _fx_before(text, bm.start()):
            continue
        v = _digits(bm.group(1))
        if _in_bounds(v):
            tier = CONF_ANCHOR_BARE if conf == CONF_ANCHOR_SCALED else conf
            out.append((bm.start(), OrderValue(v, tier, bm.group(0).strip())))

    return out


def _read_window(window: str) -> Optional[OrderValue]:
    """The reading for one label's window: whichever of a money figure or an
    explicit refusal to disclose appears first."""
    nearest: Optional[tuple[int, OrderValue]] = None
    for pos, value in _figure_candidates(window, CONF_ANCHOR_SCALED):
        if nearest is None or pos < nearest[0]:
            nearest = (pos, value)
        elif pos == nearest[0] and value.confidence == CONF_ANCHOR_SCALED:
            nearest = (pos, value)  # prefer the scaled reading at a tie

    wm = _WITHHELD.search(window)
    if wm and (nearest is None or wm.start() < nearest[0]):
        return OrderValue(None, CONF_WITHHELD, wm.group(0))
    return nearest[1] if nearest else None


def parse_order_value(text: str) -> OrderValue:
    """Best-effort rupee value for one filing's text.

    Order of preference: the mandated label, then explicit withholding
    language, then the issuer's own INR conversion of a foreign figure, then the
    largest rupee figure anywhere (flagged `loose`), and only then a bare
    foreign quote. Rupees outrank a foreign reading because the value wanted is
    in INR and a foreign match used to pre-empt the rupee fallback entirely.
    """
    t = normalise_text(text)
    if not t:
        return OrderValue(None, CONF_NONE)

    # 1. Anchored on the mandated field label. Within a label's window the
    #    nearest reading wins, so "Order value: not disclosed ... paid up
    #    capital Rs. 500 crore" reports withheld instead of inventing 500 cr.
    for m in _ANCHOR.finditer(t):
        found = _read_window(t[m.end(): m.end() + _WINDOW])
        if found is not None:
            return found

    # 2. Withheld anywhere in the document.
    wm = _WITHHELD.search(t)
    if wm:
        return OrderValue(None, CONF_WITHHELD, wm.group(0))

    # 3. A foreign figure with the issuer's own INR conversion beside it, as in
    #    "USD 412.5 Million (~ Rs 4,000 Crore)". Taken before the plain foreign
    #    reading below, which used to return here with rupees=None and throw the
    #    conversion away -- a rupee value, stated by the company, two characters
    #    from the match. Tiered `loose` because we arrived here only after the
    #    anchor failed: the number is the issuer's, but nothing labels it as the
    #    order value rather than some other figure in the same sentence.
    fm = _FOREIGN.search(t)
    if fm:
        conv = _FX_INR_CONVERSION.match(
            t[fm.end(): fm.end() + _FX_INR_LOOKAHEAD])
        if conv:
            v = _scaled_value(conv.group(1), conv.group(2))
            if _in_bounds(v):
                return OrderValue(v, CONF_LOOSE, conv.group(0).strip())

    # 4. Largest rupee figure anywhere, with the Rs marker required. Weak by
    #    construction -- this is the path that produced WELCORP's Rs 45,000 cr,
    #    hence the `loose` tier, and `_best_order_for_symbol` in enrich.py must
    #    not rank on it.
    best: Optional[OrderValue] = None
    for _, value in _figure_candidates(t, CONF_LOOSE, require_marker=True):
        if value.rupees is None:
            continue
        if best is None or value.rupees > best.rupees:
            best = value
    if best is not None:
        return best

    # 5. Foreign currency with no conversion offered and no rupee figure in the
    #    document -- captured but never converted; an FX rate would be another
    #    data source and a silent source of error. Last, so that a document
    #    stating a rupee amount reports it instead of reporting "USD".
    if fm:
        return OrderValue(None, CONF_FOREIGN, fm.group(0).strip(),
                          currency=fm.group(1).upper())

    return OrderValue(None, CONF_NONE)


# --------------------------------------------------------------------------
# Fetch layer -- thin, because everything above is testable without network.
# --------------------------------------------------------------------------

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_PAGES = 8       # order filings run 1-4 pages; 8 is slack, not a real cap
REQUEST_SLEEP = 1.0  # polite; NSE archives are not rate-documented


def extract_pdf_text(content: bytes, max_pages: int = MAX_PAGES) -> str:
    """Text of the first `max_pages` pages. Returns '' for a scanned PDF."""
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(content))
    parts = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page must not lose the rest
            continue
    return normalise_text(" ".join(parts))


def fetch_filing_text(session, url: str, timeout: int = 60) -> tuple[str, int]:
    """Download one filing PDF and return (text, bytes). Raises on HTTP error."""
    resp = session.get(url, headers=UA, timeout=timeout)
    resp.raise_for_status()
    return extract_pdf_text(resp.content), len(resp.content)
