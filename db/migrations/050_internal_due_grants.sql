-- Grants for GET /internal/due (collector-split S5a, decided 2026-11-14).
-- 050 follows 049 (source_cooldown), which had no grants and said this migration would grant SELECT on it.
-- The Fastify server computes the due list from collector_settings and source_cooldown, so the server login
-- market_scanner_server needs SELECT on both (migration 057 covers its other tables). The app role
-- market_scanner_app gets the same two grants, as the slices doc names it too.
-- The roles are NOT created here and no password is set here; this file holds no secret.
-- Apply it only after both roles exist; GRANT fails on a missing role.
-- SELECT only: the route reads these tables and never writes them. collector_requests, collector_runs
-- are already granted by 042, 043 and 057 and are not repeated here.

GRANT SELECT ON collector_settings, source_cooldown TO market_scanner_server;
GRANT SELECT ON collector_settings, source_cooldown TO market_scanner_app;
