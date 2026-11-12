-- Daily close, TTM EPS and P/E per company per day, from fund_derive.daily_valuation.
-- fund_line cannot hold this series: its section CHECK excludes daily data.
-- Design: docs/designs/fundamentals-tables.md.

-- One row per (company, day, source). ttm_eps and pe stay NULL until the inputs exist.
CREATE TABLE fund_daily (
  symbol      text NOT NULL,
  day         date NOT NULL,
  close       numeric,                 -- NULL allowed when the close is not known
  ttm_eps     numeric,                 -- NULL until four quarters are published
  pe          numeric,                 -- NULL when ttm_eps is missing or not positive, never 0
  source      text NOT NULL DEFAULT 'screener' CHECK (source IN ('screener', 'nse')),
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, day, source)
);
CREATE INDEX fund_daily_day_idx ON fund_daily (day);

-- Same grant pattern as 026 and 027: the app role reads and writes, with no row removal.
GRANT SELECT, INSERT, UPDATE ON fund_daily TO market_scanner_app;
