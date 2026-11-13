-- Drops the provider columns added by 055. The stage CHECK is not touched by 055 or by this file.
ALTER TABLE llm_calls DROP COLUMN IF EXISTS base_host;
ALTER TABLE llm_calls DROP COLUMN IF EXISTS route;
ALTER TABLE llm_calls DROP COLUMN IF EXISTS provider_id;
