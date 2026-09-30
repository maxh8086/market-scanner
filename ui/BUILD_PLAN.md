# Build plan and ownership (read this first)

Approved decisions (from the user, 2026-09-30):

1. **Candles and NSE data move to Postgres.** Export from `data/history.db` and `data/factors.db`, import into Postgres, then read and write Postgres.
2. **Collection is separate from analysis.** A collector fetches data and pushes it to the databases. Candles are fetched **end of day only**. Fundamentals, announcements, corporate actions and exchange filings are fetched **as and when reported**. A run analyses what is stored and only fills gaps.
3. **Master configuration in the UI** sets, per source, `scheduled` (default, cron in Asia/Kolkata) or `manual`, and a "Run now" button always works. Stored in `collector_settings`.
4. **Announcements must cover both ends.** Required window per stock is `max(listing date, today - 3 years)` to today. Check the *start* as well as the end; fetch only the gaps. Announcements are linked in Neo4j and summarised in a Postgres table.
5. **Filings are pushed to Neo4j right after extraction**, not only at the end of the pipeline.
6. **No provider prices anywhere.** The Cost center shows measured metrics only (tokens, seconds, GPU energy) so the user can work out cost themselves. No price tables, no comparison, no lookups.
7. A re-run for the same trading date replaces the earlier run only when the new one completes.

## Environment for every agent

- Project root: `C:\Users\vaibh\Downloads\Projects\Kite-ATH-Scanner`. Windows, Git Bash. Python: `.venv/Scripts/python.exe` (3.10 on host; the Docker images are 3.13, so write code valid for both).
- Postgres, MongoDB and Neo4j are already running (shared infra, project `ath_scanner`). Load the logins and reach them from the host like this:
  ```bash
  set -a; . ../Shared-Market-Research-Infra/secrets/ath_scanner.env; set +a
  export PYTHONIOENCODING=utf-8 INFRA_LOCAL=1
  ```
  `INFRA_LOCAL=1` makes `scanner/infra.py` rewrite the in-network hostnames to `127.0.0.1` ports. Use `127.0.0.1`, never `localhost` (IPv6 lookups stall for minutes on this machine).
- **Never print, log or commit a password or DSN.** Do not read `.env` (Upstox/Kite keys) at all.
- Already installed in the venv: psycopg 3, pymongo, neo4j, fastapi, uvicorn, croniter, tinydb, pandas. They are listed in `requirements.txt`.
- Postgres helpers already exist: `scanner/pg/db.py` (`connect()`, `transaction()`, `available()`), `scanner/pg/migrate.py` (applies `db/migrations/*.sql` once each, records a hash). `001_core.sql` is applied and **frozen**: never edit an applied migration, add a new one.
- Full test command (must stay green, 675 OK with 2 skipped at the start):
  `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests -t . -q`
  `tests/__init__.py` forces `MARKETDATA_BACKEND=sqlite` and `DOCSTORE_BACKEND=tinydb`, so unit tests never touch the shared databases. Tests that need a real database must create a throwaway Postgres schema or Mongo database and drop it afterwards, and must skip cleanly when the database is unreachable.
- Match the surrounding code: comment density, naming, idiom. Python only for backend code. No emojis. British/neutral plain English in comments.
- Do **not** run `docker compose build`, `start.ps1`, the full pipeline, or anything that spends Upstox quota or calls NSE for more than a few requests while testing. Do not run the vLLM stack. Do not restart or reconfigure the shared infra containers.
- Do not `git commit`, `git push`, or change git state. The lead commits.
- Do not edit `docker-compose.yml`, `start.ps1`, `stop.ps1`, `README.md`, `requirements.txt`, `db/migrations/001_core.sql`, `tests/__init__.py`. If you need a change there, say exactly what in your report and the lead applies it. If you need a new Python package, say which.

## Ownership (files each agent may create or edit; everything else is read-only for it)

| Agent | Owns |
|-------|------|
| A market-data | `scanner/history.py`, `scanner/factors.py`, `scanner/marketdata/*` (new), `scanner/coverage.py`, `db/migrations/010_market_data.sql`, `scanner/pg/import_sqlite.py`, `tests/test_history*.py`, `tests/test_factors*.py`, `tests/test_coverage.py`, `tests/test_marketdata*.py` |
| B runs | `scanner/runs.py`, `scanner/pg/backfill.py`, `record_run.py`, `db/migrations/020_views.sql`, `tests/test_runs*.py`, `tests/test_backfill.py` |
| C documents and graph | `scanner/docstore.py`, `scanner/graph.py`, `graph_sync.py`, `scanner/retention.py`, `scanner/fundamentals.py`, `enrich.py`, `scanner/mongo.py` (new), `tests/test_docstore.py`, `tests/test_graph.py`, `tests/test_retention.py`, `tests/test_fundamentals.py`, `tests/test_enrich.py`, `docker/enrich/Dockerfile` |
| D metrics | `scanner/llm.py`, `scanner/conclude.py`, `conclude.py`, `scanner/metrics.py` (new), `scripts/gpu_sample.ps1` (new), `tests/test_llm.py`, `tests/test_conclude.py`, `tests/test_stage_llm.py`, `tests/test_metrics.py` |
| E collectors | `collect.py`, `scanner/collect/*` (new), `tests/test_collect*.py` |
| F UI | everything under `ui/` except `ui/BUILD_PLAN.md`, `ui/SCHEMA.md`; `docker/ui/*` (new); `tests/test_ui*.py` |

Cross-agent contracts (code against these names; the owner promises them):

- **Backend switches.** `MARKETDATA_BACKEND` = `postgres` | `sqlite` (default `postgres` when `scanner.pg.db.available()`, else `sqlite`). `DOCSTORE_BACKEND` = `mongo` | `tinydb` (default `mongo` when `MONGO_URI` is set, else `tinydb`). Public function names and signatures in `history.py`, `factors.py` and `docstore.py` do not change; only where they store changes.
- **A provides** (`scanner/coverage.py`): `required_start(listing_date, today, years=3) -> date`; `missing_windows(feed, need_from, need_to) -> list[tuple[date, date]]` (gaps in the recorded coverage for a feed, so a caller fetches only those); `announcement_coverage() -> list[dict]` per symbol with `symbol, listing_date, required_from, first_date, last_date, rows, ok`. Postgres tables from `010_market_data.sql`: `candles`, `symbol_stats`, `announcements`, `corporate_actions`, `feed_coverage(feed, from_date, to_date)`, `symbol_listing(symbol, isin, listing_date, source)`, and view `v_announcement_summary(symbol, isin, category, n, first_date, last_date)`. A also exposes `history.collect_eod(...)` and `factors.collect_announcements(...)`, `factors.collect_corporate_actions(...)`, each returning `{"fetched": int, "new": int, "from": date|None, "to": date|None}` and fetching gaps only.
- **B provides** (`scanner/runs.py`): `start_run(run_date, trigger="manual") -> uuid`, `record_snapshots(run_id, enriched_df, conclusions) -> int`, `compute_changes(run_id) -> int`, `finish_run(run_id, status, **fields)`, plus CLI `record_run.py`. Views (`020_views.sql`): `v_run_summary`, `v_stock_timeline`, `v_run_metrics`.
- **C provides**: the unchanged docstore API on Mongo; `scanner/mongo.py: db()`; `graph.Graph.push_filing(filing, extraction)` called from `enrich.stage_llm` right after each extraction; `graph.Graph.sync_announcement_summary(rows)`; a `graph_sync.py --announcements` mode fed from `v_announcement_summary`; and the in-repo Screener client (`scanner/screener.py`) that replaces the `screener_mcp` import the enrich image lacked.
- **D provides** (`scanner/metrics.py`): `record_call(stage, source_key, symbol, model, input_tokens, output_tokens, seconds, ok)` (no-op unless `RUN_ID` is set; writes to `llm_calls` with `ON CONFLICT DO NOTHING`, falls back to `logs/metrics/<run_id>.jsonl` if Postgres is down); `finalize(run_id)` which fills `runs.gpu_*` and `runs.stage_timings`.
- **E provides**: `collect.py` with subcommands `run <source>`, `serve` (scheduler loop that reads `collector_settings` every minute, runs due `scheduled` sources, and claims `collector_requests`), `status`. It only calls A's and C's public functions.
- **F consumes** Postgres only (never the SQLite files, never Mongo directly): `runs`, `stock_snapshots`, `snapshot_changes`, `llm_calls`, `collector_*`, `v_*`, `v_announcement_summary`.

## What "done" means for each agent

1. Code plus tests, all new tests passing, full suite still green.
2. Live check against the real databases where it is safe (read-only, or writes confined to the tables you own and idempotent). State exactly what you ran and what it returned.
3. A short final report: files changed, public functions added, anything the lead must apply to compose / start.ps1 / requirements, anything that did not work, anything you deliberately did not do.
