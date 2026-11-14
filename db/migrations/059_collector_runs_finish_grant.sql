-- Grant for POST /internal/due/finish (collector-split S4, decided 2026-11-14).
-- The watchdog stops a collector container that ran past its max runtime. The server then marks that
-- run as failed (status, finished_at, message), so the run does not stay "running" in the table. The
-- next run-once also finalises a stale running row (advisory-lock path), so this endpoint is the
-- prompt path, not the only one.
-- Column-level UPDATE only: nothing else on collector_runs becomes writable. SELECT is already granted
-- to market_scanner_server by 057. The role is not created here; the GRANT fails on a missing role.

GRANT UPDATE (status, finished_at, message) ON collector_runs TO market_scanner_server;
