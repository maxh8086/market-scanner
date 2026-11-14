-- Registers the home_filings collector source (exchange filings feed).
-- Spec: docs/designs/home-events-filings-spec.md, section 4.1. Task F-T1 in docs/designs/t4f-mvp-plan.md.
--
-- Why: the HomeFilings source ships later in code, and its settings row must exist before that.
-- The row starts as manual, so the collect.py serve loop never runs it. F-T9 later flips it to
-- scheduled through PUT /api/config/home_filings.
--
-- The cron is set here on purpose. ensure_sources() (scanner/collect/settings.py) inserts any
-- SOURCES key with the placeholder cron 0 0 1 1 * and never changes an existing row. Without this
-- row, the placeholder would stay in place once the source is in code.
--
-- ON CONFLICT DO NOTHING keeps any value already changed in the UI.
-- Down step: db/migrations/down/052_home_filings_registration.down.sql (manual, not run by the runner).

INSERT INTO collector_sources (source) VALUES ('home_filings') ON CONFLICT (source) DO NOTHING;

INSERT INTO collector_settings (source, mode, cron, params) VALUES
  ('home_filings', 'manual', '*/5 8-20 * * 1-5', '{}')
ON CONFLICT (source) DO NOTHING;
