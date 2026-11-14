-- Undo 059. Revokes exactly the column-level UPDATE granted by 059. The role itself is not dropped.
REVOKE UPDATE (status, finished_at, message) ON collector_runs FROM market_scanner_server;
