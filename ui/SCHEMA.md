# Storage schema

Status: **built and in use** (as of 2026-09-30). The source of truth is `db/migrations/*.sql`,
applied in filename order by `python -m scanner.pg.migrate` (also run by `record_run.py` and the
collector). This file describes what those migrations create and why.

## Where each kind of data lives

| Store | Holds | Why there |
|---|---|---|
| Postgres (`market_scanner` db) | runs, per-stock snapshots, change log, LLM-call metrics, collector settings and history, candles, announcements, corporate actions, feed coverage, listing dates | relational, joined and filtered by the UI, needs unique keys |
| MongoDB (`market_scanner` db) | filings (with text), extractions, conclusions, fundamentals | documents of varying shape, looked up by key |
| Neo4j | Company, Filing, Extraction, Counterparty, Conclusion, Fundamentals and their relationships | customer and repeat-order questions no single filing answers; rebuildable from Mongo |
| `output/` files | scan, enriched, conclusions and report files written by each stage | hand-off between pipeline stages today; see "Files" below |

Backends are switchable for offline work and tests: `MARKETDATA_BACKEND=postgres|sqlite`,
`DOCSTORE_BACKEND=mongo|tinydb`. `tests/__init__.py` forces sqlite/tinydb, so the offline tests
do not exercise Postgres types (NUMERIC arrives as `Decimal`; the Postgres read boundary converts
it to float, see `tests/test_postgres_decimal.py`).

## Postgres tables

### Core (`001_core.sql`)

| Table | Key | Notes |
|---|---|---|
| `runs` | `run_id` (uuid) | one row per pipeline execution: date, status (`running`, `complete`, `failed`, `partial`), counts, `git_sha`, `model`, measured GPU figures (`gpu_watts_avg`, `gpu_energy_wh`, `gpu_busy_seconds`), `stage_timings` (jsonb, seconds per stage). NULL means "not measured", never zero |
| `stock_snapshots` | `(run_id, symbol)` | one row per stock per run; `bucket`, `distance_pct`, stance, and the full enriched row in `metrics` (jsonb). A stock's timeline is this table ordered by run date |
| `snapshot_changes` | `(run_id, symbol, kind)` | what changed versus the stock's previous snapshot: `entered_range`, `left_range`, `bucket_change`, `stance_change`, `new_order_book`, `capacity_change`, `new_filing`. Written once, never edited |
| `llm_calls` | `call_id`; unique `(run_id, stage, source_key)` | every model call: tokens in and out, seconds, ok. A retried call is counted once. No prices anywhere |
| `collector_settings` | `source` | Master configuration: `mode` (`scheduled` or `manual`), 5-field `cron` (Asia/Kolkata), `params`. Seeded with defaults for the five sources |
| `collector_runs` | `id` | every collection attempt: window requested, rows fetched, rows new after de-duplication, status |
| `collector_requests` | `id`; partial unique on `source` where unclaimed | "Run now" clicks. The UI inserts, the collector claims. Double-clicking cannot queue two |

Bucket values: `at_ath`, `within_5`, `within_10`, `within_26`, and `left_range` (added in
`011_left_range_bucket.sql`). `left_range` is a snapshot row carrying the stock's last known values
so the "left range" change has a row to hang on.

### Market data (`010_market_data.sql`)

| Table | Key | Notes |
|---|---|---|
| `candles` | `(symbol, date)` | daily OHLCV, end of day only, new dates only, never updated |
| `symbol_stats` | `symbol` | running ATH high/close and dates, first and last candle date |
| `announcements` | `(isin, an_dt, "desc")` | NSE announcements; `seq_id` is NSE's id and the Mongo filing key. Required depth is `max(listing date, today - 3 years)` |
| `corporate_actions` | `(isin, ex_date, subject)` | bonuses, splits, dividends, demergers |
| `feed_coverage` | `(feed, from_date, to_date)` | which windows were fetched, so only gaps are requested |
| `symbol_listing` | `symbol` | listing date inferred from the first candle, or from an NSE master file; never a guess |

### Views (`020_views.sql`, `010_market_data.sql`)

`v_run_summary` (per-run counts by bucket), `v_stock_timeline` (snapshots with the previous run's
values alongside), `v_run_metrics` (tokens, calls, throughput and GPU energy per run, the Cost
center's source) and `v_announcement_summary` (announcements per symbol and category).

## Duplicate-proofing

Every writer can be re-run without creating a second copy:

- `runs_one_current_per_date`: partial unique index, one current run per date. A re-run replaces
  the earlier one only once it completes.
- `stock_snapshots` primary key `(run_id, symbol)`, `snapshot_changes` `(run_id, symbol, kind)`.
- `llm_calls` unique `(run_id, stage, source_key)`.
- `candles` `(symbol, date)`, `announcements` `(isin, an_dt, desc)`, `corporate_actions`
  `(isin, ex_date, subject)`; writers use `ON CONFLICT` (do nothing for corporate actions, update for candles and announcements).
- `collector_requests` one open request per source.

## Cost metrics (metrics only)

The Cost center shows what was measured, not what it cost. There is no price table, no rate card
and no provider lookup. Figures come from `llm_calls` (tokens, seconds, ok), `runs` (GPU energy,
power, busy time, stage timings) and `collector_runs` (rows fetched and new). The reader
multiplies by whatever rate they choose. `python -m scanner.metrics finalize` writes the run-level
figures at the end of a run.

## MongoDB collections

`filings`, `extractions`, `conclusions`, `fundamentals`. Each record carries `expires_at` (its
date plus the retention years in `config/retention.json`); the purge step deletes a record only
when it is past that date and processed. Conclusions are referenced from `stock_snapshots.conclusion_ref`.

## Files

The pipeline stages still hand over through `output/` files: `ath_scan_<date>.csv`,
`ath_enriched_<date>.csv`, `ath_conclusions_<date>.csv`, plus the workbook and cross-check files.
Each stage picks its input as the newest file by name, so **never add a suffix or rename files in
`output/`**; move old outputs into a subfolder instead. Moving these hand-offs into the database
(keyed by `run_id`, files only as a manual export) is planned, not done.
