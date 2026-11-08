-- The list of valid collector sources lives in code (scanner/collect/sources.py SOURCES), not in
-- the database. Drop the hard-coded CHECK so a new source needs no migration: the collector
-- registers each SOURCES key in collector_settings at startup (scanner/collect/settings.py
-- ensure_sources). Foreign keys from collector_runs and collector_requests stay in place.

ALTER TABLE collector_settings DROP CONSTRAINT IF EXISTS collector_settings_source_check;
