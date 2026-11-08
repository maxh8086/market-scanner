-- Register the ath_scan collector source, which the first-run watcher queues once broker
-- API details exist. Its default row is manual, so it runs only when a request is queued.
--
-- The live collector_settings check already lists index_eod, exchange_results and gov_feeds
-- (they have rows); they are kept here so those rows stay valid.

ALTER TABLE collector_settings DROP CONSTRAINT collector_settings_source_check;
ALTER TABLE collector_settings ADD CONSTRAINT collector_settings_source_check
  CHECK (source IN ('candles_eod','announcements','corporate_actions','filings','fundamentals',
                    'index_eod','exchange_results','gov_feeds','ath_scan'));

INSERT INTO collector_settings (source, mode, cron, params)
VALUES ('ath_scan', 'manual', '0 0 1 1 *', '{}')
ON CONFLICT (source) DO NOTHING;
