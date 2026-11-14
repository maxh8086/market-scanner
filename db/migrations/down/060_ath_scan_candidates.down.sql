-- Manual reversal of 060_ath_scan_candidates.sql. NOT run by the migration runner (the runner globs db/migrations non-recursively, so down/ is never picked up). Take a pg_dump first.
-- Drops the candidate rows of every scan date; the collector's ath_scan source cannot read candidates until 060 is re-applied.
--   DROP TABLE IF EXISTS ath_scan_candidates;
--   DELETE FROM schema_migrations WHERE filename = '060_ath_scan_candidates.sql';
DROP TABLE IF EXISTS ath_scan_candidates;
DELETE FROM schema_migrations WHERE filename = '060_ath_scan_candidates.sql';
