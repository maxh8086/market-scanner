-- Grants for the Fastify server login market_scanner_server in the events database (collector-split S3, F-T5c).
-- The role is created out of band by the user (see main-database migration 057); this file creates no role and holds no secret.
-- The server only inserts rows (INSERT ... ON CONFLICT (dedupe_key) DO NOTHING in server/src/homeEventsBatch.ts), so INSERT is the only privilege.
-- CONNECT on the database is not granted here (the database name is configurable); grant it by hand if CONNECT was revoked from PUBLIC (db-touchpoint-v2 question 21).
GRANT INSERT ON home_events TO market_scanner_server;
