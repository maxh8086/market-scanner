-- NSE index constituent membership, one row per (index, ISIN, snapshot date).
-- Loaded from data/constituents/*.csv by scripts/fetch_index_constituents.py.

CREATE TABLE constituent_membership (
  index_name text NOT NULL,
  isin       text NOT NULL,
  symbol     text,
  as_of      date NOT NULL,
  PRIMARY KEY (index_name, isin, as_of)
);
