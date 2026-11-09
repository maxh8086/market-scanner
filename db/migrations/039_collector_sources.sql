-- The list of valid collector sources, stored in the database. collector_settings may only
-- hold a source that is listed here, so a raw SQL insert with an unknown name is refused.
-- scanner/collect/settings.py ensure_sources() adds a row here for every key in sources.py
-- before it adds the matching collector_settings row.

CREATE TABLE collector_sources (
  source     text PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Existing settings rows (verified before this migration: all six match sources.py).
INSERT INTO collector_sources (source)
SELECT source FROM collector_settings
ON CONFLICT (source) DO NOTHING;

ALTER TABLE collector_settings
  ADD CONSTRAINT collector_settings_source_fkey
  FOREIGN KEY (source) REFERENCES collector_sources (source);

-- The app role reads the list and inserts new names (ensure_sources). No DELETE, same as 026.
GRANT SELECT, INSERT ON collector_sources TO market_scanner_app;
