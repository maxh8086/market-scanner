-- Manual reversal for 046_token_expiry_alert.sql. NOT run by the migration runner.
-- Removes the record of sent alerts, so alerts due again would be sent again. Take a pg_dump first.
--   DROP TABLE IF EXISTS token_alert_sent;
--   DELETE FROM schema_migrations WHERE filename = '046_token_expiry_alert.sql';
DROP TABLE IF EXISTS token_alert_sent;
DELETE FROM schema_migrations WHERE filename = '046_token_expiry_alert.sql';
