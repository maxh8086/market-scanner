# app

## Overview
FastAPI application for the legacy UI. `main.py` wires the app and the
lifespan check for the master key. `api.py` holds the JSON routes.
`queries.py` holds the SQL statements, including the collector-setting and
collector-request writes.

## Interface
- `main.py`: `lifespan`, `check_master_key`, `health`, `serve_spa`,
  `no_cache_static`. The app object is the module-level FastAPI instance.
- `api.py`: `get_runs`, `get_run`, `get_results`, `get_stock`,
  `get_cost_summary`, `get_cost_for_run`, `get_report`, `get_config`,
  `update_config`, `request_manual_run`, `get_secrets`, `put_secrets`,
  `ConfigUpdateRequest`, `SecretsUpdate`, `serialize_row`, `serialize_run`,
  `resolve_run_id`, `safe_connection`, `_describe_cron`.
- `queries.py`: SQL statements for runs, results, stocks, costs and collector
  settings.
- `indicators.py`: `sma`, `ema`, `rsi` for the stock page.
- `internal_secrets.py`: `get_internal_secret`, `_read_expected_token`. Serves
  secrets to other services that present the expected token.
- `static/`: [static](./static/EGM.md) SPA assets.

## Invariants
- The SQL writes in `queries.py` are limited to collector settings and collector
  requests (`UPDATE_COLLECTOR_SETTING`, `INSERT_COLLECTOR_REQUEST`).
- `safe_connection` wraps database access for the API routes.
- `check_master_key` is the startup master-key check.
- Internal secret lookups compare against the expected token before any value
  is returned.

## Side Effects
- Postgres reads, and writes to configuration and secrets tables.
- Manual run requests (`request_manual_run`) insert a collector request.
- Secrets routes (`get_secrets`, `put_secrets`) read and write secret values.
- Serves static files with no-cache headers (`no_cache_static`).

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root (covers
  `tests/test_ui_api.py`, `tests/test_ui_indicators.py`).
