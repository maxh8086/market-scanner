-- 12-month relative strength of each stock against its comparison index, one row per
-- (symbol, as_of). Written by scanner/relative_strength.py. Missing returns are NULL.

CREATE TABLE IF NOT EXISTS relative_strength (
  symbol text NOT NULL,
  as_of date NOT NULL,
  stock_return_12m numeric,
  index_name text NOT NULL,
  index_return_12m numeric,
  rs_gap_pct numeric,
  tier text NOT NULL,
  PRIMARY KEY (symbol, as_of)
);
