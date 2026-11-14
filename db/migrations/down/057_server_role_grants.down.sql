-- Undo 057. The role itself is not dropped (it is created out of band).
REVOKE SELECT ON runs, stock_snapshots, snapshot_changes, candles, symbol_sector, collector_runs FROM market_scanner_server;
REVOKE SELECT, INSERT, DELETE ON scan_presets FROM market_scanner_server;
REVOKE SELECT, INSERT ON collector_requests FROM market_scanner_server;
