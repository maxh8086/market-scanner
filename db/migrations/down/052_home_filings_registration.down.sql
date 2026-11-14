-- Undo 052. Manual, not run by the migration runner (the runner globs db/migrations non-recursively, so down/ is never picked up). Take a pg_dump first.
-- collector_requests and collector_runs rows for home_filings reference collector_sources through foreign keys,
-- so they are removed first, then collector_settings, then collector_sources.

DELETE FROM collector_requests WHERE source = 'home_filings';
DELETE FROM collector_runs WHERE source = 'home_filings';
DELETE FROM collector_settings WHERE source = 'home_filings';
DELETE FROM collector_sources WHERE source = 'home_filings';
