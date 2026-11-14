-- Undo 050. The roles themselves are not dropped (they are created out of band).
REVOKE SELECT ON collector_settings, source_cooldown FROM market_scanner_server;
REVOKE SELECT ON collector_settings, source_cooldown FROM market_scanner_app;
