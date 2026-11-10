# Market Scanner Blueprint

## System Overview
Market Scanner screens NSE equities for all-time-high (ATH) breakouts and
enriches each candidate with fundamentals, exchange filings, order-value
significance, market-intensity context, forecasts and an LLM-written
conclusion. The output is an Excel workbook plus a browsable UI.

The repository has four layers:

- **Root CLI scripts** (`*.py` in this directory): one entry point per stage
  (scan, enrich, conclude, report, cross-check, portfolio overlay, run
  recording, graph sync, model benchmarks).
- **`scanner/`**: the importable library the CLIs and UI share.
- **Storage**: Postgres (schema in `db/`), a document store (TinyDB or MongoDB),
  an optional Neo4j graph, and local SQLite or `data/` caches.
- **Front ends**: `ui/` (FastAPI app that serves a static SPA and a JSON API)
  and `ui-v2/` (React/Vite client). `server/` is a Fastify API that the
  `ui-v2/` client calls.

## Local Interface & Invariants
Direct files in this root. Each script exposes a `main()` entry point.

- `ath_scan.py`: `parse_args`, `main`, `batched`, `is_intraday`, `now_ist`,
  `_check_backend`, `_record_isin_history`. Runs the ATH scan.
- `collect.py`: `cmd_run`, `cmd_serve`, `cmd_status`, `split_registered`,
  `main`. Collector CLI with `run`, `serve` and `status` modes.
- `enrich.py`: `stage_fundamentals`, `stage_filings`, `stage_reparse`,
  `stage_llm`, `stage_backfill_announcements`, `stage_report`, `latest_scan`,
  `load_scan`, `main`. Enrichment stages for the newest scan.
- `conclude.py`: `newest_enriched`, `main`. Writes per-stock conclusions.
- `final_report.py`: `newest_enriched`, `newest_conclusions`, `main`. Writes the
  final Excel report.
- `crosscheck.py`: `parse_args`, `find_latest_scan`, `main`. Compares scan
  output with independent price sources.
- `portfolio.py`: `parse_args`, `find_latest`, `main`. Portfolio overlay.
- `record_run.py`: `_scan_is_empty`, `_finish`, `main`. Records a run outcome.
- `graph_sync.py`: `_all`, `main`. Loads the document store into Neo4j.
- `bench_models.py`: `main`, `trial`, `run_stocks`, `start`, `wait_ready`.
  Runs the fixed acceptance test on each candidate model.
- `bench_extract.py`: `pick`, `main`. Runs the extraction acceptance test.

Invariants:

- Each script is a standalone CLI. Reusable logic belongs in `scanner/`, not
  here.
- Model benchmarks (`bench_models.py`, `bench_extract.py`) run the fixed
  acceptance tests in `scanner/modelcheck.py` and `scanner/extractcheck.py`
  before a model is adopted.

## Subdirectories & System Boundaries
- `config/`: JSON settings (`glossary.json`, `retention.json`). No code
  contract, so it is not linked.
- [db](./db/EGM.md): Postgres schema migrations (main and events databases).
- `docker/`: Dockerfiles only. No code contract, so it is not linked.
- `docs/`: design docs and progress notes. Skipped by `.egmignore`.
- [scanner](./scanner/EGM.md): core library (ATH logic, fetchers, parsers,
  stores, secrets, collector).
- [scripts](./scripts/EGM.md): one-off data loaders and sector fetchers.
- [server](./server/EGM.md): Fastify TypeScript API for the `ui-v2` client.
- `tests/`: offline test suite. Test-only, so not documented here.
- [ui](./ui/EGM.md): FastAPI app that serves the legacy SPA and JSON API.
- [ui-v2](./ui-v2/EGM.md): React and Vite client.

## Global Invariants
- Browsers never open Postgres, MongoDB or Upstox connections. The `ui-v2`
  client only calls HTTP endpoints of `server/`, and the legacy `ui/` app only
  calls its own FastAPI routes.
- Schema changes go through `db/` migrations, never ad-hoc DDL.
- Secrets stay out of git. They live in the encrypted app-secrets store and
  `.env` (see `.env.example`), both git-ignored.
- Generated outputs (`output/`, `data/`, `logs/`) are local state and are not
  source.

## Global Side Effects
- Postgres reads and writes (main database, plus the events database for
  `home_events`), and DDL when migrations run.
- Document store writes: TinyDB JSON or MongoDB, subject to retention purges.
- Optional Neo4j graph writes.
- Network calls to Upstox, Kite, NSE, screener.in, and Telegram for alerts.
- Local LLM calls and model-server start-up in benchmark scripts.
- Writes under `output/` (Excel and CSV), `logs/`, and SQLite caches in `data/`.

## System Verification
- Run: `.venv/Scripts/python.exe -m pytest` (the `pyproject.toml` build gate).
  The offline `unittest` form from `CLAUDE.md` also works:
  `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`.
- Run: `npm test` in `server/` and `ui-v2/`.
