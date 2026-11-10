-- Home event feed table. Spec: docs/designs/home-events-filings-spec.md.
-- No GRANT: the migration runs as the app login, which owns the database (4.5), so it owns the table.
-- Down-step: db/events_migrations/down/001_home_events.down.sql (manual).
CREATE TABLE home_events (
  dedupe_key    text PRIMARY KEY,
  exchange      text NOT NULL CHECK (exchange IN ('NSE')),
  feed_code     text NOT NULL,
  source_id     text,
  source_url    text NOT NULL,
  isin          text NOT NULL,
  symbol        text NOT NULL,
  company       text,
  event_type    text NOT NULL CHECK (event_type IN
                  ('results','insider_trade','governance','corporate_action','shareholding','related_party')),
  feed_tier     text NOT NULL CHECK (feed_tier IN ('high_priority','catalyst')),
  headline      text NOT NULL,
  published_at  timestamptz NOT NULL,
  fetched_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX home_events_isin_pub_idx ON home_events (isin, published_at DESC);
CREATE INDEX home_events_pub_idx ON home_events (published_at DESC);
