-- Dedupe record for token expiry alerts (docs/designs/fundamentals-upstox-secondary.md, alert section;
-- docs/designs/secrets-and-roles.md decision 14). One row per alert that was actually sent.
-- The key is (secret name, expires_on, alert kind), so the same alert is never sent twice for one expiry.
-- Down-step: db/migrations/down/046_token_expiry_alert.down.sql (manual, not run by the runner).

CREATE TABLE token_alert_sent (
  secret_name text NOT NULL,
  expires_on  date NOT NULL,
  alert_kind  text NOT NULL CHECK (alert_kind IN ('d30', 'd7', 'd1', 'd0', 'auth')),
  sent_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (secret_name, expires_on, alert_kind)
);

-- Insert and read only. No DELETE or UPDATE grant: a record of a sent alert is never removed by the app.
GRANT SELECT, INSERT ON token_alert_sent TO market_scanner_app;
