"""Database queries for the UI. All parameterised, read-only except configuration writes."""

from typing import Optional, Dict, Any, List

# Run summary and timelines
LATEST_RUNS = """
SELECT
  v.run_id,
  v.run_date,
  v.started_at,
  v.finished_at,
  v.status,
  v.scanned,
  v.in_range,
  v.at_ath,
  v.within_5,
  v.within_10,
  v.within_26,
  v.stance_constructive,
  v.stance_mixed,
  v.stance_cautious,
  v.entered_range_count,
  v.left_range_count,
  v.duration_seconds
FROM v_run_summary v
JOIN runs r ON r.run_id = v.run_id
WHERE r.is_current
ORDER BY v.run_date DESC
LIMIT 50
"""

RUN_BY_ID = """
SELECT
  r.run_id,
  r.run_date,
  r.started_at,
  r.finished_at,
  r.status,
  r.is_current,
  r.trigger,
  v.scanned,
  v.in_range,
  v.at_ath,
  r.skipped,
  r.git_sha,
  r.prompt_version,
  r.model,
  r.gpu_name,
  r.gpu_watts_avg,
  r.gpu_energy_wh,
  r.gpu_busy_seconds,
  r.stage_timings,
  r.notes
FROM runs r
LEFT JOIN v_run_summary v ON v.run_id = r.run_id
WHERE r.run_id = %s
"""

RUN_SUMMARY_STATS = """
SELECT
  COUNT(DISTINCT CASE WHEN bucket = 'at_ath' THEN symbol END) as at_ath,
  COUNT(DISTINCT CASE WHEN bucket = 'within_5' THEN symbol END) as within_5,
  COUNT(DISTINCT CASE WHEN bucket = 'within_10' THEN symbol END) as within_10,
  COUNT(DISTINCT CASE WHEN bucket = 'within_26' THEN symbol END) as within_26,
  COUNT(DISTINCT CASE WHEN stance = 'constructive' THEN symbol END) as constructive,
  COUNT(DISTINCT CASE WHEN stance = 'mixed' THEN symbol END) as mixed,
  COUNT(DISTINCT CASE WHEN stance = 'cautious' THEN symbol END) as cautious
FROM stock_snapshots
WHERE run_id = %s
"""

CHANGES_SINCE_PREVIOUS = """
SELECT
  kind,
  COUNT(*) as count
FROM snapshot_changes
WHERE run_id = %s
GROUP BY kind
"""

# Stock snapshots and timelines
STOCK_SNAPSHOT = """
SELECT
  ss.run_id,
  ss.symbol,
  ss.isin,
  ss.company,
  ss.industry,
  ss.ltp,
  ss.ath_high,
  ss.ath_date,
  ss.distance_pct,
  ss.bucket,
  ss.one_year_return_pct,
  ss.order_pct_of_sales,
  ss.stance,
  ss.stance_score,
  ss.conclusion_ref,
  ss.metrics,
  r.run_date
FROM stock_snapshots ss
JOIN runs r ON ss.run_id = r.run_id
WHERE ss.symbol = %s AND ss.run_id = %s
"""

STOCK_LATEST_SNAPSHOT = """
SELECT
  ss.run_id,
  ss.symbol,
  ss.isin,
  ss.company,
  ss.industry,
  ss.ltp,
  ss.ath_high,
  ss.ath_date,
  ss.distance_pct,
  ss.bucket,
  ss.one_year_return_pct,
  ss.order_pct_of_sales,
  ss.stance,
  ss.stance_score,
  ss.conclusion_ref,
  ss.metrics,
  r.run_date
FROM stock_snapshots ss
JOIN runs r ON ss.run_id = r.run_id
WHERE ss.symbol = %s AND r.is_current = true
ORDER BY r.run_date DESC
LIMIT 1
"""

STOCK_TIMELINE = """
SELECT
  ss.run_id,
  ss.symbol,
  ss.stance,
  ss.ltp,
  ss.distance_pct,
  ss.bucket,
  r.run_date,
  r.started_at
FROM stock_snapshots ss
JOIN runs r ON ss.run_id = r.run_id
WHERE ss.symbol = %s AND r.is_current = true
ORDER BY r.run_date DESC
LIMIT 100
"""

SNAPSHOT_CHANGES = """
SELECT
  kind,
  before,
  after,
  note
FROM snapshot_changes
WHERE run_id = %s AND symbol = %s
ORDER BY kind
"""

# Results table
RESULTS_QUERY = """
SELECT
  ss.symbol,
  ss.company,
  ss.industry,
  ss.ltp,
  ss.distance_pct,
  ss.ath_date,
  ss.one_year_return_pct,
  ss.order_pct_of_sales,
  ss.stance,
  ss.bucket,
  COALESCE(
    (SELECT COUNT(*) FROM snapshot_changes WHERE run_id = ss.run_id AND symbol = ss.symbol) > 0,
    false
  ) as changed
FROM stock_snapshots ss
WHERE ss.run_id = %s
ORDER BY {order_by}
LIMIT %s OFFSET %s
"""

RESULTS_COUNT = """
SELECT COUNT(*) as total
FROM stock_snapshots
WHERE run_id = %s
"""

# Cost center (measured metrics only)
RUN_COST_METRICS = """
SELECT
  run_id,
  run_date,
  total_calls AS llm_calls,
  ok_calls,
  total_calls - COALESCE(ok_calls, 0) AS failed_calls,
  total_input_tokens,
  total_output_tokens,
  avg_input_tokens_per_call + avg_output_tokens_per_call AS avg_tokens_per_call,
  total_llm_seconds AS total_seconds,
  tokens_per_second,
  gpu_name,
  gpu_energy_wh,
  gpu_watts_avg,
  gpu_busy_seconds
FROM v_run_metrics
WHERE run_id = %s
"""

COST_RUNS_COMPARISON = """
SELECT
  m.run_id,
  m.run_date,
  m.total_calls AS llm_calls,
  m.total_input_tokens,
  m.total_output_tokens,
  m.total_llm_seconds AS total_seconds,
  m.tokens_per_second,
  m.gpu_energy_wh,
  m.gpu_watts_avg,
  m.gpu_busy_seconds
FROM v_run_metrics m
JOIN runs r ON r.run_id = m.run_id
WHERE r.is_current
ORDER BY m.run_date DESC
LIMIT 30
"""

COST_PER_STAGE = """
SELECT
  lc.stage,
  COUNT(*) as call_count,
  SUM(CASE WHEN lc.ok = true THEN 1 ELSE 0 END) as ok_count,
  SUM(lc.input_tokens) as input_tokens,
  SUM(lc.output_tokens) as output_tokens,
  SUM(lc.seconds) as total_seconds
FROM llm_calls lc
WHERE lc.run_id = %s
GROUP BY lc.stage
"""

# Configuration
COLLECTOR_SETTINGS = """
SELECT
  source,
  mode,
  cron,
  params,
  updated_at
FROM collector_settings
ORDER BY source
"""

COLLECTOR_SETTING_BY_SOURCE = """
SELECT
  source,
  mode,
  cron,
  params,
  updated_at
FROM collector_settings
WHERE source = %s
"""

COLLECTOR_RUNS_HISTORY = """
SELECT
  id,
  source,
  trigger,
  started_at,
  finished_at,
  status,
  from_date,
  to_date,
  rows_fetched,
  rows_new,
  message
FROM collector_runs
WHERE source = %s
ORDER BY started_at DESC
LIMIT 10
"""

# Configuration updates
UPDATE_COLLECTOR_SETTING = """
UPDATE collector_settings
SET mode = %s, cron = %s, params = %s, updated_at = now()
WHERE source = %s
"""

INSERT_COLLECTOR_REQUEST = """
INSERT INTO collector_requests (id, source, requested_at)
VALUES (%s, %s, now())
ON CONFLICT (source) WHERE claimed_at IS NULL DO NOTHING
"""

# Announcement coverage
ANNOUNCEMENT_COVERAGE = """
SELECT
  COUNT(*) as total_stocks,
  COUNT(CASE WHEN ok = true THEN 1 END) as stocks_ok,
  COUNT(CASE WHEN ok = false THEN 1 END) as stocks_with_gaps,
  MIN(first_date) as earliest_date,
  MAX(last_date) as latest_date
FROM (
  SELECT DISTINCT
    symbol,
    COALESCE(
      (first_date IS NOT NULL AND last_date IS NOT NULL),
      false
    ) as ok,
    first_date,
    last_date
  FROM symbol_listing sl
  LEFT JOIN (
    SELECT symbol, MIN(an_dt) as first_date, MAX(an_dt) as last_date
    FROM announcements
    GROUP BY symbol
  ) ann ON sl.symbol = ann.symbol
) coverage
"""
