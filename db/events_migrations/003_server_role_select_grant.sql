-- Read grant for the Fastify server login market_scanner_server in the events database (NEW-HOME-FEED part A).
-- The role is created out of band by the user (see main-database migration 057); this file creates no role and holds no secret.
-- GET /api/events reads home_events (server/src/eventsRead.ts), so SELECT is the only privilege added here.
-- Written, not applied: the user applies it to the events database.
GRANT SELECT ON home_events TO market_scanner_server;
