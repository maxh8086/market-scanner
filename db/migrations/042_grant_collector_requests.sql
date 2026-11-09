-- The UI "Refresh" button queues a manual collector run by inserting into collector_requests
-- through the Fastify server (server/src/collectorRefresh.ts), which runs as market_scanner_app.
-- The table was created in 001_core.sql without a grant to that role. Read is needed for the
-- duplicate check; no UPDATE or DELETE is granted, same as collector_sources in 039.

GRANT SELECT, INSERT ON collector_requests TO market_scanner_app;
