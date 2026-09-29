"""Write a short, evidence-cited conclusion for each stock in the enriched scan.

    python conclude.py                       # every stock in the newest ath_enriched_*.csv
    python conclude.py --symbols INFY,TCS    # just these
    python conclude.py --limit 10            # trial run
    python conclude.py --url http://vllm:8000   # or set CONCLUDE_URL (compose does)

Reads the enriched CSV and the document store (data/documents.json), builds a
fact sheet per stock, and asks an OpenAI-compatible server (the compose `vllm`
service: Qwen/Qwen3-4B-Instruct-2507) to summarise it. Answers are checked
against the fact sheet (see scanner/conclude.py) and stored in the document
store; results are also written to output/ath_conclusions_<date>.csv.

Re-runs are cheap: a stock whose fact sheet has not changed since its stored
conclusion is skipped unless --force is given.

Exit codes: 0 all stocks concluded, 1 model server unreachable, 2 some failed.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from scanner import conclude, docstore, llm

OUTPUT_DIR = Path("output")
ORDER_KIND = llm.KIND_ORDER


def newest_enriched() -> Path:
    files = sorted(OUTPUT_DIR.glob("ath_enriched_*.csv"))
    if not files:
        raise SystemExit("No output/ath_enriched_*.csv found. Run enrich.py --report first.")
    return files[-1]


def _filings(db, symbol: str) -> list[dict]:
    out = []
    for f in docstore.filings_for(db, symbol):
        item = dict(f)
        ex = docstore.get_extraction(db, f["seq_id"], ORDER_KIND)
        data = (ex or {}).get("data") or {}
        item["extraction"] = {k: data[k] for k in
                              ("counterparty", "counterparty_type", "execution_months")
                              if data.get(k) not in (None, "")}
        out.append(item)
    return out


def _cached(db, symbol: str, as_of: str, digest: str, model: str):
    """A stored conclusion is reusable only for the same facts, prompt and model."""
    doc = docstore.get_conclusion(db, symbol, as_of)
    if (doc and not doc.get("error") and doc.get("packet_hash") == digest
            and doc.get("prompt_version") == conclude.PROMPT_VERSION
            and doc.get("model") == model):
        return doc
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--enriched", help="enriched CSV (default: newest in output/)")
    p.add_argument("--symbols", help="comma-separated symbols only")
    p.add_argument("--limit", type=int, help="cap number of stocks (trial runs)")
    p.add_argument("--force", action="store_true", help="re-conclude even if unchanged")
    p.add_argument("--url", default=os.environ.get("CONCLUDE_URL", "http://localhost:8000"),
                   help="model server base URL (default: $CONCLUDE_URL or localhost:8000)")
    p.add_argument("--model", default=conclude.DEFAULT_MODEL, help="served model name")
    p.add_argument("--workers", type=int, default=4, help="concurrent requests")
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args(argv)

    path = Path(args.enriched) if args.enriched else newest_enriched()
    df = pd.read_csv(path)
    stem = path.stem.replace("ath_enriched_", "")
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        df = df[df["symbol"].isin(wanted)]
    if args.limit:
        df = df.head(args.limit)
    if df.empty:
        print("Nothing to conclude (no matching symbols).")
        return 0

    cfg = llm.LLMConfig(base_url=args.url, model=args.model, api="openai",
                        timeout=args.timeout)
    reachable, detail = llm.health(cfg)
    print(f"Model server {args.url}: {detail}")
    if not reachable:
        print("Start it with: docker compose --profile vllm up -d vllm  (or ./start.ps1 -WithConclusions)")
        return 1

    db = docstore.open_db()
    jobs, reused = [], 0
    for row in df.to_dict("records"):
        symbol = row["symbol"]
        packet = conclude.build_packet(row, _filings(db, symbol))
        digest = conclude.packet_hash(packet)
        if not args.force and _cached(db, symbol, stem, digest, cfg.model):
            reused += 1
            continue
        jobs.append((symbol, row, packet))
    print(f"{len(df)} stocks: {len(jobs)} to conclude, {reused} unchanged since last run")

    results: dict[str, conclude.Conclusion] = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(conclude.conclude, cfg, sym, row, packet, stem): sym
                       for sym, row, packet in jobs}
            for i, fut in enumerate(as_completed(futures), 1):
                res = fut.result()
                results[res.symbol] = res
                # Store as each answer arrives (main thread only: TinyDB is not safe for
                # concurrent writers), so a crash mid-run keeps the finished stocks.
                docstore.put_conclusion(db, res.symbol, stem,
                                        {k: v for k, v in res.__dict__.items() if k != "symbol"})
                mark = res.stance if res.ok else f"ERROR {res.error[:60]}"
                print(f"  [{i}/{len(jobs)}] {res.symbol:<12} {mark} ({res.seconds}s)")

    db.close()

    db = docstore.open_db()
    rows = []
    for symbol in df["symbol"]:
        doc = docstore.get_conclusion(db, symbol, stem)
        if not doc or doc.get("error"):
            continue
        rows.append({
            "symbol": symbol,
            "stance": doc["stance"],
            "conclusion": doc["conclusion"],
            "positives": " | ".join(x["point"] for x in doc["positives"]),
            "concerns": " | ".join(x["point"] for x in doc["concerns"]),
            "data_gaps": " | ".join(doc["data_gaps"]),
            "ungrounded_points": doc["ungrounded"],
            "unverified_numbers": " ".join(doc["unverified_numbers"]),
            "speculative_phrases": " | ".join(doc.get("speculative") or []),
            "stance_score": doc.get("score", 0),
            "stance_rules": " | ".join(doc.get("rules") or []),
            "model": doc["model"],
        })
    db.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"ath_conclusions_{stem}.csv"
    out_df = pd.DataFrame(rows, columns=[
        "symbol", "stance", "conclusion", "positives", "concerns", "data_gaps",
        "ungrounded_points", "unverified_numbers", "speculative_phrases",
        "stance_score", "stance_rules", "model"])
    out_df.to_csv(out, index=False)

    failed = [r for r in results.values() if not r.ok]
    print(f"\nWrote {out} ({len(out_df)} stocks)")
    if len(out_df):
        print("Stance: " + ", ".join(f"{k} {v}" for k, v in
                                     out_df["stance"].value_counts().items()))
        bad = int((out_df["unverified_numbers"].astype(str).str.len() > 0).sum())
        print(f"Guards: {int(out_df['ungrounded_points'].sum())} ungrounded points dropped, "
              f"{bad} stocks with numbers not found in their fact sheet")
    print("Conclusions are a reading aid over the stored data, not investment advice.")
    if failed:
        print(f"{len(failed)} stocks failed: " + ", ".join(r.symbol for r in failed[:10]))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
