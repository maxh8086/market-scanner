-- Portfolio snapshots for the broker login feature (phase 1: Kite). Decided 2026-11-14, design v3.
-- Holds one stored holdings snapshot per successful sync, per profile and broker.
-- The server writes a sync and its holdings in one transaction. A failed sync inserts nothing,
-- so the previous snapshot stays. Only status 'ok' is written in phase 1; 'failed' is kept for later.
-- This file holds no secret: no tokens, no api keys, no passwords. Broker credentials stay in app_secret.
-- Apply after the role exists for the grants below (same rule as 057). GRANT fails on a missing role.

-- Profiles that can own a broker connection and a portfolio. 'default' is the seeded single-user profile.
CREATE TABLE user_profile (
    profile_id   text PRIMARY KEY CHECK (profile_id ~ '^[a-z][a-z0-9]{0,15}$'),
    display_name text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

INSERT INTO user_profile (profile_id, display_name) VALUES ('default', 'Default') ON CONFLICT DO NOTHING;

-- One row per sync attempt. The latest 'ok' row per (profile_id, broker) is the current snapshot.
CREATE TABLE portfolio_sync (
    sync_id    uuid PRIMARY KEY,
    profile_id text NOT NULL REFERENCES user_profile (profile_id),
    broker     text NOT NULL CHECK (broker IN ('kite', 'upstox')),
    synced_at  timestamptz NOT NULL DEFAULT now(),
    status     text NOT NULL CHECK (status IN ('ok', 'failed')),
    row_count  integer NOT NULL CHECK (row_count >= 0)
);

CREATE INDEX portfolio_sync_profile_broker_synced_idx ON portfolio_sync (profile_id, broker, synced_at DESC);

-- Holdings of one sync. Deleting a sync removes its holdings (cascade).
-- exchange is NOT NULL DEFAULT '' so the primary key works for rows without an exchange.
-- raw holds the parsed broker holding object only (never headers or tokens).
CREATE TABLE portfolio_holding (
    sync_id        uuid NOT NULL REFERENCES portfolio_sync (sync_id) ON DELETE CASCADE,
    profile_id     text NOT NULL,
    broker         text NOT NULL,
    symbol         text NOT NULL,
    isin           text,
    exchange       text NOT NULL DEFAULT '',
    quantity       numeric NOT NULL,
    average_price  numeric NOT NULL,
    last_price     numeric NOT NULL,
    pnl            numeric NOT NULL,
    day_change     numeric,
    day_change_pct numeric,
    raw            jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (sync_id, symbol, exchange)
);

-- Grants to the Fastify server's login role. Least privilege: the server reads the profile list
-- and the latest snapshot, and appends new syncs. It never updates or deletes a snapshot.
GRANT SELECT ON user_profile TO market_scanner_server;
GRANT SELECT, INSERT ON portfolio_sync, portfolio_holding TO market_scanner_server;
