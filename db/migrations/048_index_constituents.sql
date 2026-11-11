-- index_constituents: constituent lists of named indexes (for example "NIFTY TOTAL MARKET").
-- Filled by the monthly job (scanner/company_reference_job.py); scans read one index at a time
-- by name. The run path never downloads these lists.
--
-- Primary key is (index_name, symbol, isin): one index can hold the same symbol only once.

-- IF NOT EXISTS: the table was created in market_scanner before the runner recorded this file
-- (no schema_migrations row). Re-running it must be a no-op, not an error that stops the run.
CREATE TABLE IF NOT EXISTS index_constituents (
  index_name    text NOT NULL,
  symbol        text NOT NULL,
  isin          text NOT NULL,
  company_name  text NOT NULL,
  industry      text,
  series        text,
  as_of         date NOT NULL,
  loaded_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (index_name, symbol, isin)
);

CREATE INDEX IF NOT EXISTS index_constituents_symbol_idx ON index_constituents (symbol);

-- The app reads; the loader role fills the table (same split as migration 047).
GRANT SELECT ON index_constituents TO market_scanner_app;
GRANT SELECT, INSERT, DELETE ON index_constituents TO market_scanner_loader;
