-- Undo 058. Destroys every stored portfolio snapshot and the profile rows. Take a backup first.
-- Dependency order: holdings reference syncs, syncs reference profiles.
DROP TABLE portfolio_holding;
DROP TABLE portfolio_sync;
DROP TABLE user_profile;
