-- Migration 021 created constituent_membership as the admin role, so the app role
-- had no privileges on it. The constituent loader and relative-strength step run
-- as market_scanner_app and fail with InsufficientPrivilege without these grants.
-- GRANT is idempotent, so re-running this migration is safe.
GRANT SELECT, INSERT, UPDATE ON constituent_membership TO market_scanner_app;
