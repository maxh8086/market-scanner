-- Manual reversal for 045_app_secret.sql. NOT run by the migration runner.
-- Destroys every stored app secret. Take a pg_dump backup first (docs/progress/rollback.md, rule 3).
-- Run inside the Postgres container as the database owner:
--   DROP TABLE IF EXISTS app_secret;
-- Then remove the row from schema_migrations so the runner does not treat the file as applied:
--   DELETE FROM schema_migrations WHERE filename = '045_app_secret.sql';
DROP TABLE IF EXISTS app_secret;
DELETE FROM schema_migrations WHERE filename = '045_app_secret.sql';
