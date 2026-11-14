-- ATH scan candidates (collector split S2a): one row per candidate per scan date. These are the rows
-- ath_scan used to write to output/ath_scan_<date>.csv. Column names and order are the CSV columns of
-- scanner/report.py (BASE_COLUMNS, TREND_COLUMNS, FACTOR_COLUMNS). tests/test_migration_060_ath_scan_candidates.py
-- checks this list against those constants, so schema and CSV cannot drift.
-- Text columns hold the CSV text: '' (never NULL) for an empty cell, so symbol NA and the label
-- INSUFFICIENT_HISTORY survive a round trip. ath_date and the boolean-like columns are text, not parsed.
-- run_id is NULL for a scan run made outside the collector.
-- Retention: 90 days, pruned by the writer (scanner/ath_scan_store.py, write_scan).
-- No grants here: the collector and the host scripts connect as the owner role.
-- Down-step: db/migrations/down/060_ath_scan_candidates.down.sql (manual, not applied by the runner).

CREATE TABLE IF NOT EXISTS ath_scan_candidates (
  scan_date        date NOT NULL,
  symbol           text NOT NULL,
  run_id           uuid REFERENCES collector_runs(id) ON DELETE SET NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  company          text NOT NULL DEFAULT '',
  isin             text NOT NULL DEFAULT '',
  industry         text NOT NULL DEFAULT '',
  ltp              double precision,
  today_high       double precision,
  ath_high         double precision,
  ath_date         text NOT NULL DEFAULT '',
  ath_close        double precision,
  distance_pct     double precision,
  bucket           text NOT NULL DEFAULT '',
  days_since_ath   integer,
  listed_days      integer,
  recent_ipo       text NOT NULL DEFAULT '',
  ema50            double precision,
  sma200           double precision,
  above_ema50      text NOT NULL DEFAULT '',
  above_sma200     text NOT NULL DEFAULT '',
  trend            text NOT NULL DEFAULT '',
  bonus_issue      text NOT NULL DEFAULT '',
  demerger         text NOT NULL DEFAULT '',
  orderbook_signal text NOT NULL DEFAULT '',
  expansion_signal text NOT NULL DEFAULT '',
  factors_matched  integer,
  PRIMARY KEY (scan_date, symbol)
);
