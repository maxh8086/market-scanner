-- Market data tables: candles, NSE announcements, corporate actions.
-- Migrated from SQLite (data/history.db and data/factors.db) for query joins and incremental fetching.

-- Daily OHLCV candles per symbol, never updated (new dates only).
CREATE TABLE IF NOT EXISTS candles (
  symbol text NOT NULL,
  date date NOT NULL,
  open numeric,
  high numeric,
  low numeric,
  close numeric,
  volume bigint,
  PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS candles_symbol_date_idx ON candles (symbol, date DESC);

-- Running ATH and listing stats per symbol.
CREATE TABLE IF NOT EXISTS symbol_stats (
  symbol text PRIMARY KEY,
  ath_high numeric,
  ath_date date,
  ath_close numeric,
  ath_close_date date,
  first_date date,
  last_date date,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- NSE announcements: board approvals, bonuses, order wins, regulatory filings.
-- Keyed on (isin, an_dt, desc) so a duplicate announcement with the same date
-- and category is idempotent. seq_id is NSE's own identifier, used as the
-- document store key for fetching the PDF.
CREATE TABLE IF NOT EXISTS announcements (
  isin text NOT NULL,
  symbol text NOT NULL,
  an_dt date NOT NULL,
  "desc" text,
  attchmnt_text text,
  sort_date date,
  seq_id text,
  attchmnt_file text,
  att_file_size integer,
  PRIMARY KEY (isin, an_dt, "desc")
);
CREATE INDEX IF NOT EXISTS announcements_symbol_date_idx ON announcements (symbol, an_dt DESC);
CREATE INDEX IF NOT EXISTS announcements_seq_id_idx ON announcements (seq_id) WHERE seq_id IS NOT NULL;

-- NSE corporate actions: bonuses, splits, dividends, demergers.
CREATE TABLE IF NOT EXISTS corporate_actions (
  isin text NOT NULL,
  symbol text NOT NULL,
  subject text NOT NULL,
  ex_date date,
  received_date date,
  PRIMARY KEY (isin, ex_date, subject)
);
CREATE INDEX IF NOT EXISTS corporate_actions_symbol_date_idx ON corporate_actions (symbol, ex_date DESC);

-- Coverage of each data feed: which windows have been fetched from NSE.
-- Merge overlapping/adjacent windows so gaps are computable and non-overlapping
-- ranges tell a story of what was fetched when. Normalise to the day boundary.
CREATE TABLE IF NOT EXISTS feed_coverage (
  feed text NOT NULL,
  from_date date NOT NULL,
  to_date date NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (feed, from_date, to_date)
);
CREATE INDEX IF NOT EXISTS feed_coverage_feed_date_idx ON feed_coverage (feed, from_date, to_date);

-- Symbol listing metadata. Listing date is the earliest trading date (from the
-- first stored candle) or from an NSE master file if we fetch it. Never a guess.
CREATE TABLE IF NOT EXISTS symbol_listing (
  symbol text PRIMARY KEY,
  isin text,
  listing_date date,
  source text NOT NULL DEFAULT 'inferred'  -- 'inferred' (from candles), 'nse_master', etc.
);

-- View: announcements grouped by symbol, isin and category (desc), with counts and date ranges.
CREATE OR REPLACE VIEW v_announcement_summary AS
SELECT
  symbol,
  isin,
  "desc" AS category,
  COUNT(*) AS n,
  MIN(an_dt) AS first_date,
  MAX(an_dt) AS last_date
FROM announcements
GROUP BY symbol, isin, "desc";
