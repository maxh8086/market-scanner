-- The EOD panel shows when the index_eod source last finished successfully. The Fastify server reads
-- that from collector_runs (server/src/collectorRefresh.ts, GET /api/collector/index-eod/status).
-- Read only: the collector service writes the table, and the app role never inserts or updates it.

GRANT SELECT ON collector_runs TO market_scanner_app;
