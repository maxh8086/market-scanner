"""Run the fixed acceptance test (scanner/modelcheck.py) on each candidate model.

    python bench_models.py                     # every candidate, one at a time
    python bench_models.py --only qwen3-4b,phi4-mini-awq
    python bench_models.py --restore none      # leave the GPU free afterwards

Each candidate gets its own throw-away vLLM container on port 8003 (the GPU only
holds one at a time, so trials are strictly sequential) with the same 4.5 GB
budget, 4-bit weights and FP8 KV cache. The same first SAMPLE_SIZE stocks go
through the real conclusion stage. Nothing is written to the document store or
the shared conclusions CSV; results land in output/model_bench.csv. Time budgets
are fixed in modelcheck.py: a candidate that misses one is a fail.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

import pandas as pd

import conclude as cli
from scanner import conclude, docstore, llm
from scanner import modelcheck as mc

IMAGE = "kite-ath-scanner-vllm"
VOLUME = "kite-ath-scanner_huggingface_vllm"
NAME = "ath-bench"
PORT = 8003
OUT = Path("output/model_bench.csv")


def sh(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def repo_exists(repo: str) -> bool:
    req = urllib.request.Request(f"https://huggingface.co/{repo}/resolve/main/config.json",
                                 method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True
    except urllib.error.HTTPError as e:
        return e.code in (401, 403)      # gated but present
    except OSError:
        return True                      # cannot tell offline; let the server decide


def start(cand: mc.Candidate, kv: str | None) -> None:
    sh("docker", "rm", "-f", NAME)
    cmd = ["docker", "run", "-d", "--name", NAME, "--gpus", "all", "--ipc", "host",
           "-p", f"127.0.0.1:{PORT}:8000", "-v", f"{VOLUME}:/root/.cache/huggingface"]
    for k, v in cand.env(kv).items():
        cmd += ["-e", f"{k}={v}"]
    r = sh(*cmd, IMAGE)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-300:])


def running() -> bool:
    return sh("docker", "inspect", "-f", "{{.State.Running}}", NAME).stdout.strip() == "true"


def logs() -> str:
    r = sh("docker", "logs", NAME)
    return (r.stdout or "") + (r.stderr or "")


def last_error(text: str) -> str:
    lines = [l for l in text.splitlines()
             if re.search(r"error|exception|not supported|fail", l, re.I)]
    return " / ".join(l.strip()[:160] for l in lines[-2:]) or "container exited"


def wait_ready(budget: int) -> tuple[bool, str]:
    end = time.time() + budget
    while time.time() < end:
        if not running():
            return False, last_error(logs())
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=4):
                return True, ""
        except OSError:
            time.sleep(5)
    return False, f"not healthy within {budget}s"


def memory_facts(text: str) -> dict:
    def grab(pat):
        m = re.search(pat, text)
        return m.group(1) if m else ""
    return {"weights_gib": grab(r"Model loading took ([\d.]+) GiB"),
            "kv_gib": grab(r"Available KV cache memory: ([\d.]+) GiB"),
            "kv_tokens": grab(r"GPU KV cache size: ([\d,]+) tokens").replace(",", "")}


def stocks(n: int):
    path = cli.newest_enriched()
    df = pd.read_csv(path).head(n)
    return path.stem.replace("ath_enriched_", ""), df.to_dict("records")


def run_stocks(cand: mc.Candidate, rows: list[dict], stem: str) -> tuple[list[dict], float]:
    cfg = llm.LLMConfig(base_url=f"http://127.0.0.1:{PORT}", model=cand.key, api="openai",
                        timeout=240)
    db = docstore.open_db()
    jobs = [(r["symbol"], r, conclude.build_packet(r, cli._filings(db, r["symbol"])))
            for r in rows]
    db.close()
    out: list[dict] = []
    start_t = time.time()
    pool = ThreadPoolExecutor(max_workers=mc.MAX_NUM_SEQS)
    futures = [pool.submit(conclude.conclude, cfg, s, r, p, stem) for s, r, p in jobs]
    done, pending = wait(futures, timeout=mc.RUN_BUDGET_S)
    for f in pending:
        f.cancel()
    pool.shutdown(wait=False, cancel_futures=True)
    for f in done:
        res = f.result()
        if res.ok:
            out.append({"symbol": res.symbol, "stance": res.stance, "conclusion": res.conclusion,
                        "positives": " | ".join(x["point"] for x in res.positives),
                        "concerns": " | ".join(x["point"] for x in res.concerns),
                        "unverified_numbers": " ".join(res.unverified_numbers),
                        "speculative_phrases": " | ".join(res.speculative)})
    return out, time.time() - start_t


def trial(cand: mc.Candidate, n: int) -> dict:
    result = {"key": cand.key, "model": cand.model, "quantization": cand.quantization or "none",
              "kv_cache": cand.kv_cache_dtype, "status": "", "notes": ""}
    metrics = mc.Metrics(requested=n)
    t0 = time.time()
    if not repo_exists(cand.model):
        result.update(status="FAIL", notes="model repo not found on Hugging Face")
        return {**result, "metrics": metrics, "startup_s": 0}
    kv, notes = None, []
    for attempt in (0, 1):
        try:
            start(cand, kv)
        except RuntimeError as e:
            result.update(status="FAIL", notes=f"could not start: {e}")
            return {**result, "metrics": metrics, "startup_s": 0}
        ok, why = wait_ready(mc.STARTUP_BUDGET_S)
        if ok:
            break
        text = logs()
        Path("logs").mkdir(exist_ok=True)
        Path(f"logs/bench_{cand.key}.log").write_text(text, encoding="utf-8")
        sh("docker", "rm", "-f", NAME)
        if attempt == 0 and cand.kv_fallback and "kv" in text.lower():
            notes.append(f"FP8 KV cache rejected ({why[:100]}); retried with model-default KV")
            kv = ""
            continue
        result.update(status="FAIL", notes="; ".join(notes + [f"startup: {why}"]))
        return {**result, "metrics": metrics, "startup_s": round(time.time() - t0)}
    startup = round(time.time() - t0)
    result.update(memory_facts(logs()))
    if kv == "":
        result["kv_cache"] = "default"
    stem, rows = stocks(n)
    got, seconds = run_stocks(cand, rows, stem)
    metrics = mc.measure(got, len(rows), seconds)
    passed, reasons = mc.verdict(metrics)
    if seconds >= mc.RUN_BUDGET_S:
        passed = False
        reasons.append(f"run budget {mc.RUN_BUDGET_S}s exceeded")
    result.update(status="PASS" if passed else "FAIL", notes="; ".join(notes + reasons))
    sh("docker", "rm", "-f", NAME)
    return {**result, "metrics": metrics, "startup_s": startup}


def flat(r: dict) -> dict:
    m: mc.Metrics = r["metrics"]
    return {"key": r["key"], "status": r["status"], "completed": f"{m.completed}/{m.requested}",
            "speculative": m.speculative, "empty": m.empty, "truncated": m.truncated,
            "unverified": m.unverified, "run_s": m.seconds, "startup_s": r["startup_s"],
            "weights_gib": r.get("weights_gib", ""), "kv_gib": r.get("kv_gib", ""),
            "kv_tokens": r.get("kv_tokens", ""), "quantization": r["quantization"],
            "kv_cache": r["kv_cache"], "model": r["model"], "notes": r["notes"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", help="comma-separated candidate keys")
    p.add_argument("--sample", type=int, default=mc.SAMPLE_SIZE)
    p.add_argument("--restore", default="compose",
                   help="'compose' brings the default vllm service back up; 'none' leaves the GPU free")
    p.add_argument("--out", default=str(OUT), help="results CSV")
    args = p.parse_args(argv)
    out_path = Path(args.out)
    wanted = {k.strip() for k in args.only.split(",")} if args.only else None
    cands = [c for c in mc.CANDIDATES if not wanted or c.key in wanted]

    print("Stopping the compose vllm service to free the GPU ...")
    sh("docker", "compose", "--profile", "vllm", "stop", "vllm")
    results = []
    for i, cand in enumerate(cands, 1):
        print(f"\n[{i}/{len(cands)}] {cand.key}  ({cand.model}, {cand.quantization or 'no quant'}, "
              f"kv={cand.kv_cache_dtype})", flush=True)
        r = trial(cand, args.sample)
        results.append(r)
        m = r["metrics"]
        print(f"    {r['status']}: {m.completed}/{m.requested} done in {m.seconds}s "
              f"(startup {r['startup_s']}s) spec={m.speculative} empty={m.empty} "
              f"trunc={m.truncated} unv={m.unverified}  {r['notes']}", flush=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([flat(x) for x in results]).to_csv(out_path, index=False)

    ranked = mc.rank([(r["key"], r["metrics"]) for r in results])
    by_key = {r["key"]: r for r in results}
    print("\nVerdict (best first):")
    for key, m in ranked:
        r = by_key[key]
        print(f"  {r['status']:<4} {key:<24} {m.completed}/{m.requested} spec={m.speculative} "
              f"empty={m.empty} trunc={m.truncated} unv={m.unverified} run={m.seconds}s "
              f"weights={r.get('weights_gib') or '-'}GiB kv={r.get('kv_gib') or '-'}GiB")
    print(f"\nResults: {out_path}")
    if args.restore != "none":
        print("Restoring the compose vllm service ...")
        sh("docker", "compose", "--profile", "vllm", "up", "-d", "vllm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
