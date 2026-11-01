-- Fetch bookkeeping and the Upstox 5-year pull log, moved off SQLite (data/factors.db).

-- One row per feed: the last date window fetched and when. Read by the factor
-- cache to decide whether a feed was already fetched today for the same window.
CREATE TABLE IF NOT EXISTS fetch_metadata (
  feed_name text PRIMARY KEY,
  from_date date,
  to_date date,
  fetched_at timestamptz
);

-- One row per symbol per Upstox pull attempt: how many rows came back, the date
-- span, the outcome and the error text when it failed.
CREATE TABLE IF NOT EXISTS upstox_pull_log (
  id bigserial PRIMARY KEY,
  symbol text NOT NULL,
  rows integer,
  first_date date,
  last_date date,
  status text NOT NULL,
  pulled_at timestamptz NOT NULL,
  error text
);
CREATE INDEX IF NOT EXISTS upstox_pull_log_symbol_idx ON upstox_pull_log (symbol);
