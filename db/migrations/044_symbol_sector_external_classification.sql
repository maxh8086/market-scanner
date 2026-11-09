-- Classification from two external sources, stored next to the NSE columns.
-- Each loader writes only its own columns, so re-running one source cannot overwrite the other.
--
-- upstox_sector: Upstox fundamentals profile, data.sector (GET /v2/fundamentals/{isin}/profile).
--   Upstox's own labels, for example 'Bank', 'Refineries', 'IT - Software'.
-- screener_*: Screener company-page breadcrumb, one path per company, four levels.
--   Level 1 has eight top sectors (for example 'Financial Services'); level 4 is the most specific.

ALTER TABLE symbol_sector
  ADD COLUMN upstox_sector          text,
  ADD COLUMN upstox_sector_as_of    date,
  ADD COLUMN screener_sector        text,
  ADD COLUMN screener_industry      text,
  ADD COLUMN screener_basic_industry text,
  ADD COLUMN screener_sub_industry  text,
  ADD COLUMN screener_as_of         date;

CREATE INDEX symbol_sector_upstox_sector_idx ON symbol_sector (upstox_sector);
CREATE INDEX symbol_sector_screener_sector_idx ON symbol_sector (screener_sector);
