-- Migration 025 created symbol_sector as the admin role, so the app role has no
-- privileges on it. The sector loader and the UI run as market_scanner_app.
-- GRANT is idempotent, so re-running this migration is safe.
GRANT SELECT, INSERT, UPDATE ON symbol_sector TO market_scanner_app;
