-- Sector classification per listed company.
-- nse_industry comes from the NSE Total Market constituents CSV (Industry column, 22 groups).
-- nse_basic_industry stays NULL until the NSE per-company quote field is confirmed.
-- sub_sector is the user's own mapping. It is never overwritten by a loader.
-- A loader may refresh nse_industry and as_of, and must not touch sub_sector columns.

CREATE TABLE symbol_sector (
  symbol             text PRIMARY KEY,
  isin               text,
  nse_industry       text,
  nse_basic_industry text,
  sub_sector         text,
  sub_sector_source  text,            -- 'manual' or a source name; NULL when unmapped
  as_of              date NOT NULL,   -- date of the exchange file the nse_* values came from
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX symbol_sector_isin_idx ON symbol_sector (isin);
CREATE INDEX symbol_sector_nse_industry_idx ON symbol_sector (nse_industry);
CREATE INDEX symbol_sector_sub_sector_idx ON symbol_sector (sub_sector);
