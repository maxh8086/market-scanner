"""Run the fixed extraction acceptance test (scanner/extractcheck.py).

    python bench_extract.py                       # vLLM on localhost:8001
    python bench_extract.py --url http://localhost:11434 --api ollama --model qwen3:8b

Order filings whose value the regex read from the mandated table are the yardstick:
the model must reproduce that rupee figure. A few guidance and expansion filings
are also run to check that the answers come back usable. Nothing is written to the
document store.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from scanner import docstore, extractcheck as ec, llm, orderval


def pick(db):
    docs = [d for d in docstore.all_filings(db) if d.get("raw_text")]
    anchored = sorted((d for d in docs if d.get("kind") == "orderbook"
                       and d.get("regex_confidence") == orderval.CONF_ANCHOR_SCALED
                       and d.get("regex_rupees")), key=lambda d: d["seq_id"])
    guidance = sorted((d for d in docs if d.get("kind") == "guidance"), key=lambda d: d["seq_id"])
    expansion = sorted((d for d in docs if d.get("kind") == "expansion"), key=lambda d: d["seq_id"])
    return (anchored[:ec.SAMPLE_SIZE], guidance[:ec.SHAPE_SAMPLE], expansion[:ec.SHAPE_SAMPLE])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:8001")
    p.add_argument("--api", default="openai", choices=["openai", "ollama"])
    p.add_argument("--model", default="qwen3-4b")
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args(argv)

    db = docstore.open_db()
    orders, guidance, expansion = pick(db)
    db.close()
    cfg = llm.LLMConfig(base_url=args.url, model=args.model, api=args.api, timeout=240)
    ok, detail = llm.health(cfg)
    print(f"{args.url}: {detail}")
    if not ok:
        return 1

    jobs = ([(d, llm.KIND_ORDER, True) for d in orders]
            + [(d, llm.KIND_GUIDANCE, False) for d in guidance]
            + [(d, llm.KIND_CAPACITY, False) for d in expansion])
    m = ec.Metrics(requested=len(orders), shape_requested=len(guidance) + len(expansion))
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda j: llm.extract(cfg, j[0]["raw_text"], j[1]), jobs))
    m.seconds = round(time.time() - started, 1)

    for (doc, kind, scored), res in zip(jobs, results):
        if not scored:
            m.shape_failed += not res.ok
            continue
        if not res.ok:
            m.failed += 1
            continue
        got = res.data.get("order_value_inr")
        outcome = ec.compare(doc.get("regex_rupees"), got)
        setattr(m, outcome, getattr(m, outcome) + 1)
        if outcome != "agree":
            print(f"  {outcome:<8} {doc['symbol']:<12} regex={doc['regex_rupees']:.0f} model={got}")
    passed, reasons = ec.verdict(m)
    print(f"\n{args.model}: {'PASS' if passed else 'FAIL'}  order agree {m.agree}/{m.requested} "
          f"({m.pct(m.agree)}%) disagree={m.disagree} missed={m.missed} failed={m.failed}; "
          f"guidance/expansion unusable {m.shape_failed}/{m.shape_requested}; {m.seconds}s")
    for r in reasons:
        print("  -", r)
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
