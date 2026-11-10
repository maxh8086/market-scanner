-- App-level secrets, encrypted with the master key (docs/designs/secrets-and-roles.md, S2).
-- The master key is never stored here. Only the API decrypts ciphertext; the UI never reads this table.
-- last4 is the masked hint shown in the admin screen (decision 4). Values are never stored in plain text.
-- Down-step: db/migrations/down/045_app_secret.down.sql (manual, not applied by the runner).

CREATE TABLE app_secret (
  name        text PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9_]{1,63}$'),
  ciphertext  bytea NOT NULL,
  nonce       bytea NOT NULL CHECK (octet_length(nonce) = 12),
  key_version integer NOT NULL DEFAULT 1,
  last4       text NOT NULL,
  created_on  date NOT NULL,
  expires_on  date,
  updated_by  text NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_on IS NULL OR expires_on >= created_on)
);

-- No DELETE grant: a removed secret is overwritten or left in place, never hard-deleted by the app.
GRANT SELECT, INSERT, UPDATE ON app_secret TO market_scanner_app;
