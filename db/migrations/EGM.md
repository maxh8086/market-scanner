# migrations

## Overview
Ordered SQL migrations for the main Postgres database. `scanner/pg/migrate.py`
applies them by filename order and records which ones ran. The files define
run and snapshot history, market data caches, constituent and relative-strength
tables, sector classification, fundamentals, collector configuration, saved
presets, app secrets and token-expiry alert state.

## Interface
Tables and views created or altered (grouped by feature):

- Run history: `runs`, `stock_snapshots`, `snapshot_changes`, `llm_calls`
  (001); `stock_snapshots` gains a left-range bucket column (011).
- Market data: `candles`, `symbol_stats`, `announcements` (010);
  `fetch_metadata`, `upstox_pull_log` (011); `isin_history`, `symbol_alias`
  (012).
- Views: `v_run_summary`, `v_stock_timeline`, `v_run_metrics` (020).
- Index membership and strength: `constituent_membership` (021),
  `relative_strength` (022, 024 adds a 3-month column).
- Sectors: `symbol_sector` (025, 044 adds external classification columns).
- Fundamentals: `fund_line`, `fund_row_map`, `fund_snapshot`, `fund_growth`
  (027).
- Collector: `collector_sources` (039), `collector_settings` altered
  (013, 014, 039, 041).
- Presets: `scan_presets` (040).
- Secrets and alerts: `app_secret` (045), `token_alert_sent` (046).
- Broker login and portfolio: `user_profile` (seeded `default`), `portfolio_sync`,
  `portfolio_holding` (058). No secrets are stored in them.
- Grants to application roles: 023, 026, 042, 043, 050, 057, 058.
- Child contract: [down](./down/EGM.md) (reverse scripts for 045 and 046).

## Invariants
- Filenames are unique and sort in apply order. Numbering gaps are allowed
  (for example 028 to 038 are unused).
- A migration must not drop data unless it has a matching `down/` script. Only
  045 and 046 have one.
- Grants (023, 026, 042, 043) run after the table they grant on.

## Side Effects
- DDL and grants on the main Postgres database when `migrate.py apply` runs.
- `ALTER TABLE` on existing tables (`stock_snapshots`, `collector_settings`,
  `relative_strength`, `symbol_sector`) can rewrite or lock them on a large
  database.

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` (covers `tests/test_pg_migrate_events.py`
  and related migration tests).
