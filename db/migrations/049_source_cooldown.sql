-- Shared block cooldown per source host (docs/designs/t4f-mvp-plan.md, D7): a flat 1 hour, read by GET /internal/due in S5a and written by the collector containers.
-- One row per host; cooldown_until NULL means no cooldown (reset keeps the row, so a host stays listed).
-- No grants here: migration 050 (S5a) grants SELECT to market_scanner_app; the collector connects as the owner role.
-- Down-step: db/migrations/down/049_source_cooldown.down.sql (manual, not applied by the runner).

CREATE TABLE IF NOT EXISTS source_cooldown (
  host           text PRIMARY KEY CHECK (host = lower(btrim(host)) AND host <> ''),
  cooldown_until timestamptz,
  reason         text,
  updated_at     timestamptz NOT NULL DEFAULT now()
);
