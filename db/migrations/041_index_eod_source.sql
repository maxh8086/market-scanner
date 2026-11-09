-- Adds the index_eod collector source (scanner/collect/sources.py IndexEOD).
--
-- The original CHECK on collector_settings.source (001_core.sql) only allows the five
-- names that existed then. Migration 039 made collector_sources the list of valid names
-- through a foreign key, so the CHECK is no longer needed and is dropped here.

ALTER TABLE collector_settings DROP CONSTRAINT IF EXISTS collector_settings_source_check;

-- The foreign key from 039 requires the name in collector_sources before settings can use it.
INSERT INTO collector_sources (source) VALUES ('index_eod')
ON CONFLICT (source) DO NOTHING;

-- Scheduled 15:45 IST close run and an 08:45 retry before the 09:00 open, weekdays only.
-- The cron is evaluated in Asia/Kolkata. ON CONFLICT keeps any setting already changed in the UI.
INSERT INTO collector_settings (source, mode, cron, params) VALUES
  ('index_eod', 'scheduled', '45 8,15 * * 1-5', '{"note":"index closes; retries 08:45 before the open"}')
ON CONFLICT (source) DO NOTHING;
