-- Grants for the Fastify server container's own database login, market_scanner_server (collector-split S3, decided 2026-11-14).
-- The role is NOT created here and no password is set here: the user creates it out of band
-- (CREATE ROLE market_scanner_server LOGIN PASSWORD ...) and keeps the password in the file mounted at
-- /run/app-keys/server_db_password, same split as market_scanner_loader. This file holds no secret.
-- Apply it only after the role exists; GRANT fails on a missing role.
-- Least privilege, from what server/src actually queries on the main pool: SELECT where it only reads.
-- No UPDATE and no sequence grants anywhere (no serial columns are touched; ids are uuids).

GRANT SELECT ON runs, stock_snapshots, snapshot_changes, candles, symbol_sector, collector_runs TO market_scanner_server;

-- Scan presets: list, save and delete (server/src/presets.ts). No UPDATE.
GRANT SELECT, INSERT, DELETE ON scan_presets TO market_scanner_server;

-- UI Refresh button queues a manual run (server/src/collectorRefresh.ts). SELECT covers the duplicate check and RETURNING id.
-- The collector_settings foreign key is checked by PostgreSQL as the owner of that table, so no grant on it is needed.
GRANT SELECT, INSERT ON collector_requests TO market_scanner_server;

-- home_events is NOT granted here. It lives in the separate events database (db/events_migrations/001_home_events.sql);
-- the server's events pool is the open part of F-T5c, and that database's grants belong to that work.
