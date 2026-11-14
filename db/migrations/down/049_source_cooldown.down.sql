-- Manual reversal of 049_source_cooldown.sql. NOT run by the migration runner (the runner globs db/migrations non-recursively, so down/ is never picked up). Take a pg_dump first.
-- If 050 (S5a) is already applied, reverse 050 first, since it grants on this table.
--   DROP TABLE IF EXISTS source_cooldown;
--   DELETE FROM schema_migrations WHERE filename = '049_source_cooldown.sql';
DROP TABLE IF EXISTS source_cooldown;
DELETE FROM schema_migrations WHERE filename = '049_source_cooldown.sql';
