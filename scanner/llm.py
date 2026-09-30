"""Local LLM extraction over stored filing text.

Runs against any OpenAI-compatible or Ollama HTTP endpoint, so the backend is a
config change rather than a code change -- llama.cpp's server image, Ollama, or
anything else that speaks either protocol. Nothing here assumes a GPU.

Why a text model and not a vision/OCR one: measured over 40 real filings, pypdf
extracted a clean text layer from 40/40. These are digitally-generated PDFs, not
scans. Running OCR would burn CPU re-deriving text that is already present. What
regex cannot do is *comprehension* -- a value in a table cell whose label is in
another cell, prose like "orders aggregating to about three hundred crore",
several orders summed into one announcement. That is a language task.
`OCR_FALLBACK_NOTE` records where a vision model would slot in if a scanned
filing ever does turn up.

Why one call per document rather than one per field: on CPU, prompt processing
dominates (a 1-4 page filing is ~2-4k tokens, the answer is ~100). Asking for
six fields in one pass costs almost exactly what asking for one costs; six
separate passes costs six times as much.

The counterparty fields are extracted even though nothing consumes them yet --
they are what a supplier/customer graph would be built from, and re-running
hours of CPU inference later to add one field would be the expensive mistake.

Every response is stored verbatim in the document store (`extractions`), keyed
by (seq_id, kind), so a prompt change can be re-run offline and diffed against
the previous answer.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# Where a vision model would go, if ever needed. Not built: 0 of 40 measured
# filings lacked a text layer. The hook is `extract_pdf_text` returning '' --
# that, and only that, is the signal that OCR is required.
OCR_FALLBACK_NOTE = (
    "If extract_pdf_text() returns '' the PDF is a scan and needs OCR. "
    "Slot a vision model (LLaVA-class, or a CPU OCR engine such as RapidOCR) "
    "in at that point only -- never ahead of the text layer."
)

KIND_ORDER = "order_v1"
KIND_CAPACITY = "capacity_v1"
# Management's own forward revenue target. A third forward estimate alongside the
# extrapolated series and the order book, and the only one where a company has
# staked its credibility on the number -- which is why the *direction* of a
# revision matters more than its level.
KIND_GUIDANCE = "guidance_v1"

# Bumped when a prompt changes, so an old extraction is recognisably old rather
# than silently mixed with new ones.
PROMPT_VERSION = 1


@dataclass
class LLMConfig:
    """Backend settings. Defaults point at Ollama's usual local port."""

    base_url: str = "http://localhost:11434"
    model: str = "qwen3:8b"
    api: str = "ollama"        # "ollama" or "openai" (llama.cpp server, vLLM, ...)
    timeout: int = 900         # CPU inference on a long filing is slow, not stuck
    temperature: float = 0.0   # extraction, not writing: no sampling
    max_input_chars: int = 12000
    num_ctx: int = 8192

    @property
    def endpoint(self) -> str:
        if self.api == "ollama":
            return f"{self.base_url.rstrip('/')}/api/chat"
        return f"{self.base_url.rstrip('/')}/v1/chat/completions"


_ORDER_SCHEMA = """{
  "order_amount": number or null,      // the figure exactly as written, commas removed, NOT converted
  "order_unit": "rupees" | "thousand" | "lakh" | "crore" | "million" | "billion" | null,
  "currency": "INR" | "USD" | "EUR" | "other",   // currency of order_amount
  "inr_amount": number or null,        // ONLY if a foreign-currency value is followed by a stated INR equivalent
  "inr_unit": "rupees" | "thousand" | "lakh" | "crore" | null,
  "value_basis": "stated" | "computed" | "withheld" | "absent",
  "counterparty": string or null,      // who placed the order, verbatim
  "counterparty_type": "government" | "psu" | "private" | "foreign" | "unknown",
  "execution_months": number or null,  // completion timeline, if stated
  "order_count": number or null,       // >1 if the filing aggregates orders
  "notes": string                      // one short sentence
}"""

_ORDER_PROMPT = """You extract facts from an Indian stock exchange filing. Return ONLY JSON.

Rules:
- SEBI mandates a field "Broad consideration or size of order(s)/contract(s) (in INR)". If present, that is the order value.
- Do NOT do any arithmetic or unit conversion. Copy the figure as written into order_amount and the scale word into order_unit.
- "Rs. 450 crore" is order_amount 450, order_unit "crore". "Rs. 7.99 Crores" is 7.99, "crore". "Rs. 12.5 lakh" is 12.5, "lakh".
- Indian digit grouping has no scale word: "Rs. 21,57,48,840/-" is order_amount 215748840, order_unit "rupees" (only the commas are removed).
- If several orders are listed and a total is stated, use the stated total. Otherwise leave order_amount null.
- If the value is given in a foreign currency, set currency accordingly, keep the figure as written, and use "million" or "billion" for the scale word.
- If the filing ALSO states an INR equivalent ("USD 7.6 Mn (Rs. 67.16 Cr approximately)"), copy that stated INR figure into inr_amount and inr_unit ("67.16", "crore"). Never work one out yourself; if no INR figure is stated, leave both null.
- If the company says the value is confidential, set value_basis "withheld" and order_amount null.
- Do NOT use a figure that is the company's revenue, market size, paid-up capital, or a past order. If unsure, set order_amount null and say why in notes.
- counterparty is the customer awarding the order, not the filing company.

Schema:
{schema}

Filing text:
---
{text}
---
JSON:""".replace("{schema}", _ORDER_SCHEMA)


_CAPACITY_SCHEMA = """{
  "existing_capacity": string or null,   // verbatim, with unit, e.g. "1.2 MTPA"
  "proposed_capacity": string or null,   // verbatim, with unit
  "capacity_unit": string or null,
  "capacity_multiple": number or null,   // proposed / existing, if both known
  "capex_amount": number or null,        // figure as written, not converted
  "capex_unit": "rupees" | "thousand" | "lakh" | "crore" | "million" | "billion" | null,
  "commissioning_target": string or null,
  "is_planned": true or false,           // false if aspirational/exploratory
  "notes": string
}"""

_CAPACITY_PROMPT = """You extract facts from an Indian stock exchange filing about expansion. Return ONLY JSON.

Rules:
- existing_capacity and proposed_capacity must be quoted with their units exactly as the filing states them.
- If the filing gives only a post-expansion total, put it in proposed_capacity and leave existing_capacity null.
- capacity_multiple only when BOTH figures are known and in the same unit. Otherwise null.
- capex_amount and capex_unit as written, with no arithmetic ("Rs. 300 crore" is capex_amount 300, capex_unit "crore").
- is_planned is false when the filing only says the board is "evaluating" or "exploring".
- Never infer a number the filing does not state.

Schema:
{schema}

Filing text:
---
{text}
---
JSON:""".replace("{schema}", _CAPACITY_SCHEMA)

_GUIDANCE_SCHEMA = """{
  "has_guidance": true or false,
  "direction": "RAISED" or "LOWERED" or "REAFFIRMED" or "NEW" or "WITHDRAWN" or "NONE",
  "metric": string or null,              // "revenue", "EBITDA margin", "volume"
  "target_amount": number or null,       // figure as written, not converted, if a level is given
  "target_unit": "rupees" | "thousand" | "lakh" | "crore" | "million" | "billion" | null,
  "growth_pct": number or null,          // if stated as growth instead
  "margin_pct": number or null,          // if the guidance is a margin
  "period": string or null,              // "FY27", "next 3 years", as filed
  "is_management_statement": true or false,
  "verbatim": string,                    // the sentence the numbers came from
  "notes": string
}"""

_GUIDANCE_PROMPT = """You extract management's forward-looking guidance from an Indian listed company's disclosure. Return ONLY JSON.

Rules:
- Guidance is a forward TARGET management commits to or projects. It is NOT a past result.
- "Revenue grew 22% last year" is a RESULT, not guidance. has_guidance false.
- "We expect to reach Rs 1,200 crore revenue in FY27" is guidance: target_amount 1200, target_unit "crore", period "FY27".
- "We guide to 18-20% growth" is guidance: growth_pct 19 (midpoint), and say in notes that it was a range.
- direction: RAISED if the filing says the earlier target has been increased; LOWERED if cut; REAFFIRMED if restated unchanged; NEW if given for the first time; WITHDRAWN if management has pulled it.
- If the filing does not say whether it revises an earlier target, use NEW.
- Copy target_amount and target_unit as written; do no arithmetic.
- is_management_statement false if the number comes from an analyst, a broker note, or a newspaper quoted in the filing. Only the company's own words count.
- verbatim must be copied from the text, not paraphrased. If you cannot quote it, has_guidance is false.
- Never infer a target from an order book, a capex plan, or a capacity figure. Those are different disclosures.

Schema:
{schema}

Filing text:
---
{text}
---
JSON:""".replace("{schema}", _GUIDANCE_SCHEMA)

PROMPTS = {KIND_ORDER: _ORDER_PROMPT, KIND_CAPACITY: _CAPACITY_PROMPT,
           KIND_GUIDANCE: _GUIDANCE_PROMPT}

# The filing text goes in at this placeholder. Substitution is `str.replace`,
# not %-formatting and not str.format: the schemas above are JSON and are full of
# braces, and a prompt that has to discuss percentage growth is full of percent
# signs. Both of those are literals a prompt author should be able to write once,
# without escaping them for a formatter.
TEXT_SLOT = "{text}"


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props,
            "required": required if required is not None else list(props),
            "additionalProperties": False}


_NUM = {"type": ["number", "null"]}
_STR = {"type": ["string", "null"]}
_UNIT = {"enum": ["rupees", "thousand", "lakh", "crore", "million", "billion", None]}

# The model reads a figure and its scale word; the code does the multiplication. A 4-bit
# 4B model reading "Rs. 7.99 Crores" answered 799000000 (x10 too big) on most order filings.
UNIT_MULTIPLIER = {"rupees": 1.0, "thousand": 1e3, "lakh": 1e5, "crore": 1e7,
                   "million": 1e6, "billion": 1e9}
# (amount field, unit field, rupee field the rest of the pipeline reads)
_MONEY_FIELDS = ((("order_amount", "order_unit", "order_value_inr"), KIND_ORDER),
                 (("capex_amount", "capex_unit", "capex_inr"), KIND_CAPACITY),
                 (("target_amount", "target_unit", "target_inr"), KIND_GUIDANCE))


def to_rupees(amount, unit) -> Optional[float]:
    """Amount x scale word as absolute rupees; None if either is missing or unknown."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None
    mult = UNIT_MULTIPLIER.get(str(unit or "").strip().lower())
    return amount * mult if mult else None


def add_rupees(kind: str, data: dict) -> dict:
    """Fill the *_inr field from the amount and unit the model read. A foreign-currency
    order takes the INR equivalent the company itself stated, else stays null: the value
    is never converted here."""
    for (amount, unit, out), k in _MONEY_FIELDS:
        if k != kind or amount not in data:
            continue
        if kind == KIND_ORDER and str(data.get("currency") or "INR").upper() != "INR":
            data[out] = to_rupees(data.get("inr_amount"), data.get("inr_unit"))
        else:
            data[out] = to_rupees(data.get(amount), data.get(unit))
    return data

# Real JSON Schemas for a server that enforces them (vLLM's structured outputs). The
# pseudo-schemas in the prompts tell the model what each field means; these make the
# answer parse. Field names must stay in step with the prompt schemas above.
SCHEMAS: dict[str, dict] = {
    KIND_ORDER: _obj({
        "order_amount": _NUM,
        "order_unit": _UNIT,
        "currency": {"enum": ["INR", "USD", "EUR", "other"]},
        "inr_amount": _NUM,
        "inr_unit": {"enum": ["rupees", "thousand", "lakh", "crore", None]},
        "value_basis": {"enum": ["stated", "computed", "withheld", "absent"]},
        "counterparty": _STR,
        "counterparty_type": {"enum": ["government", "psu", "private", "foreign", "unknown"]},
        "execution_months": _NUM,
        "order_count": _NUM,
        "notes": {"type": "string", "maxLength": 300},
    }),
    KIND_CAPACITY: _obj({
        "existing_capacity": _STR,
        "proposed_capacity": _STR,
        "capacity_unit": _STR,
        "capacity_multiple": _NUM,
        "capex_amount": _NUM,
        "capex_unit": _UNIT,
        "commissioning_target": _STR,
        "is_planned": {"type": "boolean"},
        "notes": {"type": "string", "maxLength": 300},
    }),
    KIND_GUIDANCE: _obj({
        "has_guidance": {"type": "boolean"},
        "direction": {"enum": ["RAISED", "LOWERED", "REAFFIRMED", "NEW", "WITHDRAWN", "NONE"]},
        "metric": _STR,
        "target_amount": _NUM,
        "target_unit": _UNIT,
        "growth_pct": _NUM,
        "margin_pct": _NUM,
        "period": _STR,
        "is_management_statement": {"type": "boolean"},
        "verbatim": {"type": "string", "maxLength": 500},
        "notes": {"type": "string", "maxLength": 300},
    }),
}

# A vLLM server here runs a 4096-token context: the prompt (~0.7k), the answer and the
# filing text must all fit. The mandated disclosure sits at the top of a filing, so the
# text is cut from the tail. Ollama runs its own, larger num_ctx and keeps the config cap.
OPENAI_MAX_INPUT_CHARS = 8000
OPENAI_MAX_TOKENS = 500


@dataclass
class LLMResult:
    """One extraction. `data` is the parsed JSON, `raw` the model's own text."""

    data: dict = field(default_factory=dict)
    raw: str = ""
    error: str = ""
    seconds: float = 0.0
    model: str = ""
    prompt_version: int = PROMPT_VERSION
    input_tokens: int = 0          # prompt token count
    output_tokens: int = 0         # completion token count

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.data)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def parse_json_response(text: str) -> Optional[dict]:
    """Pull a JSON object out of a model response.

    Small local models wrap JSON in prose or markdown fences and, when a
    thinking-capable model is used, may emit a <think> block first. Each of
    these is handled rather than treated as a failure, because re-running a
    CPU inference to recover from punctuation is expensive.
    """
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    fenced = _FENCE.search(text)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    # Outermost braces, for a response with prose on either side.
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first: last + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _payload(cfg: LLMConfig, prompt: str, kind: Optional[str] = None) -> dict:
    messages = [{"role": "user", "content": prompt}]
    if cfg.api == "ollama":
        return {
            "model": cfg.model,
            "messages": messages,
            "stream": False,
            "format": "json",  # Ollama constrains decoding to valid JSON
            "options": {"temperature": cfg.temperature, "num_ctx": cfg.num_ctx},
        }
    body = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": OPENAI_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    if kind in SCHEMAS:
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": kind, "schema": SCHEMAS[kind]}}
    return body


def _content(cfg: LLMConfig, body: dict) -> str:
    if cfg.api == "ollama":
        return (body.get("message") or {}).get("content", "")
    choices = body.get("choices") or [{}]
    return (choices[0].get("message") or {}).get("content", "")


def _extract_tokens(cfg: LLMConfig, body: dict) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from a response body.

    Ollama: prompt_eval_count and eval_count
    OpenAI: usage.prompt_tokens and usage.completion_tokens

    Returns (0, 0) if tokens are not present in the response.
    """
    if cfg.api == "ollama":
        prompt = body.get("prompt_eval_count", 0)
        completion = body.get("eval_count", 0)
        return (prompt, completion)
    # OpenAI style
    usage = body.get("usage", {})
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    return (prompt, completion)


def health(cfg: LLMConfig, timeout: int = 5) -> tuple[bool, str]:
    """Is the backend reachable? Checked once before a long batch, so a wrong
    port fails in a second instead of after the first 15-minute timeout."""
    import requests

    url = (f"{cfg.base_url.rstrip('/')}/api/tags" if cfg.api == "ollama"
           else f"{cfg.base_url.rstrip('/')}/v1/models")
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    names = ""
    try:
        body = resp.json()
        items = body.get("models") or body.get("data") or []
        names = ", ".join(
            str(m.get("name") or m.get("id", "")) for m in items[:20])
    except Exception:  # noqa: BLE001
        pass
    if names and cfg.model.split(":")[0] not in names:
        return True, f"reachable, but '{cfg.model}' not in: {names}"
    return True, names or "reachable"


def extract(cfg: LLMConfig, text: str, kind: str = KIND_ORDER,
            source_key: Optional[str] = None, symbol: Optional[str] = None) -> LLMResult:
    """Run one extraction. Never raises -- the error lands on the result.

    Args:
        cfg: LLMConfig
        text: filing text to extract from
        kind: KIND_ORDER, KIND_CAPACITY, or KIND_GUIDANCE
        source_key: filing seq_id for metrics; if not provided, derived from text hash
        symbol: stock symbol for metrics; optional
    """
    import requests

    if kind not in PROMPTS:
        return LLMResult(error=f"unknown extraction kind: {kind}")
    if not text or not text.strip():
        return LLMResult(error="no text to extract from")

    # Truncating from the front: the mandated disclosure table is near the top
    # of an order filing, and the tail is boilerplate and signatures.
    limit = cfg.max_input_chars
    if cfg.api != "ollama":
        limit = min(limit, OPENAI_MAX_INPUT_CHARS)

    # Derive source_key from text hash if not provided, for metrics logging
    if not source_key:
        import hashlib
        source_key = hashlib.sha256(text.encode()).hexdigest()[:16]

    started = time.time()
    raw = ""
    response_body = {}
    try:
        for attempt in (0, 1):
            prompt = PROMPTS[kind].replace(TEXT_SLOT, text[:limit])
            resp = requests.post(cfg.endpoint, json=_payload(cfg, prompt, kind),
                                 timeout=cfg.timeout)
            # Text that overflows the server's context is a 400; one retry on half as
            # much text beats losing the document.
            if resp.status_code == 400 and attempt == 0 and "context" in resp.text.lower():
                limit //= 2
                continue
            resp.raise_for_status()
            response_body = resp.json()
            raw = _content(cfg, response_body)
            break
    except Exception as e:  # noqa: BLE001
        elapsed = round(time.time() - started, 1)
        # Record the failed call
        from . import metrics
        metrics.record_call("extract", source_key, symbol, cfg.model, 0, 0, elapsed, False)
        return LLMResult(error=f"{type(e).__name__}: {e}",
                         seconds=elapsed,
                         model=cfg.model)

    elapsed = round(time.time() - started, 1)
    input_tokens, output_tokens = _extract_tokens(cfg, response_body)

    data = parse_json_response(raw)
    ok = data is not None
    if data is None:
        result = LLMResult(raw=raw, error="response was not JSON",
                          seconds=elapsed, model=cfg.model,
                          input_tokens=input_tokens, output_tokens=output_tokens)
    else:
        result = LLMResult(data=add_rupees(kind, data), raw=raw, seconds=elapsed,
                          model=cfg.model, input_tokens=input_tokens,
                          output_tokens=output_tokens)

    # Record the call
    from . import metrics
    metrics.record_call("extract", source_key, symbol, cfg.model, input_tokens,
                       output_tokens, elapsed, ok)

    return result


# --------------------------------------------------------------------------
# Cross-checking the model against the regex
# --------------------------------------------------------------------------

AGREE = "agree"
DISAGREE = "disagree"
LLM_ONLY = "llm-only"
REGEX_ONLY = "regex-only"
NEITHER = "neither"

# Within 2% counts as agreement: the two paths round differently (a model may
# read "about Rs 450 crore" as 450, the regex as 450.00) and that is not a
# disagreement worth flagging.
AGREE_TOLERANCE_PCT = 2.0


def cross_check(regex_rupees: Optional[float],
                llm_rupees: Optional[float]) -> str:
    """Compare the two extraction paths for one filing.

    Agreement between an anchored regex and a language model is strong evidence
    the number is right. Disagreement is the interesting case: it means one of
    them misread the document, and it is worth a human glance rather than a
    silent pick. This is why the LLM does not simply overwrite the regex.
    """
    if regex_rupees is None and llm_rupees is None:
        return NEITHER
    if regex_rupees is None:
        return LLM_ONLY
    if llm_rupees is None:
        return REGEX_ONLY
    if regex_rupees <= 0:
        return DISAGREE
    delta = abs(llm_rupees - regex_rupees) / regex_rupees * 100.0
    return AGREE if delta <= AGREE_TOLERANCE_PCT else DISAGREE
