-- llm_provider and ai_setting: the LLM provider store (LC1).
-- llm_provider lists the AI providers the app can call (one row per provider). Presets are seeded here;
-- the API stores key_ref and key_version only. Key values live in the encrypted secret store, never here.
-- ai_setting holds the active provider, model and route as key/value rows. Seeds are inserted only when
-- missing, so an active value the admin has already changed is never overwritten by a re-run.
-- Down-step: db/migrations/down/054_llm_provider_store.down.sql (manual, not applied by the runner).

-- IF NOT EXISTS: re-running this file must be a no-op, not an error that stops the run.
CREATE TABLE IF NOT EXISTS llm_provider (
  provider_id   text PRIMARY KEY,
  display_name  text NOT NULL,
  "class"       text NOT NULL CHECK ("class" IN ('ollama', 'openai_compat', 'anthropic_native')),
  origin        text NOT NULL,
  list_endpoint text,
  approved      boolean NOT NULL DEFAULT false,
  key_ref       text,
  key_version   integer NOT NULL DEFAULT 0,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_setting (
  "key"       text PRIMARY KEY,
  value       text,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Presets. ON CONFLICT DO NOTHING keeps any row an admin has already edited.
INSERT INTO llm_provider (provider_id, display_name, "class", origin, list_endpoint, approved) VALUES
  ('ollama',     'Ollama (local)', 'ollama',           'http://host.docker.internal:11434', '/api/tags',       true),
  ('openai',     'OpenAI',         'openai_compat',    'https://api.openai.com',            '/v1/models',      false),
  ('anthropic',  'Anthropic',      'anthropic_native', 'https://api.anthropic.com',         '/v1/models',      false),
  ('openrouter', 'OpenRouter',     'openai_compat',    'https://openrouter.ai/api',         '/api/v1/models',  false)
ON CONFLICT (provider_id) DO NOTHING;

-- Active selection. ON CONFLICT DO NOTHING: a value the admin has changed is kept on re-run.
INSERT INTO ai_setting ("key", value) VALUES
  ('AI_PROVIDER_NAME',  'ollama'),
  ('AI_MODEL_NAME',     'hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K'),
  ('AI_PROVIDER_ROUTE', 'native')
ON CONFLICT ("key") DO NOTHING;

-- The app reads and writes these tables (admin screen). No DELETE grant: rows are changed, not removed.
-- The loader role gets no access.
GRANT SELECT, INSERT, UPDATE ON llm_provider TO market_scanner_app;
GRANT SELECT, INSERT, UPDATE ON ai_setting TO market_scanner_app;
