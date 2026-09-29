"""Fixed acceptance test for the extraction model.

Ground truth without labelling anything by hand: filings whose order value the
regex read from SEBI's mandated table field (anchor+scaled confidence) have a
value we already trust. The model is run on the same documents and must land
on the same rupee figure. A model that cannot reproduce a value the regex read
cleanly cannot be trusted with the filings the regex could not read.

Pure logic only; ``bench_extract.py`` drives the run against a live server.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from scanner import llm

SAMPLE_SIZE = 40
RUN_BUDGET_S = 420
MIN_AGREE_PCT = 90.0        # of the sampled order filings, model value == regex value
MAX_FAILED_PCT = 0.0        # a call that errors or returns unusable JSON
SHAPE_SAMPLE = 8            # per guidance/expansion kind: valid, schema-shaped answer
TOLERANCE_PCT = llm.AGREE_TOLERANCE_PCT


@dataclass
class Metrics:
    requested: int = 0
    failed: int = 0
    agree: int = 0
    disagree: int = 0
    missed: int = 0             # the model returned no value where the regex has one
    shape_requested: int = 0
    shape_failed: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    def pct(self, count: int, of: Optional[int] = None) -> float:
        base = self.requested if of is None else of
        return round(100.0 * count / base, 1) if base else 0.0


def compare(regex_rupees: Optional[float], model_rupees: Optional[float]) -> str:
    """agree / disagree / missed for one order filing with a trusted regex value."""
    if not model_rupees:
        return "missed"
    if not regex_rupees:
        return "disagree"
    gap = abs(model_rupees - regex_rupees) / regex_rupees * 100.0
    return "agree" if gap <= TOLERANCE_PCT else "disagree"


def verdict(m: Metrics) -> tuple[bool, list[str]]:
    reasons = []
    if m.requested <= 0:
        return False, ["no order filings tested"]
    if m.pct(m.failed) > MAX_FAILED_PCT:
        reasons.append(f"failed {m.pct(m.failed)}% > {MAX_FAILED_PCT}%")
    if m.pct(m.agree) < MIN_AGREE_PCT:
        reasons.append(f"agreement {m.pct(m.agree)}% < {MIN_AGREE_PCT}%")
    if m.shape_failed:
        reasons.append(f"{m.shape_failed}/{m.shape_requested} guidance/expansion answers unusable")
    if m.seconds >= RUN_BUDGET_S:
        reasons.append(f"run budget {RUN_BUDGET_S}s exceeded")
    return not reasons, reasons
