-- ISIN history and symbol renames, so a stale constituents CSV can be corrected automatically.
-- Written by scanner/isin_resolver.py from Upstox's public NSE instrument master.

-- Every (symbol, ISIN) pair seen for a symbol, with the first and last date it was resolved.
CREATE TABLE IF NOT EXISTS isin_history (
  symbol text NOT NULL,
  isin text NOT NULL,
  first_seen date NOT NULL,
  last_seen date NOT NULL,
  source text NOT NULL,
  PRIMARY KEY (symbol, isin)
);

-- A symbol rename detected through an unchanged ISIN (old_symbol -> new_symbol).
CREATE TABLE IF NOT EXISTS symbol_alias (
  old_symbol text NOT NULL,
  new_symbol text NOT NULL,
  isin text NOT NULL,
  seen_at date NOT NULL,
  PRIMARY KEY (old_symbol, new_symbol, isin)
);
