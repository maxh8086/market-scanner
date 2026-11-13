-- llm_calls gains the provider columns (LC5, M-16).
-- provider_id: the llm_provider row the call went through. route: "native" or "compat".
-- base_host: the host only (no scheme, port, path or query).
-- All three are nullable: calls written before this migration have no provider.
-- The stage CHECK is unchanged.
-- Down-step: db/migrations/down/055_llm_calls_provider.down.sql (manual, not applied by the runner).

ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS provider_id text;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS route text;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS base_host text;
