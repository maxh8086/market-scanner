"""Capture and store real measured resource metrics for every model call.

No prices are stored anywhere. This module records only measurements: tokens,
seconds, and GPU energy, so the user can compute cost themselves.

On-disk fallback: when Postgres is unreachable, metrics are appended as JSON
lines to logs/metrics/<run_id>.jsonl and can be loaded later with flush_pending.

One connection per process, reconnected once on failure. Metrics errors never
fail the pipeline (they are swallowed).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from .pg import db

logger = logging.getLogger(__name__)

# One connection per process, lazy-created and cached.
_connection = None
_connection_failed = False


def _get_connection():
    """Lazy connection to Postgres, reconnects once on failure."""
    global _connection, _connection_failed

    if _connection is not None:
        return _connection

    if _connection_failed:
        return None

    try:
        _connection = db.connect()
        return _connection
    except Exception as e:
        logger.debug(f"Postgres unavailable for metrics: {e}")
        _connection_failed = True
        return None


def _ensure_run_exists(run_id: uuid.UUID) -> bool:
    """Check if a run row exists in Postgres. Return True if it does, False if not."""
    try:
        conn = _get_connection()
        if not conn:
            return False
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM runs WHERE run_id = %s LIMIT 1", (str(run_id),))
            return bool(cur.fetchone())
    except Exception as e:
        logger.debug(f"Error checking run existence: {e}")
        return False


def _metrics_dir(run_id: uuid.UUID) -> Path:
    """Directory for metrics files for this run."""
    d = Path("logs") / "metrics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _jsonl_path(run_id: uuid.UUID) -> Path:
    """Path to the JSONL fallback file for a run."""
    return _metrics_dir(run_id) / f"{run_id}.jsonl"


def record_call(stage: str, source_key: str, symbol: Optional[str],
                model: str, input_tokens: int, output_tokens: int,
                seconds: float, ok: bool) -> None:
    """Record one LLM call. No-op unless RUN_ID env var is set.

    Writes to Postgres llm_calls with ON CONFLICT DO NOTHING (retries are
    counted once). Falls back to JSONL if Postgres is down. Never raises.

    Args:
        stage: 'extract' or 'conclude'
        source_key: filing seq_id or conclusion packet_hash
        symbol: stock symbol (optional)
        model: model name/id
        input_tokens: prompt token count
        output_tokens: completion token count
        seconds: elapsed time
        ok: whether the call succeeded
    """
    run_id_str = os.environ.get("RUN_ID")
    if not run_id_str:
        return  # No-op without RUN_ID

    try:
        run_id = uuid.UUID(run_id_str)
    except (ValueError, TypeError):
        logger.warning(f"Invalid RUN_ID: {run_id_str}")
        return

    call_id = uuid.uuid4()
    call_at = time.time()

    # Try Postgres first
    try:
        conn = _get_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO llm_calls
                    (call_id, run_id, symbol, stage, source_key, model,
                     input_tokens, output_tokens, seconds, ok, called_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, to_timestamp(%s))
                    ON CONFLICT (run_id, stage, source_key) DO NOTHING
                """, (str(call_id), str(run_id), symbol, stage, source_key, model,
                      input_tokens, output_tokens, seconds, ok, call_at))
            conn.commit()
            return
    except Exception as e:
        logger.debug(f"Postgres insert failed: {e}")
        try:
            if _connection is not None:
                _connection.rollback()     # an aborted transaction would fail every later call
        except Exception:
            pass
        # Fall through to JSONL

    # Fall back to JSONL
    try:
        row = {
            "call_id": str(call_id),
            "run_id": str(run_id),
            "symbol": symbol,
            "stage": stage,
            "source_key": source_key,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "seconds": seconds,
            "ok": ok,
            "called_at": call_at,
        }
        path = _jsonl_path(run_id)
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        logger.debug(f"JSONL fallback failed: {e}")


def flush_pending(run_id: uuid.UUID) -> None:
    """Load a JSONL metrics file into Postgres, idempotently.

    If the file does not exist, does nothing. If Postgres is unavailable,
    logs the error but does not raise.
    """
    path = _jsonl_path(run_id)
    if not path.exists():
        return

    try:
        conn = _get_connection()
        if not conn:
            logger.warning(f"Cannot flush metrics: Postgres unavailable")
            return

        with open(path) as f:
            loaded = 0
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO llm_calls
                            (call_id, run_id, symbol, stage, source_key, model,
                             input_tokens, output_tokens, seconds, ok, called_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                    to_timestamp(%s))
                            ON CONFLICT (run_id, stage, source_key) DO NOTHING
                        """, (row["call_id"], row["run_id"], row.get("symbol"),
                              row["stage"], row["source_key"], row["model"],
                              row["input_tokens"], row["output_tokens"],
                              row["seconds"], row["ok"], row["called_at"]))
                    loaded += 1
                except Exception as e:
                    logger.debug(f"Error loading JSONL row: {e}")

        conn.commit()
        if loaded > 0:
            logger.info(f"Loaded {loaded} metrics from JSONL for {run_id}")
    except Exception as e:
        logger.error(f"Error flushing metrics: {e}")


def finalize(run_id: uuid.UUID, gpu_csv: Optional[str] = None,
             stage_timings: Optional[dict] = None) -> None:
    """Finalize a run: fill gpu_name, gpu_watts_avg, gpu_energy_wh,
    gpu_busy_seconds, and merge stage_timings into the runs row.

    Args:
        run_id: UUID of the run
        gpu_csv: path to GPU samples CSV (timestamp, name, power.draw,
                 utilization.gpu, memory.used), or None if not measured
        stage_timings: dict of {stage_name: seconds}, merged into runs.stage_timings
    """
    flush_pending(run_id)    # calls that fell back to disk while Postgres was down
    try:
        conn = _get_connection()
        if not conn:
            logger.warning(f"Cannot finalize metrics: Postgres unavailable")
            return

        gpu_name = None
        gpu_watts_avg = None
        gpu_energy_wh = None
        gpu_busy_seconds = None

        if gpu_csv:
            gpu_name, gpu_watts_avg, gpu_energy_wh, gpu_busy_seconds = _process_gpu_csv(gpu_csv)

        stage_timings = stage_timings or {}

        with conn.cursor() as cur:
            # Ensure the run row exists (minimal row if missing)
            cur.execute("""
                INSERT INTO runs (run_id, run_date, status)
                SELECT %s, CURRENT_DATE, 'running'
                WHERE NOT EXISTS (SELECT 1 FROM runs WHERE run_id = %s)
            """, (str(run_id), str(run_id)))

            # Update the GPU and timing fields
            cur.execute("""
                UPDATE runs
                SET gpu_name = COALESCE(%s, gpu_name),
                    gpu_watts_avg = COALESCE(%s::numeric, gpu_watts_avg),
                    gpu_energy_wh = COALESCE(%s::numeric, gpu_energy_wh),
                    gpu_busy_seconds = COALESCE(%s::numeric, gpu_busy_seconds),
                    stage_timings = stage_timings || %s
                WHERE run_id = %s
            """, (gpu_name, gpu_watts_avg, gpu_energy_wh, gpu_busy_seconds,
                  json.dumps(stage_timings), str(run_id)))

        conn.commit()
    except Exception as e:
        logger.error(f"Error finalizing metrics: {e}")


def _process_gpu_csv(csv_path: str) -> tuple[Optional[str], Optional[float],
                                              Optional[float], Optional[float]]:
    """Parse GPU samples CSV and compute aggregates.

    CSV format: timestamp,name,power.draw,utilization.gpu,memory.used
    (from nvidia-smi --query-gpu=...)

    Returns: (gpu_name, gpu_watts_avg, gpu_energy_wh, gpu_busy_seconds)
    All return None if the CSV is empty or unreadable.
    """
    try:
        path = Path(csv_path)
        if not path.exists():
            return None, None, None, None

        lines = []
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip()]

        if not lines:
            return None, None, None, None

        rows = []
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                timestamp = float(parts[0])
                name = parts[1]
                power_w = float(parts[2])
                util_pct = float(parts[3])
                rows.append((timestamp, name, power_w, util_pct))
            except (ValueError, IndexError):
                continue

        if not rows:
            return None, None, None, None

        # GPU name is consistent across all rows
        gpu_name = rows[0][1]

        # Average power draw (watts)
        avg_watts = sum(r[2] for r in rows) / len(rows) if rows else None

        # Energy: integrate power over time using trapezoidal rule
        energy_ws = 0.0
        for i in range(len(rows) - 1):
            t1, _, w1, _ = rows[i]
            t2, _, w2, _ = rows[i + 1]
            dt = t2 - t1
            avg_w = (w1 + w2) / 2.0
            energy_ws += avg_w * dt

        energy_wh = energy_ws / 3600.0 if energy_ws > 0 else None

        # GPU busy time: seconds with utilization > 5%
        busy_seconds = sum(rows[i + 1][0] - rows[i][0]
                          for i in range(len(rows) - 1)
                          if rows[i][3] > 5.0)

        return gpu_name, avg_watts, energy_wh, busy_seconds if busy_seconds > 0 else None

    except Exception as e:
        logger.error(f"Error processing GPU CSV: {e}")
        return None, None, None, None


def summarize(run_id: uuid.UUID) -> dict:
    """Read llm_calls and runs tables, return usage summary.

    Returns a dict with:
        calls: number of calls
        ok: number of successful calls
        failed: number of failed calls
        input_tokens: total input tokens
        output_tokens: total output tokens
        total_tokens: input + output
        seconds: total elapsed seconds
        tokens_per_second: total tokens / total seconds (if > 0 seconds)
        tokens_per_call: average tokens per call
        calls_per_million_tokens: calls per million tokens (volume metric)
        stage_timings: dict from runs.stage_timings
        gpu_name: GPU name from runs, if measured
        gpu_watts_avg: average GPU power draw
        gpu_energy_wh: GPU energy in watt-hours
        gpu_busy_seconds: GPU busy time
    """
    try:
        conn = _get_connection()
        if not conn:
            return {"error": "Postgres unavailable"}

        result = {}

        # Read from llm_calls
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as calls,
                    SUM(CASE WHEN ok THEN 1 ELSE 0 END) as ok,
                    SUM(CASE WHEN NOT ok THEN 1 ELSE 0 END) as failed,
                    COALESCE(SUM(input_tokens), 0) as input_tokens,
                    COALESCE(SUM(output_tokens), 0) as output_tokens,
                    COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                    COALESCE(SUM(seconds), 0) as seconds
                FROM llm_calls
                WHERE run_id = %s
            """, (str(run_id),))
            row = cur.fetchone()
            if row:
                result["calls"] = row["calls"] or 0
                result["ok"] = row["ok"] or 0
                result["failed"] = row["failed"] or 0
                result["input_tokens"] = row["input_tokens"]
                result["output_tokens"] = row["output_tokens"]
                result["total_tokens"] = row["total_tokens"]
                result["seconds"] = row["seconds"]

                if result["seconds"] > 0:
                    result["tokens_per_second"] = round(result["total_tokens"] / result["seconds"], 2)
                if result["calls"] > 0:
                    result["tokens_per_call"] = round(result["total_tokens"] / result["calls"], 1)
                if result["total_tokens"] > 0:
                    result["calls_per_million_tokens"] = round(
                        result["calls"] * 1e6 / result["total_tokens"], 2)

        # Read from runs
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    stage_timings,
                    gpu_name,
                    gpu_watts_avg,
                    gpu_energy_wh,
                    gpu_busy_seconds
                FROM runs
                WHERE run_id = %s
            """, (str(run_id),))
            row = cur.fetchone()
            if row:
                result["stage_timings"] = row["stage_timings"] or {}
                result["gpu_name"] = row["gpu_name"]
                result["gpu_watts_avg"] = float(row["gpu_watts_avg"]) if row["gpu_watts_avg"] else None
                result["gpu_energy_wh"] = float(row["gpu_energy_wh"]) if row["gpu_energy_wh"] else None
                result["gpu_busy_seconds"] = float(row["gpu_busy_seconds"]) if row["gpu_busy_seconds"] else None

        return result

    except Exception as e:
        logger.error(f"Error summarizing metrics: {e}")
        return {"error": str(e)}


def main(argv=None) -> int:
    """python -m scanner.metrics finalize --run-id UUID [--gpu-csv PATH] [--timings JSON]

    Never fails the pipeline: metrics are best effort, so this always exits 0 on a
    well-formed command line.
    """
    import argparse
    ap = argparse.ArgumentParser(description="Finalize the measured resource use of a run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    fin = sub.add_parser("finalize")
    fin.add_argument("--run-id", required=True)
    fin.add_argument("--gpu-csv")
    fin.add_argument("--timings", default="{}", help='JSON {"stage": seconds}')
    sm = sub.add_parser("summary")
    sm.add_argument("--run-id", required=True)
    args = ap.parse_args(argv)
    run_id = uuid.UUID(args.run_id)
    if args.cmd == "finalize":
        gpu_csv = args.gpu_csv if args.gpu_csv and Path(args.gpu_csv).exists() else None
        finalize(run_id, gpu_csv=gpu_csv, stage_timings=json.loads(args.timings))
    else:
        print(json.dumps(summarize(run_id), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
