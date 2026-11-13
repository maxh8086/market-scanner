-- Reference rows for company names, symbols and ISINs from two stored sources:
--   nse_csv        : NSE Nifty Total Market constituents list
--   upstox_master  : Upstox NSE_EQ/EQ instrument master
-- Filled by the monthly refresh (collector job). Runs read only this table, never the
-- source files or the source URLs. See concepts_brief.md, "Reference tables in the DB".
--
-- name_key is computed by the Python normaliser (one function, one source of truth).
-- SQL never re-implements it.

CREATE TABLE company_reference (
  source        text NOT NULL CHECK (source IN ('nse_csv', 'upstox_master')),
  symbol        text NOT NULL,            -- upper(btrim(...))
  isin          text NOT NULL,            -- upper(btrim(...))
  company_name  text NOT NULL,            -- as published by the source
  name_key      text NOT NULL,            -- normalised by the Python normaliser
  series        text,
  as_of         date NOT NULL,            -- date of the source file or master snapshot
  loaded_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source, symbol, isin)
);

CREATE INDEX company_reference_isin_idx        ON company_reference (isin);
CREATE INDEX company_reference_symbol_idx      ON company_reference (symbol);
CREATE INDEX company_reference_name_key_idx    ON company_reference (name_key);
CREATE INDEX company_reference_symbol_isin_idx ON company_reference (symbol, isin);
CREATE INDEX company_reference_isin_name_idx   ON company_reference (isin, name_key);
CREATE INDEX company_reference_name_symbol_idx ON company_reference (name_key, symbol);

-- Joins the two sources on ISIN. A disagreement in symbol or name is visible here.
CREATE VIEW company_reference_by_isin AS
SELECT coalesce(c.isin, m.isin) AS isin,
       c.symbol         AS csv_symbol,
       c.company_name   AS csv_name,
       c.name_key       AS csv_name_key,
       m.symbol         AS master_symbol,
       m.company_name   AS master_name,
       m.name_key       AS master_name_key,
       (c.symbol = m.symbol)     AS symbol_agrees,
       (c.name_key = m.name_key) AS name_agrees
FROM (SELECT * FROM company_reference WHERE source = 'nse_csv') c
FULL JOIN (SELECT * FROM company_reference WHERE source = 'upstox_master') m
       ON c.isin = m.isin;

-- The app reads only. Write access goes to the separate loader role (decision O2),
-- which is created outside this migration because it needs an admin step.
GRANT SELECT ON company_reference TO market_scanner_app;
GRANT SELECT ON company_reference_by_isin TO market_scanner_app;
