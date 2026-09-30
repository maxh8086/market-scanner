"""API routes for the ATH Scanner UI."""

import json
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, date
from croniter import croniter

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from scanner.pg import db
from scanner.collect import settings as collector_settings
from ui.app import queries

router = APIRouter()

class ConfigUpdateRequest(BaseModel):
    mode: str
    cron: str
    params: Optional[Dict[str, Any]] = None

def safe_connection():
    """Get a database connection, return None if unavailable."""
    try:
        return db.connect()
    except Exception:
        return None

def serialize_row(row):
    """Convert a row dict with date/datetime objects to JSON-serializable format."""
    if not row:
        return row
    result = {}
    for key, value in row.items():
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = value
        else:
            result[key] = value
    return result

# ---- HOME / RUNS ----
@router.get("/runs")
async def get_runs(limit: int = Query(50, ge=1, le=200)):
    """Get latest runs for the home page."""
    conn = safe_connection()
    if not conn:
        return {"runs": [], "error": "Database unavailable"}

    try:
        rows = conn.execute(queries.LATEST_RUNS).fetchall()
        return {"runs": [serialize_row(r) for r in rows]}
    finally:
        conn.close()

@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get a specific run's dashboard data."""
    conn = safe_connection()
    if not conn:
        return {"error": "Database unavailable"}

    try:
        run = conn.execute(queries.RUN_BY_ID, (run_id,)).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        stats = conn.execute(queries.RUN_SUMMARY_STATS, (run_id,)).fetchone()
        changes = conn.execute(queries.CHANGES_SINCE_PREVIOUS, (run_id,)).fetchall()
        changes_dict = {row["kind"]: row["count"] for row in changes}

        return {
            "run": serialize_row(run),
            "stats": serialize_row(stats),
            "changes": changes_dict,
        }
    finally:
        conn.close()

# ---- RESULTS TABLE ----
@router.get("/runs/{run_id}/results")
async def get_results(
    run_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sort: str = Query("symbol"),
    order: str = Query("asc"),
    bucket: Optional[str] = None,
    stance: Optional[str] = None,
    search: Optional[str] = None,
):
    """Get paginated results table with sorting and filtering."""
    conn = safe_connection()
    if not conn:
        return {"error": "Database unavailable", "results": [], "total": 0}

    try:
        where_parts = ["ss.run_id = %s"]
        params = [run_id]

        if bucket and bucket != "all":
            where_parts.append("ss.bucket = %s")
            params.append(bucket)

        if stance and stance != "all":
            where_parts.append("ss.stance = %s")
            params.append(stance)

        if search:
            where_parts.append("(ss.symbol ILIKE %s OR ss.company ILIKE %s)")
            search_param = f"%{search}%"
            params.extend([search_param, search_param])

        where_clause = " AND ".join(where_parts)

        allowed_cols = ["symbol", "company", "ltp", "distance_pct", "stance", "bucket"]
        sort_col = sort if sort in allowed_cols else "symbol"
        order_dir = "ASC" if order.lower() == "asc" else "DESC"

        order_by = f"ss.{sort_col} {order_dir}"

        count_query = f"SELECT COUNT(*) as total FROM stock_snapshots ss WHERE {where_clause}"
        count_result = conn.execute(count_query, params).fetchone()
        total = count_result["total"] if count_result else 0

        offset = (page - 1) * per_page
        result_query = f"""
            SELECT
              ss.symbol, ss.company, ss.industry, ss.ltp, ss.distance_pct,
              ss.ath_date, ss.one_year_return_pct, ss.order_pct_of_sales,
              ss.stance, ss.bucket
            FROM stock_snapshots ss
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
        """
        params.extend([per_page, offset])

        rows = conn.execute(result_query, params).fetchall()

        return {
            "results": [serialize_row(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }
    finally:
        conn.close()

# ---- STOCK DASHBOARD ----
@router.get("/stocks/{symbol}")
async def get_stock(symbol: str):
    """Get stock dashboard with latest snapshot, timeline, and metrics."""
    conn = safe_connection()
    if not conn:
        return {"error": "Database unavailable"}

    try:
        snapshot = conn.execute(queries.STOCK_LATEST_SNAPSHOT, (symbol,)).fetchone()
        if not snapshot:
            return {"error": "Stock not found", "symbol": symbol}

        run_id = snapshot["run_id"]
        timeline = conn.execute(queries.STOCK_TIMELINE, (symbol,)).fetchall()
        changes = conn.execute(queries.SNAPSHOT_CHANGES, (run_id, symbol)).fetchall()

        return {
            "snapshot": serialize_row(snapshot),
            "timeline": [serialize_row(r) for r in timeline],
            "changes": [serialize_row(c) for c in changes],
        }
    finally:
        conn.close()

# ---- COST CENTER ----
@router.get("/cost")
async def get_cost_summary(period: str = Query("latest")):
    """Get cost center summary."""
    conn = safe_connection()
    if not conn:
        return {"error": "Database unavailable"}

    try:
        runs = conn.execute("""
            SELECT run_id, run_date FROM runs
            WHERE is_current = true
            ORDER BY run_date DESC LIMIT 1
        """).fetchall()

        if not runs:
            return {
                "latest_run": None,
                "runs_comparison": [],
                "error": "No runs found"
            }

        run_id = runs[0]["run_id"]
        metrics = conn.execute(queries.RUN_COST_METRICS, (run_id,)).fetchone()
        stages = conn.execute(queries.COST_PER_STAGE, (run_id,)).fetchall()
        comparison = conn.execute(queries.COST_RUNS_COMPARISON).fetchall()

        return {
            "latest_run": serialize_row(runs[0]),
            "metrics": serialize_row(metrics),
            "per_stage": [serialize_row(s) for s in stages],
            "runs_comparison": [serialize_row(r) for r in comparison],
        }
    finally:
        conn.close()

@router.get("/cost/{run_id}")
async def get_cost_for_run(run_id: str):
    """Get cost metrics for a specific run."""
    conn = safe_connection()
    if not conn:
        return {"error": "Database unavailable"}

    try:
        metrics = conn.execute(queries.RUN_COST_METRICS, (run_id,)).fetchone()
        if not metrics:
            raise HTTPException(status_code=404, detail="Run not found")

        stages = conn.execute(queries.COST_PER_STAGE, (run_id,)).fetchall()

        return {
            "metrics": serialize_row(metrics),
            "per_stage": [serialize_row(s) for s in stages],
        }
    finally:
        conn.close()

# ---- REPORT DASHBOARD ----
@router.get("/report")
async def get_report():
    """Get report dashboard with trends and aggregates."""
    conn = safe_connection()
    if not conn:
        return {"error": "Database unavailable"}

    try:
        runs = conn.execute("""
            SELECT v.run_id, v.run_date, v.scanned, v.in_range, v.at_ath,
                   v.within_5, v.within_10, v.within_26
            FROM v_run_summary v
            JOIN runs r ON r.run_id = v.run_id
            WHERE r.is_current
            ORDER BY v.run_date DESC
            LIMIT 41
        """).fetchall()

        industries = []
        new_ath = []

        if runs:
            latest_run_id = runs[0]["run_id"]
            industries = conn.execute("""
                SELECT industry, COUNT(*) as count
                FROM stock_snapshots
                WHERE run_id = %s
                GROUP BY industry
                ORDER BY count DESC
                LIMIT 10
            """, (latest_run_id,)).fetchall()

            new_ath = conn.execute("""
                SELECT DISTINCT ss.symbol, r.run_date
                FROM stock_snapshots ss
                JOIN runs r ON ss.run_id = r.run_id
                WHERE ss.bucket = 'at_ath' AND r.is_current = true
                ORDER BY r.run_date DESC
                LIMIT 10
            """).fetchall()

        return {
            "runs": [serialize_row(r) for r in runs],
            "industries": [serialize_row(i) for i in industries],
            "newly_ath": [serialize_row(a) for a in new_ath],
        }
    finally:
        conn.close()

# ---- MASTER CONFIGURATION ----
@router.get("/config")
async def get_config():
    """Get master configuration for all data sources."""
    try:
        settings = collector_settings.get_settings()
        conn = safe_connection()

        result = []
        for source, setting in settings.items():
            runs = []
            if conn:
                try:
                    runs = conn.execute(
                        queries.COLLECTOR_RUNS_HISTORY,
                        (source,)
                    ).fetchall()
                except:
                    pass

            cron = setting.get("cron", "")
            try:
                cron_iter = croniter(cron, datetime.now())
                next_due = cron_iter.get_next(datetime).isoformat()
            except:
                next_due = None

            result.append({
                "source": source,
                "mode": setting.get("mode", "scheduled"),
                "cron": cron,
                "cron_human": _describe_cron(cron),
                "params": setting.get("params", {}),
                "updated_at": setting.get("updated_at").isoformat() if setting.get("updated_at") else None,
                "next_due": next_due,
                "last_runs": [serialize_row(r) for r in runs],
            })

        coverage = None
        if conn:
            try:
                coverage = conn.execute(queries.ANNOUNCEMENT_COVERAGE).fetchone()
            except:
                pass
            finally:
                conn.close()

        return {
            "sources": result,
            "coverage": serialize_row(coverage) if coverage else None,
        }
    except Exception as e:
        return {"error": str(e), "sources": []}

@router.get("/config/{source}")
async def get_config_source(source: str):
    """Get configuration for a specific source."""
    try:
        settings = collector_settings.get_settings()

        if source not in settings:
            raise HTTPException(status_code=404, detail="Source not found")

        setting = settings[source]

        conn = safe_connection()
        runs = []
        if conn:
            try:
                runs = conn.execute(
                    queries.COLLECTOR_RUNS_HISTORY,
                    (source,)
                ).fetchall()
            finally:
                conn.close()

        return {
            "source": source,
            "mode": setting.get("mode", "scheduled"),
            "cron": setting.get("cron", ""),
            "cron_human": _describe_cron(setting.get("cron", "")),
            "params": setting.get("params", {}),
            "last_runs": [serialize_row(r) for r in runs],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/config/{source}")
async def update_config(source: str, request: ConfigUpdateRequest):
    """Update configuration for a source."""
    try:
        collector_settings.update_setting(
            source,
            mode=request.mode,
            cron=request.cron,
            params=request.params
        )
        return {"success": True, "source": source}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/config/{source}/run")
async def request_manual_run(source: str):
    """Request an immediate manual run of a collector."""
    try:
        queued = collector_settings.request_run(source)
        return {
            "success": True,
            "source": source,
            "status": "queued" if queued else "already_queued"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---- HELPERS ----
def _describe_cron(cron_str: str) -> str:
    """Convert a 5-field cron to a human-readable string."""
    parts = cron_str.split()
    if len(parts) != 5:
        return "Invalid cron"

    minute, hour, day, month, dow = parts

    if minute == "*":
        min_desc = "every minute"
    elif "," in minute:
        min_desc = f"at minute {minute}"
    elif minute.startswith("*/"):
        interval = minute.split("/")[1]
        min_desc = f"every {interval} minutes"
    else:
        min_desc = f"at minute {minute}"

    if hour == "*":
        hour_desc = ""
    elif "," in hour:
        hour_desc = f"hour {hour}"
    elif hour.startswith("*/"):
        interval = hour.split("/")[1]
        hour_desc = f"every {interval} hours"
    elif "-" in hour:
        hour_desc = f"hours {hour}"
    else:
        hour_desc = f"hour {hour}"

    if dow == "*":
        dow_desc = ""
    elif dow == "1-5":
        dow_desc = "weekdays"
    else:
        dow_desc = f"day {dow}"

    desc_parts = [p for p in [min_desc, hour_desc, dow_desc] if p]
    return ", ".join(desc_parts) if desc_parts else "Invalid cron"
