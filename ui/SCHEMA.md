# Database plan for the ATH Scanner UI

Status: **proposal, nothing built.** Read alongside `ui/wireframes/index.html` and `ui/DESIGN.md`.

Goals, from the brief:

1. No duplicate rows in any case, including re-runs, retries and restarts.
2. Every stock keeps a timeline: one analysis record per run, with what changed since the previous one.
3. Never re-download exchange data that is already stored.
4. Store real token and timing metrics so the Cost center compares like with like.

## 1. What exists today (measured 2026-09-30)

| Store | Content | Size | Dedupe today |
|-------|---------|------|--------------|
| `data/history.db` (SQLite) | `candles(symbol,date,OHLCV)`, `symbol_stats` | 2,630,246 candles, 750 symbols | primary key `(symbol,date)` |
| `data/factors.db` (SQLite) | `announcements`, `corporate_actions`, `fetch_metadata` | 391,957 announcements, 4,037 actions | primary keys, `fetch_metadata` per feed |
| `data/documents.json` (TinyDB) | `fundamentals` 298, `filings` 968, `extractions` 868, `conclusions` 586 | one JSON file | key fields, no enforced uniqueness |
| `output/*.csv, *.xlsx` | one scan, enriched and conclusions file per run date | 286 rows per run | overwritten per date, so no history inside a store |

Run history exists only as files (2026-09-28, 09-29, 09-30). That is enough to backfill the first three points of every timeline.

## 2. Where each thing goes

| Data | Store | Why |
|------|-------|-----|
| Runs, per-stock snapshots, change log, LLM call metrics, pricing | **Postgres** (`ath_scanner` db) | relational, joins, unique constraints, the UI's queries |
| Filings (raw text), extractions, conclusions, fundamentals | **MongoDB** (`ath_scanner` db) | large, variable-shape documents, replaces TinyDB with real unique indexes |
| Relationships (customers, repeat customers, capacity) | **Neo4j** (unchanged) | already built |
| Candles, NSE announcements, corporate actions | **stay in SQLite for now** | already deduplicated and incremental; 2.6M rows moving buys nothing this phase. Revisit after the UI works |

Postgres holds only what the UI reads. Mongo holds only bulky documents. Nothing is written to both.

## 3. Postgres schema

```sql
-- One row per scan execution.
CREATE TABLE runs (
  run_id        uuid PRIMARY KEY,
  run_date      date        NOT NULL,          -- trading date the prices are for
  started_at    timestamptz NOT NULL,
  finished_at   timestamptz,
  status        text        NOT NULL CHECK (status IN ('running','complete','failed','partial')),
  is_current    boolean     NOT NULL DEFAULT true,   -- the run the UI shows for that date
  scanned       int, in_range int, at_ath int, skipped int,
  git_sha       text, prompt_version text, model text,
  gpu_name      text, gpu_watts_avg numeric
);
-- A re-run for the same date replaces the earlier one instead of duplicating it.
CREATE UNIQUE INDEX runs_one_current_per_date ON runs (run_date) WHERE is_current;

-- One row per stock per run. The timeline is this table ordered by run_date.
CREATE TABLE stock_snapshots (
  run_id         uuid    NOT NULL REFERENCES runs ON DELETE CASCADE,
  symbol         text    NOT NULL,
  isin           text,
  company        text, industry text,
  ltp            numeric, ath_high numeric, ath_date date,
  distance_pct   numeric NOT NULL,
  bucket         text    NOT NULL CHECK (bucket IN ('at_ath','within_5','within_10','within_26')),
  one_year_return_pct numeric,
  order_pct_of_sales  numeric,
  stance         text CHECK (stance IN ('constructive','mixed','cautious')),
  stance_score   numeric,
  conclusion_id  text,                          -- Mongo _id of the conclusion used
  metrics        jsonb   NOT NULL,              -- the full enriched row (all ~80 columns)
  PRIMARY KEY (run_id, symbol)                  -- cannot store a stock twice in a run
);
CREATE INDEX snapshots_symbol_run ON stock_snapshots (symbol, run_id);

-- What changed for a stock versus its previous snapshot. Written once, never edited.
CREATE TABLE snapshot_changes (
  run_id     uuid NOT NULL, symbol text NOT NULL,
  kind       text NOT NULL,      -- entered_range, left_range, bucket_change, stance_change,
                                 -- new_order_book, capacity_change, new_filing
  before     jsonb, after jsonb, note text,
  PRIMARY KEY (run_id, symbol, kind),
  FOREIGN KEY (run_id, symbol) REFERENCES stock_snapshots ON DELETE CASCADE
);

-- Every model call, for the Cost center.
CREATE TABLE llm_calls (
  call_id      uuid PRIMARY KEY,
  run_id       uuid NOT NULL REFERENCES runs ON DELETE CASCADE,
  symbol       text, stage text NOT NULL,       -- 'extract' | 'conclude'
  source_key   text NOT NULL,                   -- filing seq_id or conclusion packet_hash
  model        text NOT NULL,
  input_tokens int NOT NULL, output_tokens int NOT NULL,
  seconds      numeric NOT NULL, ok boolean NOT NULL,
  UNIQUE (run_id, stage, source_key)            -- a retried call cannot be counted twice
);

-- Prices with provenance. A row is never overwritten; a new check inserts a new row.
CREATE TABLE price_points (
  provider text NOT NULL, model text NOT NULL, tier text NOT NULL DEFAULT 'standard',
  input_per_mtok numeric, output_per_mtok numeric,
  currency text NOT NULL DEFAULT 'USD',
  source_url text, checked_on date NOT NULL,
  status text NOT NULL CHECK (status IN ('verified','to_verify')),
  PRIMARY KEY (provider, model, tier, checked_on)
);
-- Cloud GPU rental is per hour, not per token.
CREATE TABLE gpu_rates (
  provider text NOT NULL, gpu text NOT NULL, usd_per_hour numeric,
  source_url text, checked_on date NOT NULL, status text NOT NULL,
  PRIMARY KEY (provider, gpu, checked_on)
);
CREATE TABLE cost_assumptions (         -- the Cost center's editable inputs, one current row
  id boolean PRIMARY KEY DEFAULT true CHECK (id),
  inr_per_kwh numeric NOT NULL, gpu_watts numeric NOT NULL,
  hardware_inr numeric, amortize_months int, usd_inr numeric NOT NULL
);
```

Views the UI reads: `v_run_summary` (bucket and stance counts per run), `v_stock_timeline` (snapshots joined to changes, newest first), `v_run_cost` (tokens times the price row current on the run date).

## 4. MongoDB collections

All keys below have a **unique index**, so a second insert of the same thing fails instead of duplicating.

| Collection | Unique key | Notes |
|------------|-----------|-------|
| `filings` | `seq_id` | NSE sequence id. Holds `symbol`, `isin`, `an_date`, `kind`, `raw_text`. Text is fetched once and kept |
| `extractions` | `(seq_id, prompt_version, model)` | a new prompt version adds a row; the old one stays for comparison |
| `conclusions` | `(symbol, packet_hash)` | `packet_hash` is a hash of the evidence packet. Same evidence gives the same conclusion, no second model call |
| `fundamentals` | `(symbol, as_of)` | one per stock per fetch date, so trends are possible |

Writes are upserts on the unique key. `stored_at` is metadata, never part of the key.

## 5. Duplicate-proofing, in one place

| Risk | Guard |
|------|-------|
| Same run started twice on one date | `runs_one_current_per_date`. The new run marks the old `is_current=false` in the same transaction, and only after it completes |
| Crash halfway through a run | Snapshots are written in one transaction with the run's `status='complete'` flag. A `running` or `failed` run is never shown |
| Same stock twice in a run | primary key `(run_id, symbol)` |
| Same filing fetched again | Mongo unique `seq_id`; fetch is skipped if present |
| Same conclusion regenerated | unique `(symbol, packet_hash)`; identical evidence reuses the stored conclusion |
| Retried LLM call double-counted in cost | `UNIQUE (run_id, stage, source_key)` |
| Price row edited silently | prices are insert-only with `checked_on` in the key |
| Timeline diff written twice | primary key `(run_id, symbol, kind)`; the diff step is `INSERT ... ON CONFLICT DO NOTHING` |

## 6. Timeline: how "what changed" is produced

After a run is complete, one SQL step compares each snapshot to the same symbol's snapshot in the previous current run (by `run_date`):

- present now, absent before: `entered_range`. Absent now, present before: `left_range` (the stock row is written with its last known values).
- bucket differs: `bucket_change`. Stance differs: `stance_change`.
- order book ratio moved by more than a threshold, or a capacity phrase appeared: `new_order_book`, `capacity_change`.
- filings in Mongo with `an_date` after the previous run: `new_filing`.

The Stock page's timeline is `SELECT ... FROM stock_snapshots JOIN snapshot_changes ... ORDER BY run_date DESC`. Because changes are stored, old entries never change when new logic is added later; a new rule only writes new kinds.

## 7. Not re-downloading exchange data

Today `scanner/factors.py` re-checks by "was fetched today". Plan:

| Feed | Rule |
|------|------|
| Bhavcopy / candles | Fetch only trading dates after `max(date)` per symbol. Closed months are never refetched. The current month is topped up with a 2-day overlap, deduplicated by the `(symbol,date)` key |
| Announcements | Fetch from `fetch_metadata.to_date` minus 2 days to today. Keyed on the existing primary key, so overlap cannot duplicate |
| Corporate actions | Refresh at most once per 24 h; unchanged rows are skipped by primary key |
| Filing PDFs / text | Only fetched for `seq_id`s not yet in Mongo `filings` |
| Fundamentals | Refetch only when the stored `as_of` is older than the last quarterly result date |

Each fetch records what it fetched and how many rows were new, so the Run dashboard can show "38 new filings today".

## 8. Backfill

From the three existing run dates, create `runs` and `stock_snapshots` from `ath_enriched_<date>.csv` and `ath_conclusions_<date>.csv`, then compute `snapshot_changes`. This gives every stock a 3-point timeline on day one. `llm_calls` cannot be backfilled honestly (token counts were not recorded), so Cost center history begins with the first instrumented run and says so.

## 9. Decisions needed from you

1. **Same-day re-run:** replace the earlier run (recommended) or keep both and show the latest?
2. **Candles and NSE feeds:** leave in SQLite for this phase (recommended) or move to Postgres now?
3. **Pricing:** I will not invent provider prices. I need confirmed rates for OpenAI, Google, Mistral, DeepSeek, Groq, Together, Fireworks and GPU rental. May I look them up from each provider's public pricing page and mark them `verified` with the source and date?
4. **Order of work after approval:** (a) Postgres schema and backfill, (b) metrics capture in `scanner/llm.py`, (c) incremental-fetch changes, (d) the UI container.
