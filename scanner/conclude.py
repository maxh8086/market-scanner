"""Per-stock conclusions from the stored insight data, written by a small local LLM.

The model is *not* asked to know anything about a company. Everything it may say
comes from the "insight packet" built here out of data the pipeline already holds:
the enriched scan row (price/ATH position, trend, fundamentals, order book,
capacity, forecast columns) and the NoSQL document store (recent filings and any
stored LLM extractions). It is a summariser over facts, and that is the only job
a 4B-parameter model can be trusted with.

Because a small model will still occasionally invent, three guards run on every
answer and none of them trusts the model:

  * Every `evidence` key the model cites must be a real field of that stock's
    packet with a real value. A point whose evidence does not exist is dropped
    and counted as ungrounded.
  * Every number written in the prose is checked against the numbers in the
    packet. Numbers with no source are listed in `unverified_numbers`, not
    silently accepted. This is a smell test, not a proof.
  * The stance is one of three fixed labels; anything else is an error result.

The conclusion never changes the ranking. It is a reading aid stored beside the
data, keyed by (symbol, as_of), and it is not investment advice.

Backend: an OpenAI-compatible chat endpoint. The compose `vllm` service serves
Qwen/Qwen3-4B-Instruct-2507 that way, but any such server works.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from . import llm

PROMPT_VERSION = 3
DEFAULT_MODEL = "qwen3-4b"            # the served name, see docker-compose.yml
STANCES = ("CONSTRUCTIVE", "MIXED", "CAUTIOUS")
MAX_FILINGS = 5

# Packet groups, in reading order. A field appears in the packet only when it has
# a value: "not available" is stated once in `data_gaps`, not once per column.
GROUPS: dict[str, tuple[str, ...]] = {
    "price": ("ltp", "ath_high", "distance_pct", "bucket", "days_since_ath",
              "listed_days", "recent_ipo", "trend", "above_ema50",
              "above_sma200", "vol_regime", "vol_percentile", "breakout_quality"),
    "fundamentals": ("mcap_cr", "pe", "industry_pe", "pe_vs_industry_pct",
                     "roce", "roe", "debt_to_equity", "pledged_pct",
                     "ttm_sales_cr", "qoq_growth_pct", "yoy_growth_pct"),
    "orders": ("order_value_cr", "order_value_date", "order_pct_of_mcap",
               "order_pct_of_sales", "order_significance", "book_to_bill",
               "orders_vs_history"),
    "corporate": ("bonus_issue", "demerger", "orderbook_signal",
                  "expansion_signal", "capacity_change", "order_capacity_plan"),
    "forecast": ("rev_ttm_growth_pct", "rev_forward_ttm_cr", "rev_ttm_dev_pct",
                 "vol_forecast_pct"),
}

SYSTEM_PROMPT = (
    "You are a careful equity research assistant for Indian listed companies. "
    "You are given a JSON fact sheet for ONE stock. Use ONLY facts in that sheet. "
    "Never use outside knowledge, never invent numbers, never give a price target "
    "or a buy/sell instruction. Do not list missing data: that is added separately, and never mention a key that is not in the sheet. Keep the conclusion to three sentences. "
    "Every point you make must cite the fact-sheet keys that support it, written "
    "exactly as they appear (for example \"price.distance_pct\"). "
    "Read the sheet as a whole: weigh order book size against sales and market cap, "
    "growth against valuation, and distance from the all-time high. Quote at least "
    "three figures from the sheet in the conclusion, exactly as written there. "
    "A missing or UNPLANNED item is a gap to mention, not by itself a reason for caution. "
    "Field meanings: price.distance_pct is how far BELOW the all-time high the price is (lower is closer to the high); "
    "fundamentals.pe_vs_industry_pct is the stock's PE relative to its industry PE, so a negative value means cheaper "
    "than the industry and a positive value dearer; every *_pct value is already a percentage. "
    "The stance is already decided by a fixed scorecard and given to you: write a conclusion that agrees with it and "
    "explains it with the figures behind it, never argue against it. "
    "Do not infer undervaluation, upside, opportunity or a target from any figure, do not compute new ratios, "
    "and do not compare a figure to anything outside the sheet. "
    "Return ONLY JSON."
)

def response_schema(keys=None) -> dict:
    """JSON schema for the answer. Arrays are capped and, when `keys` is given, evidence
    may only name fact-sheet keys: a 3.8B model otherwise loops inside an open-ended
    evidence list until it hits the token limit (seen on 2 of 5 stocks)."""
    evidence = {"type": "string"}
    if keys:
        evidence["enum"] = sorted(keys)
    point = {"type": "object",
             "properties": {"point": {"type": "string", "maxLength": 260},
                            "evidence": {"type": "array", "items": evidence,
                                         "minItems": 1, "maxItems": 4}},
             "required": ["point", "evidence"]}
    return {
        "type": "object",
        "properties": {
            "conclusion": {"type": "string", "maxLength": 900},
            "positives": {"type": "array", "items": point, "maxItems": 4},
            "concerns": {"type": "array", "items": point, "maxItems": 4},
        },
        "required": ["conclusion", "positives", "concerns"],
    }


RESPONSE_SCHEMA = response_schema()

USER_TEMPLATE = (
    "Fact sheet for {symbol} ({company}, {industry}), as of {as_of}:\n"
    "{packet}\n\n"
    "Scorecard stance (fixed, do not change it): {stance} (score {score}).\n"
    "Rules that fired: {rules}\n\n"
    "Write: a conclusion of at most three sentences that reads consistently with that stance, "
    "up to four positives and up to four concerns, each with evidence keys."
)


# --------------------------------------------------------------------------
# Insight packet
# --------------------------------------------------------------------------

def _clean(value: Any) -> Any:
    """A JSON-safe scalar, or None when there is nothing to say."""
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 2)
    if hasattr(value, "item"):            # numpy scalar
        return _clean(value.item())
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def build_packet(row: Mapping[str, Any],
                 filings: Optional[list[Mapping[str, Any]]] = None) -> dict[str, Any]:
    """Flatten one enriched row (+ document-store filings) into `group.field` facts.

    Flat dotted keys, not nested objects, so an evidence citation is a plain string
    the guard can look up.
    """
    packet: dict[str, Any] = {}
    for group, fields in GROUPS.items():
        for name in fields:
            value = _clean(row.get(name))
            if value is not None:
                packet[f"{group}.{name}"] = value

    ranked = sorted((f for f in (filings or []) if f.get("an_date")),
                    key=lambda f: f["an_date"], reverse=True)[:MAX_FILINGS]
    for i, f in enumerate(ranked, 1):
        packet[f"filing{i}.date"] = f["an_date"]
        packet[f"filing{i}.type"] = f.get("kind") or f.get("desc")
        rupees = _clean(f.get("regex_rupees"))
        if rupees:
            packet[f"filing{i}.value_cr"] = round(rupees / 1e7, 2)
        for ex_key, ex_val in (f.get("extraction") or {}).items():
            ex_val = _clean(ex_val)
            if ex_val is not None:
                packet[f"filing{i}.{ex_key}"] = ex_val
    return packet


def packet_hash(packet: Mapping[str, Any]) -> str:
    blob = json.dumps(packet, sort_keys=True, default=str)
    return hashlib.sha256(f"v{PROMPT_VERSION}|{blob}".encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# Stance scorecard
# --------------------------------------------------------------------------
# The first run let the model pick the stance and 75% of stocks came out CAUTIOUS,
# although every stock here is at or near its all-time high. A 4B model cannot weigh
# a dozen signals consistently, so the label is now computed from the fact sheet by
# fixed rules and the model only writes the prose. Six pillars, each clipped to
# [-2, +2] so no single family of columns (for example the three trend flags)
# decides the label; a missing input scores 0, never a penalty.

CONSTRUCTIVE_AT = 3          # total score >= this
CAUTIOUS_AT = -2             # total score <= this
MIN_PILLARS = 3              # fewer pillars with data than this -> MIXED, not a guess


def _num(packet: Mapping[str, Any], key: str) -> Optional[float]:
    v = packet.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def scorecard(packet: Mapping[str, Any]) -> tuple[str, int, list[str]]:
    """(stance, score, rules fired) from a fact sheet. Pure, deterministic, auditable."""
    rules: list[str] = []
    total, pillars = 0, 0

    def pillar(name: str, points: list[tuple[int, str]]) -> None:
        nonlocal total, pillars
        if not points:
            return
        pillars += 1
        score = max(-2, min(2, sum(p for p, _ in points)))
        total += score
        rules.extend(f"{name} {p:+d}: {why}" for p, why in points)

    # 1. Price trend and distance from the high
    pts = []
    trend = packet.get("price.trend")
    if trend == "UPTREND":
        pts.append((2, "price.trend UPTREND"))
    elif trend == "BELOW_BOTH":
        pts.append((-2, "price.trend BELOW_BOTH"))
    elif trend in ("ABOVE_200_ONLY", "ABOVE_50_ONLY"):
        pts.append((0, f"price.trend {trend}"))
    dist = _num(packet, "price.distance_pct")
    if dist is not None and trend != "INSUFFICIENT_HISTORY":
        if dist < 5:
            pts.append((1, f"price.distance_pct {dist:g} (within 5% of the high)"))
        elif dist > 20:
            pts.append((-1, f"price.distance_pct {dist:g} (over 20% below the high)"))
    pillar("trend", pts)

    # 2. Growth (year on year; a very weak quarter counts against it)
    pts = []
    yoy = _num(packet, "fundamentals.yoy_growth_pct")
    if yoy is not None:
        if yoy >= 35:
            pts.append((2, f"fundamentals.yoy_growth_pct {yoy:g}"))
        elif yoy >= 20:
            pts.append((1, f"fundamentals.yoy_growth_pct {yoy:g}"))
        elif yoy < 0:
            pts.append((-2, f"fundamentals.yoy_growth_pct {yoy:g} (shrinking)"))
        elif yoy < 8:
            pts.append((-1, f"fundamentals.yoy_growth_pct {yoy:g} (weak)"))
        else:
            pts.append((0, f"fundamentals.yoy_growth_pct {yoy:g}"))
    qoq = _num(packet, "fundamentals.qoq_growth_pct")
    if qoq is not None and qoq <= -30:
        pts.append((-1, f"fundamentals.qoq_growth_pct {qoq:g} (sharp quarterly fall)"))
    pillar("growth", pts)

    # 3. Quality and balance sheet
    pts = []
    roce = _num(packet, "fundamentals.roce")
    if roce is not None:
        if roce >= 20:
            pts.append((1, f"fundamentals.roce {roce:g}"))
        elif roce < 10:
            pts.append((-1, f"fundamentals.roce {roce:g} (weak)"))
        else:
            pts.append((0, f"fundamentals.roce {roce:g}"))
    de = _num(packet, "fundamentals.debt_to_equity")
    if de is not None:                       # lenders run high D/E by nature, so the bar is high
        if de > 2:
            pts.append((-1, f"fundamentals.debt_to_equity {de:g} (high)"))
        elif de < 0.3:
            pts.append((1, f"fundamentals.debt_to_equity {de:g} (low)"))
    pledged = _num(packet, "fundamentals.pledged_pct")
    if pledged is not None and pledged >= 30:
        pts.append((-1, f"fundamentals.pledged_pct {pledged:g} (promoter shares pledged)"))
    pillar("quality", pts)

    # 4. Valuation: expensive is a caution, cheap-and-growing is a positive
    pts = []
    pe = _num(packet, "fundamentals.pe")
    rel = _num(packet, "fundamentals.pe_vs_industry_pct")
    if pe is not None and pe > 100:
        pts.append((-1, f"fundamentals.pe {pe:g} (stretched)"))
    if rel is not None:
        if rel >= 100:
            pts.append((-1, f"fundamentals.pe_vs_industry_pct {rel:g} (double the industry PE)"))
        elif rel <= -30 and yoy is not None and yoy >= 15:
            pts.append((1, f"fundamentals.pe_vs_industry_pct {rel:g} (cheaper than industry while growing)"))
    if pe is not None or rel is not None:
        pillar("valuation", pts or [(0, "valuation unremarkable")])

    # 5. Forward revenue
    pts = []
    fwd = _num(packet, "forecast.rev_ttm_growth_pct")
    if fwd is not None:
        if fwd >= 25:
            pts.append((1, f"forecast.rev_ttm_growth_pct {fwd:g}"))
        elif fwd < 0:
            pts.append((-2, f"forecast.rev_ttm_growth_pct {fwd:g} (forecast shrinkage)"))
        elif fwd < 5:
            pts.append((-1, f"forecast.rev_ttm_growth_pct {fwd:g} (weak)"))
        else:
            pts.append((0, f"forecast.rev_ttm_growth_pct {fwd:g}"))
    dev = _num(packet, "forecast.rev_ttm_dev_pct")
    if dev is not None and dev > 25:
        pts.append((-1, f"forecast.rev_ttm_dev_pct {dev:g} (unsettled forecast)"))
    pillar("forecast", pts)

    # 6. Order book (rare: most stocks have none, which scores 0)
    pts = []
    vs = packet.get("orders.orders_vs_history")
    if vs == "ORDERS_AHEAD":
        pts.append((1, "orders.orders_vs_history ORDERS_AHEAD"))
    elif vs == "ORDERS_BEHIND":
        pts.append((-1, "orders.orders_vs_history ORDERS_BEHIND"))
    if packet.get("orders.order_significance") in ("MATERIAL", "TRANSFORMATIONAL"):
        pts.append((1, f"orders.order_significance {packet['orders.order_significance']}"))
    pillar("orders", pts)

    if pillars < MIN_PILLARS:
        return "MIXED", total, rules + [f"only {pillars} pillar(s) had data, so no lean"]
    if total >= CONSTRUCTIVE_AT:
        return "CONSTRUCTIVE", total, rules
    if total <= CAUTIOUS_AT:
        return "CAUTIOUS", total, rules
    return "MIXED", total, rules


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------

# A window length ("200-day EMA", "52-week high", "3-step band") names an indicator,
# it is not a claim about the stock, so it is not treated as a figure to verify.
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\d,]*\s?-?\s?(?:day|week|month|year|step)s?\b)")


def _numbers(text: str) -> list[float]:
    out = []
    for tok in _NUMBER.findall(text):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def _packet_numbers(packet: Mapping[str, Any]) -> list[float]:
    nums: list[float] = []
    for value in packet.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            nums.append(float(value))
        elif isinstance(value, str):
            nums.extend(_numbers(value))
    return nums


# What a reader would want to see and the sheet lacks. Computed, not asked of the model:
# a 4-bit 3.8B model listed fields that were on the sheet as "missing".
CORE_FIELDS = ("price.trend", "fundamentals.mcap_cr", "fundamentals.pe", "fundamentals.roce",
               "fundamentals.roe", "fundamentals.debt_to_equity", "fundamentals.yoy_growth_pct",
               "forecast.rev_ttm_growth_pct")


def data_gaps(packet: Mapping[str, Any]) -> list[str]:
    gaps = [f"{k} not available" for k in CORE_FIELDS if k not in packet]
    if not any(k.startswith("orders.") for k in packet):
        gaps.append("no order-book data")
    if not any(k.startswith("filing") for k in packet):
        gaps.append("no recent filings stored")
    return gaps


# Wording the fact sheet cannot support: the model called a fall from the high "undervaluation".
_SPECULATION = re.compile(
    r"undervalu|overvalu|upside|opportunit|potential (?:for )?(?:further |future )?(?:gain|growth)"
    r"|price target|bargain|re-?rat", re.I)


def speculative_phrases(texts: list[str]) -> list[str]:
    """Wording that claims more than the sheet says, listed for the reader to discount."""
    return sorted({m.group(0).lower() for t in texts for m in _SPECULATION.finditer(t)})


def unverified_numbers(texts: list[str], packet: Mapping[str, Any],
                       symbol: str = "") -> list[str]:
    """Numbers written in the prose that match no number in the packet.

    Matching is by value with 1% relative tolerance, plus a small absolute floor,
    so "0.9%" matches 0.91 and "Rs 2,899" matches 2899. Single digits are ignored
    ("three", "2 sentences", list numbering): they match too much to mean anything.
    Sign is ignored ("26.9% below" quotes a -26.9) and digits inside the ticker
    ("360ONE") are not figures. A number the model computed itself (a ratio or a sum
    of two facts) is still listed: it is not in the sheet, and it may be wrong.
    """
    known = [abs(k) for k in _packet_numbers(packet)]
    ticker = {float(d) for d in re.findall(r"\d+", symbol)}
    bad: list[str] = []
    for n in {abs(x) for t in texts for x in _numbers(t)}:
        if (n < 10 and n == int(n)) or n in ticker:
            continue
        # Model rounding: 12.6 for 12.63, or 13 for 12.63.
        ok = any(abs(n - k) <= max(0.01 * abs(k), 0.05) or abs(n - round(k)) < 1e-9
                 for k in known)
        if not ok:
            bad.append(f"{n:g}")
    return sorted(bad)


@dataclass
class Conclusion:
    symbol: str
    stance: str = ""
    conclusion: str = ""
    positives: list[dict] = field(default_factory=list)
    concerns: list[dict] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    ungrounded: int = 0                       # cited points dropped for bad evidence
    unverified_numbers: list[str] = field(default_factory=list)
    speculative: list[str] = field(default_factory=list)
    score: int = 0                            # scorecard total behind the stance
    rules: list[str] = field(default_factory=list)
    error: str = ""
    model: str = ""
    seconds: float = 0.0
    raw: str = ""
    packet_hash: str = ""
    prompt_version: int = PROMPT_VERSION

    @property
    def ok(self) -> bool:
        return not self.error


def _ground(points: Any, packet: Mapping[str, Any]) -> tuple[list[dict], int]:
    """Keep points whose evidence is real; return (kept, dropped)."""
    kept, dropped = [], 0
    for p in points if isinstance(points, list) else []:
        if not isinstance(p, dict) or not str(p.get("point", "")).strip():
            dropped += 1
            continue
        ev = [e for e in (p.get("evidence") or []) if isinstance(e, str)]
        valid = [e for e in ev if e in packet]
        if not valid:
            dropped += 1
            continue
        kept.append({"point": str(p["point"]).strip(), "evidence": valid})
    return kept, dropped


def validate(symbol: str, data: dict, packet: Mapping[str, Any]) -> Conclusion:
    """Turn the model's parsed JSON into a Conclusion, applying the guards."""
    stance, score, rules = scorecard(packet)
    text = str(data.get("conclusion", "")).strip()
    if not text:
        return Conclusion(symbol, error="empty conclusion")
    pos, d1 = _ground(data.get("positives"), packet)
    con, d2 = _ground(data.get("concerns"), packet)
    prose = [text] + [p["point"] for p in pos + con]
    return Conclusion(symbol=symbol, stance=stance, conclusion=text,
                      positives=pos, concerns=con, data_gaps=data_gaps(packet),
                      ungrounded=d1 + d2,
                      unverified_numbers=unverified_numbers(prose, packet, symbol),
                      speculative=speculative_phrases(prose), score=score, rules=rules)


# --------------------------------------------------------------------------
# Model call
# --------------------------------------------------------------------------

def _request_body(cfg: llm.LLMConfig, user: str, max_tokens: int, keys=None) -> dict:
    return {
        "model": cfg.model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user}],
        "temperature": cfg.temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "stock_conclusion", "schema": response_schema(keys)}},
    }


def _truncated(text: str) -> bool:
    return bool(text) and not text.rstrip().endswith((".", "!", "?"))


def _problems(res: Conclusion) -> list[str]:
    """What is wrong with an answer that parsed: wording the fact sheet cannot support,
    or a conclusion cut off by the length cap."""
    out = []
    if res.speculative:
        out.append("you used " + ", ".join(f"'{w}'" for w in res.speculative)
                   + ": a fall from the all-time high or a PE figure is not evidence of "
                     "undervaluation, overvaluation, upside or opportunity, so state the figures "
                     "without that interpretation")
    if _truncated(res.conclusion):
        out.append("the conclusion was cut off: write at most three complete, shorter sentences")
    return out


def conclude(cfg: llm.LLMConfig, symbol: str, meta: Mapping[str, Any],
             packet: Mapping[str, Any], as_of: str,
             max_tokens: int = 1400) -> Conclusion:
    """One stock in, one Conclusion out. Never raises. A 4-bit model often reads a fall
    from the high as undervaluation or runs past the length cap; one corrective retry
    names the problem, and the answer with fewer problems is kept."""
    first = _attempt(cfg, symbol, meta, packet, as_of, max_tokens)
    if not first.ok:
        return first
    problems = _problems(first)
    if not problems:
        return first
    second = _attempt(cfg, symbol, meta, packet, as_of, max_tokens,
                      note="Your previous answer was rejected: " + "; ".join(problems) + ".")
    second.seconds = round(first.seconds + second.seconds, 1)
    return second if second.ok and len(_problems(second)) < len(problems) else _keep(first, second)


def _keep(first: Conclusion, second: Conclusion) -> Conclusion:
    first.seconds = second.seconds
    return first


def _attempt(cfg: llm.LLMConfig, symbol: str, meta: Mapping[str, Any],
             packet: Mapping[str, Any], as_of: str, max_tokens: int,
             note: str = "") -> Conclusion:
    import requests

    digest = packet_hash(packet)
    if not packet:
        return Conclusion(symbol, error="empty packet", packet_hash=digest)
    stance, score, rules = scorecard(packet)
    user = USER_TEMPLATE.format(
        stance=stance, score=score, rules="; ".join(rules) or "none",
        symbol=symbol, company=meta.get("company") or symbol,
        industry=meta.get("industry") or "unknown", as_of=as_of,
        packet=json.dumps(packet, ensure_ascii=False, indent=1))
    if note:
        user += "\n\n" + note

    started = time.time()
    try:
        resp = requests.post(cfg.endpoint, json=_request_body(cfg, user, max_tokens, packet),
                             timeout=cfg.timeout)
        resp.raise_for_status()
        raw = llm._content(cfg, resp.json())
    except Exception as e:  # noqa: BLE001
        return Conclusion(symbol, error=f"{type(e).__name__}: {e}",
                          seconds=round(time.time() - started, 1),
                          model=cfg.model, packet_hash=digest)

    elapsed = round(time.time() - started, 1)
    data = llm.parse_json_response(raw)
    if data is None:
        result = Conclusion(symbol, error="response was not JSON")
    else:
        result = validate(symbol, data, packet)
    result.raw, result.seconds, result.model = raw, elapsed, cfg.model
    result.packet_hash = digest
    return result
