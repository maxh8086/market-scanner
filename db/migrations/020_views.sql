-- Views for run history, stock timeline, and metrics. Read-only.

-- Run summary: per-run counts and status
CREATE OR REPLACE VIEW v_run_summary AS
SELECT
  r.run_id,
  r.run_date,
  r.status,
  SUM(CASE WHEN s.bucket != 'left_range' THEN 1 ELSE 0 END) as scanned,
  SUM(CASE WHEN s.bucket IN ('at_ath', 'within_5', 'within_10', 'within_26')
      THEN 1 ELSE 0 END) as in_range,
  SUM(CASE WHEN s.bucket = 'at_ath' THEN 1 ELSE 0 END) as at_ath,
  SUM(CASE WHEN s.bucket = 'within_5' THEN 1 ELSE 0 END) as within_5,
  SUM(CASE WHEN s.bucket = 'within_10' THEN 1 ELSE 0 END) as within_10,
  SUM(CASE WHEN s.bucket = 'within_26' THEN 1 ELSE 0 END) as within_26,
  SUM(CASE WHEN s.stance = 'constructive' THEN 1 ELSE 0 END) as stance_constructive,
  SUM(CASE WHEN s.stance = 'mixed' THEN 1 ELSE 0 END) as stance_mixed,
  SUM(CASE WHEN s.stance = 'cautious' THEN 1 ELSE 0 END) as stance_cautious,
  SUM(CASE WHEN s.stance IS NULL THEN 1 ELSE 0 END) as stance_null,
  -- Change counts
  (SELECT COUNT(*) FROM snapshot_changes WHERE run_id = r.run_id AND kind = 'entered_range') as entered_range_count,
  (SELECT COUNT(*) FROM snapshot_changes WHERE run_id = r.run_id AND kind = 'left_range') as left_range_count,
  (SELECT COUNT(*) FROM snapshot_changes WHERE run_id = r.run_id AND kind = 'bucket_change') as bucket_change_count,
  (SELECT COUNT(*) FROM snapshot_changes WHERE run_id = r.run_id AND kind = 'stance_change') as stance_change_count,
  (SELECT COUNT(*) FROM snapshot_changes WHERE run_id = r.run_id AND kind = 'new_order_book') as new_order_book_count,
  (SELECT COUNT(*) FROM snapshot_changes WHERE run_id = r.run_id AND kind = 'capacity_change') as capacity_change_count,
  (SELECT COUNT(*) FROM snapshot_changes WHERE run_id = r.run_id AND kind = 'new_filing') as new_filing_count,
  EXTRACT(EPOCH FROM (r.finished_at - r.started_at)) as duration_seconds,
  r.started_at,
  r.finished_at
FROM runs r
LEFT JOIN stock_snapshots s ON r.run_id = s.run_id
WHERE r.status IN ('complete', 'partial')
GROUP BY r.run_id, r.run_date, r.status, r.started_at, r.finished_at
ORDER BY r.run_date DESC;

-- Stock timeline: snapshots with their changes, newest first
CREATE OR REPLACE VIEW v_stock_timeline AS
WITH snapshots_with_lag AS (
  SELECT
    s.run_id,
    s.symbol,
    s.isin,
    s.company,
    s.industry,
    s.ltp,
    s.ath_high,
    s.ath_date,
    s.distance_pct,
    s.bucket,
    s.stance,
    s.stance_score,
    s.one_year_return_pct,
    s.order_pct_of_sales,
    s.metrics,
    r.run_date,
    r.status,
    r.started_at,
    r.finished_at,
    -- Previous snapshot values via window function
    LAG(s.distance_pct) OVER (PARTITION BY s.symbol ORDER BY r.run_date DESC) as prev_distance_pct,
    LAG(s.stance) OVER (PARTITION BY s.symbol ORDER BY r.run_date DESC) as prev_stance,
    LAG(s.bucket) OVER (PARTITION BY s.symbol ORDER BY r.run_date DESC) as prev_bucket
  FROM stock_snapshots s
  JOIN runs r ON s.run_id = r.run_id
  WHERE r.status IN ('complete', 'partial')
)
SELECT
  snl.run_id,
  snl.symbol,
  snl.isin,
  snl.company,
  snl.industry,
  snl.ltp,
  snl.ath_high,
  snl.ath_date,
  snl.distance_pct,
  snl.prev_distance_pct,
  snl.bucket,
  snl.prev_bucket,
  snl.stance,
  snl.prev_stance,
  snl.stance_score,
  snl.one_year_return_pct,
  snl.order_pct_of_sales,
  snl.run_date,
  snl.status,
  snl.started_at,
  snl.finished_at,
  -- Join changes for this snapshot
  sc.kind,
  sc.before,
  sc.after,
  sc.note
FROM snapshots_with_lag snl
LEFT JOIN snapshot_changes sc ON snl.run_id = sc.run_id AND snl.symbol = sc.symbol
ORDER BY snl.symbol, snl.run_date DESC;

-- LLM metrics per run
CREATE OR REPLACE VIEW v_run_metrics AS
SELECT
  r.run_id,
  r.run_date,
  r.status,
  -- LLM call counts
  COUNT(lc.call_id) as total_calls,
  SUM(CASE WHEN lc.ok THEN 1 ELSE 0 END) as ok_calls,
  NULLIF(SUM(lc.input_tokens), 0) as total_input_tokens,
  NULLIF(SUM(lc.output_tokens), 0) as total_output_tokens,
  -- Calculated metrics
  CASE WHEN COUNT(lc.call_id) > 0
       THEN SUM(lc.input_tokens) / COUNT(lc.call_id)
       ELSE NULL
  END as avg_input_tokens_per_call,
  CASE WHEN COUNT(lc.call_id) > 0
       THEN SUM(lc.output_tokens) / COUNT(lc.call_id)
       ELSE NULL
  END as avg_output_tokens_per_call,
  NULLIF(SUM(CASE WHEN lc.stage = 'extract' THEN lc.seconds ELSE 0 END), 0) as extract_seconds,
  NULLIF(SUM(CASE WHEN lc.stage = 'conclude' THEN lc.seconds ELSE 0 END), 0) as conclude_seconds,
  NULLIF(SUM(lc.seconds), 0) as total_llm_seconds,
  CASE WHEN SUM(lc.seconds) > 0
       THEN (SUM(lc.input_tokens) + SUM(lc.output_tokens)) / SUM(lc.seconds)
       ELSE NULL
  END as tokens_per_second,
  -- GPU metrics from runs table
  r.gpu_name,
  r.gpu_watts_avg,
  r.gpu_energy_wh,
  r.gpu_busy_seconds,
  r.stage_timings,
  r.started_at,
  r.finished_at,
  EXTRACT(EPOCH FROM (r.finished_at - r.started_at)) as duration_seconds
FROM runs r
LEFT JOIN llm_calls lc ON r.run_id = lc.run_id
WHERE r.status IN ('complete', 'partial')
GROUP BY r.run_id, r.run_date, r.status, r.gpu_name, r.gpu_watts_avg,
         r.gpu_energy_wh, r.gpu_busy_seconds, r.stage_timings,
         r.started_at, r.finished_at
ORDER BY r.run_date DESC;
