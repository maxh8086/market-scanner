-- Saved scan presets: named sets of results-page filters, written by the Fastify
-- server through /api/presets. filters holds a JSON object of allowed filter keys.
-- Validation of keys and values lives in server/src/presets.ts.
CREATE TABLE IF NOT EXISTS scan_presets (
  preset_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 60),
  filters     jsonb NOT NULL CHECK (jsonb_typeof(filters) = 'object'),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- The table is created as the admin role, so the app role needs explicit grants.
-- GRANT is idempotent, so re-running this migration is safe.
GRANT SELECT, INSERT, UPDATE, DELETE ON scan_presets TO market_scanner_app;
