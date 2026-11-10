# scripts

## Overview
Standalone maintenance scripts: NSE index-constituent downloads, sector
classification fills, the Upstox 5-year candle pull and its Postgres loader,
wireframe glossary generation, and a test-database grant helper. Each file is
run by hand from the command line. None is imported by the application.

## Interface
- `build_wireframe_glossary.py`: `build_block`, `sync_wireframe`, `main`.
  Inlines the shared glossary into `ui/wireframes/index.html`.
- `fetch_index_constituents.py`: `fetch_one`, `main`. Downloads index
  constituent lists.
- `fetch_screener_sector.py`: `collect`, `main`. Collects sector data from
  screener.in.
- `fetch_upstox_sector.py`: `fetch_sector`, `main`. Fetches sector data from
  Upstox.
- `pull_upstox_5y.py`: `load_universe`, `connect`, `open_pg_pull_log`,
  `pull_log_backend`, `main`. Pulls five years of daily candles into a local
  SQLite file.
- `load_upstox_5y_to_pg.py`: `run`, `main`. Loads that SQLite file into
  `public.candles`.
- `ensure_postgres.ps1`, `gpu_sample.ps1`: PowerShell helpers (not code under
  this contract).
- `grant_test_dbs.js`: grants privileges on the test databases.

## Invariants
- Scripts write to local data files, to Postgres, or (for
  `build_wireframe_glossary.py` only) to the wireframe HTML file.
- `pull_upstox_5y.py` records pull attempts through its pull-log backend
  (`pull_log_backend`, `open_pg_pull_log`), so a failed pull can be inspected
  later.
- `load_upstox_5y_to_pg.py` reads its source file and does not change it.

## Side Effects
- Network calls to NSE, Upstox and screener.in.
- Postgres writes to the candle, sector and pull-log tables.
- Writes under `data/`.
- `build_wireframe_glossary.py` rewrites the wireframe HTML file.
- `grant_test_dbs.js` issues `GRANT` statements on test databases.

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root (covers
  `tests/test_pull_upstox_5y.py` and `tests/test_glossary.py`).
- Run: `npm test` in `server/` for the TypeScript side.
