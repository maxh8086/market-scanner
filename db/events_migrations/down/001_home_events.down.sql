-- NOT run by the runner. Take a pg_dump first.
DROP TABLE IF EXISTS home_events;
DELETE FROM schema_migrations WHERE filename = '001_home_events.sql';
