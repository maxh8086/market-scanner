# marketdata

## Overview
The market-data storage backend. `__init__.py` selects a backend and exposes
the entry points the rest of `scanner/` calls. The Postgres implementation
stores candles, symbol statistics, announcements and corporate actions.

## Interface
- `__init__.py`: `get_backend`, `get_history_impl`, `get_factors_impl`.
  Backend selection is done here.
- `postgres_backend.py`: `get_history`, `collect_eod`, `cached_closes`,
  `_save_candles_pg`, `_update_symbol_stats_pg`, `_load_cached_candles_pg`.
- `factors_postgres.py`: `collect_announcements`, `collect_corporate_actions`,
  `fetch_announcements_pg`, `fetch_corporate_actions_pg`, `was_fetched_today_pg`,
  `mark_fetched_pg`, `nse_session`.

## Invariants
- Callers use `get_history_impl` and `get_factors_impl`, not a backend module
  directly, so the backend can be switched in one place.
- Fetch markers (`was_fetched_today_pg`, `mark_fetched_pg`) limit how often
  announcements and corporate actions are re-fetched in a day.
- Month windows (`_month_windows`) keep NSE requests to bounded ranges.

## Side Effects
- Postgres reads and writes: `candles`, `symbol_stats`, `announcements`,
  corporate actions, `fetch_metadata`.
- NSE HTTP session (`nse_session`) for announcements and corporate actions.

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root (covers
  `tests/test_backend_dispatch.py`, `tests/test_backend_defaults.py`,
  `tests/test_factors_backend.py`).
