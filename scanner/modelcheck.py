"""Fixed acceptance test for candidate conclusion models.

One yardstick for every model: run the same first SAMPLE_SIZE stocks through the
conclusion stage and count the defects the guards already know about. A model
passes only if every defect rate stays under its ceiling. The time budgets are
fixed up front so a slow or broken candidate cannot stall the comparison.

Pure logic only (no Docker, no network); ``bench_models.py`` drives the trials.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SAMPLE_SIZE = 40
STARTUP_BUDGET_S = 600     # image start + weights load + warm-up until /health
RUN_BUDGET_S = 420         # all SAMPLE_SIZE stocks, 4 workers
VRAM_BUDGET_GIB = 4.5      # vLLM's own share of the 8 GB card (desktop holds ~0.9)
GPU_UTILIZATION = 0.56     # 0.56 x 8 GiB ~= 4.5 GiB
MAX_NUM_SEQS = 4
MAX_MODEL_LEN = 4096

# Ceilings, as a percentage of the stocks in the sample.
MAX_FAILED_PCT = 0.0        # every stock must produce a usable conclusion
MAX_SPECULATIVE_PCT = 10.0  # "undervalued", "upside", "price target", ...
MAX_EMPTY_PCT = 10.0        # says nothing, or contradicts its stance
MAX_TRUNCATED_PCT = 5.0     # conclusion cut off mid-sentence
MAX_UNVERIFIED_PCT = 15.0   # numbers that are not in the fact sheet


@dataclass(frozen=True)
class Candidate:
    key: str
    model: str
    quantization: str = "mxfp4"
    kv_cache_dtype: str = "fp8"
    note: str = ""
    kv_fallback: bool = False   # retry without the FP8 KV cache if the model rejects it

    def env(self, kv_cache_dtype: str | None = None) -> dict[str, str]:
        return {
            "MODEL": self.model,
            "SERVED_NAME": self.key,
            "QUANTIZATION": self.quantization,
            "KV_CACHE_DTYPE": self.kv_cache_dtype if kv_cache_dtype is None else kv_cache_dtype,
            "GPU_MEMORY_UTILIZATION": str(GPU_UTILIZATION),
            "MAX_MODEL_LEN": str(MAX_MODEL_LEN),
            "MAX_NUM_SEQS": str(MAX_NUM_SEQS),
            "MAX_NUM_BATCHED_TOKENS": "1024",
        }


CANDIDATES: tuple[Candidate, ...] = (
    Candidate("qwen3-4b", "Qwen/Qwen3-4B-Instruct-2507",
              note="online MXFP4 weights (the current default)"),
    Candidate("phi4-mini-gptq", "iqbalamo93/Phi-4-mini-instruct-GPTQ-4bit",
              quantization="gptq", note="Phi-4-mini 4-bit GPTQ"),
    Candidate("phi4-mini-awq", "drawais/Phi-4-mini-instruct-AWQ-INT4",
              quantization="", note="Phi-4-mini 4-bit (repo is compressed-tensors; auto-detected)"),
    Candidate("qwen3-1.7b-gptq", "JunHowie/Qwen3-1.7B-GPTQ-Int4",
              quantization="gptq", note="Qwen3-1.7B 4-bit GPTQ"),
    Candidate("lfm2.5-1.2b-thinking", "LiquidAI/LFM2.5-1.2B-Thinking",
              quantization="", kv_fallback=True,
              note="Liquid hybrid, native bf16 (no 4-bit build); FP8 KV may be unsupported"),
    Candidate("r1-distill-qwen-7b-awq", "casperhansen/deepseek-r1-distill-qwen-7b-awq",
              quantization="awq", note="7B 4-bit AWQ; expected not to fit the budget"),
)


@dataclass
class Metrics:
    requested: int = 0
    completed: int = 0
    failed: int = 0
    speculative: int = 0
    empty: int = 0
    truncated: int = 0
    unverified: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    def pct(self, count: int) -> float:
        return round(100.0 * count / self.requested, 1) if self.requested else 0.0


def _blank(value) -> bool:
    return not str(value or "").strip().strip("[]").strip()


def _empty(row: dict) -> bool:
    """No points at all, or missing the side its stance rests on."""
    pos, con = _blank(row.get("positives")), _blank(row.get("concerns"))
    stance = str(row.get("stance") or "")
    return (pos and con) or (stance == "CONSTRUCTIVE" and pos) or (stance == "CAUTIOUS" and con)


def _truncated(text: str) -> bool:
    text = str(text or "").strip()
    return bool(text) and not text.endswith((".", "!", "?"))


def measure(rows: list[dict], requested: int, seconds: float) -> Metrics:
    """Score CSV-shaped rows for the stocks that produced a conclusion.

    Stocks that are absent from ``rows`` (errors, timeouts) count as failures.
    """
    m = Metrics(requested=requested, seconds=round(seconds, 1))
    for row in rows:
        if _blank(row.get("conclusion")):
            continue
        m.completed += 1
        m.speculative += not _blank(row.get("speculative_phrases"))
        m.unverified += not _blank(row.get("unverified_numbers"))
        m.empty += bool(_empty(row))
        m.truncated += _truncated(row.get("conclusion"))
    m.failed = max(requested - m.completed, 0)
    return m


def verdict(m: Metrics) -> tuple[bool, list[str]]:
    """(passed, reasons it failed)."""
    if m.requested <= 0 or m.completed == 0:
        return False, ["no conclusions produced"]
    reasons = []
    for label, count, ceiling in (
        ("failed", m.failed, MAX_FAILED_PCT),
        ("speculative", m.speculative, MAX_SPECULATIVE_PCT),
        ("empty", m.empty, MAX_EMPTY_PCT),
        ("truncated", m.truncated, MAX_TRUNCATED_PCT),
        ("unverified", m.unverified, MAX_UNVERIFIED_PCT),
    ):
        if m.pct(count) > ceiling:
            reasons.append(f"{label} {m.pct(count)}% > {ceiling}%")
    return not reasons, reasons


def rank(results: list[tuple[str, Metrics]]) -> list[tuple[str, Metrics]]:
    """Passing models first, then fewest failures, fewest defects, fastest."""
    def key(item):
        _, m = item
        defects = m.speculative + m.empty + m.truncated + m.unverified
        return (not verdict(m)[0], m.failed, defects, m.seconds)
    return sorted(results, key=key)
