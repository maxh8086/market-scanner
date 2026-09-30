-- Core tables shared by every component. Owned by the lead; later files add to it, never edit it.
-- Duplicate-proofing is in the keys: re-running any writer cannot create a second copy.

-- One row per pipeline execution (scan -> enrich -> conclude -> record).
CREATE TABLE runs (
  run_id          uuid PRIMARY KEY,
  run_date        date        NOT NULL,                 -- trading date the prices are for
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  status          text        NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running','complete','failed','partial')),
  is_current      boolean     NOT NULL DEFAULT false,   -- the run the UI shows for that date
  trigger         text        NOT NULL DEFAULT 'manual' CHECK (trigger IN ('manual','schedule','backfill')),
  scanned         int, in_range int, at_ath int, skipped int,
  git_sha         text, prompt_version text, model text,
  -- measured resource use, for the Cost center. NULL means "not measured", never zero.
  gpu_name        text,
  gpu_watts_avg   numeric,
  gpu_energy_wh   numeric,
  gpu_busy_seconds numeric,
  stage_timings   jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"scan": 412.0, "extract": 1930.5, ...} seconds
  notes           text
);
-- A re-run for the same date replaces the earlier one only once it completes.
CREATE UNIQUE INDEX runs_one_current_per_date ON runs (run_date) WHERE is_current;
CREATE INDEX runs_date_idx ON runs (run_date DESC);

-- One row per stock per run. A stock's timeline is this table ordered by run_date.
CREATE TABLE stock_snapshots (
  run_id         uuid    NOT NULL REFERENCES runs ON DELETE CASCADE,
  symbol         text    NOT NULL,
  isin           text,
  company        text,
  industry       text,
  ltp            numeric,
  ath_high       numeric,
  ath_date       date,
  distance_pct   numeric NOT NULL,
  bucket         text    NOT NULL CHECK (bucket IN ('at_ath','within_5','within_10','within_26')),
  one_year_return_pct numeric,
  order_pct_of_sales  numeric,
  stance         text CHECK (stance IN ('constructive','mixed','cautious')),
  stance_score   numeric,
  conclusion_ref text,                                  -- Mongo conclusions _id used for this snapshot
  metrics        jsonb   NOT NULL,                      -- the full enriched row, every column
  PRIMARY KEY (run_id, symbol)                          -- a stock cannot appear twice in a run
);
CREATE INDEX snapshots_symbol_idx ON stock_snapshots (symbol, run_id);

-- What changed for a stock versus its previous snapshot. Written once, never edited.
CREATE TABLE snapshot_changes (
  run_id  uuid NOT NULL,
  symbol  text NOT NULL,
  kind    text NOT NULL,   -- entered_range, left_range, bucket_change, stance_change,
                           -- new_order_book, capacity_change, new_filing
  before  jsonb,
  after   jsonb,
  note    text,
  PRIMARY KEY (run_id, symbol, kind),
  FOREIGN KEY (run_id, symbol) REFERENCES stock_snapshots ON DELETE CASCADE
);

-- Every model call: the raw metrics the Cost center reports. No prices are stored anywhere.
CREATE TABLE llm_calls (
  call_id       uuid PRIMARY KEY,
  run_id        uuid NOT NULL REFERENCES runs ON DELETE CASCADE,
  symbol        text,
  stage         text NOT NULL CHECK (stage IN ('extract','conclude')),
  source_key    text NOT NULL,                          -- filing seq_id, or conclusion packet_hash
  model         text NOT NULL,
  input_tokens  int  NOT NULL,
  output_tokens int  NOT NULL,
  seconds       numeric NOT NULL,
  ok            boolean NOT NULL,
  called_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, stage, source_key)                    -- a retried call is counted once
);
CREATE INDEX llm_calls_run_idx ON llm_calls (run_id, stage);

-- Master configuration: one row per data source the collectors keep fresh.
CREATE TABLE collector_settings (
  source        text PRIMARY KEY
                CHECK (source IN ('candles_eod','announcements','corporate_actions','filings','fundamentals')),
  mode          text NOT NULL DEFAULT 'scheduled' CHECK (mode IN ('scheduled','manual')),
  cron          text NOT NULL,                          -- 5-field cron, evaluated in Asia/Kolkata
  params        jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at    timestamptz NOT NULL DEFAULT now()
);
-- Defaults. 'scheduled' still allows a manual "Run now" at any time; 'manual' never runs on its own.
INSERT INTO collector_settings (source, mode, cron, params) VALUES
  ('candles_eod',       'scheduled', '35 18 * * 1-5',       '{"note":"end of day only, after the close"}'),
  ('announcements',     'scheduled', '*/30 8-20 * * 1-5',   '{"min_history_years":3}'),
  ('corporate_actions', 'scheduled', '0 */6 * * *',         '{}'),
  ('filings',           'scheduled', '10,40 8-20 * * 1-5',  '{"only_new":true}'),
  ('fundamentals',      'scheduled', '0 7 * * *',           '{"refetch_only_on_new_result":true}');

-- Every collection attempt, scheduled or manual.
CREATE TABLE collector_runs (
  id            uuid PRIMARY KEY,
  source        text NOT NULL REFERENCES collector_settings,
  trigger       text NOT NULL CHECK (trigger IN ('schedule','manual')),
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  status        text NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','failed','skipped')),
  from_date     date, to_date date,                     -- the window actually requested (gaps only)
  rows_fetched  int NOT NULL DEFAULT 0,
  rows_new      int NOT NULL DEFAULT 0,                 -- new after de-duplication
  message       text
);
CREATE INDEX collector_runs_src_idx ON collector_runs (source, started_at DESC);

-- "Run now" clicks. The UI inserts, the collector service claims and executes.
CREATE TABLE collector_requests (
  id            uuid PRIMARY KEY,
  source        text NOT NULL REFERENCES collector_settings,
  requested_at  timestamptz NOT NULL DEFAULT now(),
  claimed_at    timestamptz,
  collector_run uuid REFERENCES collector_runs
);
-- At most one unclaimed request per source: double-clicking cannot queue two.
CREATE UNIQUE INDEX collector_requests_one_open ON collector_requests (source) WHERE claimed_at IS NULL;
