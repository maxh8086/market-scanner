# Collector split, task S0 (report only)

Date: 2026-11-12. Main checkout at 24516ec. No code changed.

## 1. Run times (from `collector_runs`, read-only)

Query: last 60 rows per source ordered by `started_at` desc; duration = `finished_at - started_at` over the latest 30 rows with both timestamps.

| source | rows read | runs used | median | max |
| :-- | --: | --: | --: | --: |
| announcements | 60 | 30 | 101.9 s | 147.5 s |
| corporate_actions | 44 | 30 | 109.6 s | 1585.5 s (about 26 min) |

- `announcements` fits a 15 min cadence on time alone (about 1.7 min median), but see the same-day risk in section 3: a faster cadence adds nothing until that is fixed.
- `corporate_actions` has one outlier of about 26 min; the median is about 1.8 min. Set the max runtime (S4) above that, or investigate the outlier. Only 44 rows exist in total.
- Other sources were not asked for and are not measured.

## 2. Start-up time

Not measured in this step (no container run). Open for S4 / the Docker slice; the spec's threshold is about 20 s per run.

## 3. Existing pacing (from code)

- `scanner/marketdata/factors_postgres.py:28-29`: `REQUEST_INTERVAL_SECONDS = 3`, `RETRY_BACKOFF_SECONDS = 10`; sleep at line 56 inside the shared `_fetch_nse_feed` retry loop (used by announcements and corporate_actions). An NSE homepage cookie warm-up GET is at line 97.
- `scanner/factors.py:698`: `time.sleep(1)` on the failure path ("polite rate-limiting").
- `scanner/orderval.py:443`: `REQUEST_SLEEP = 1.0`; `enrich.py:71` sleeps it between filing PDF downloads in `stage_filings`.
- `scanner/collect/scheduler.py`: no sleep, pace or interval constants (grep found none); cadence lives in `collector_settings` rows.
- Same-day coverage (spec risk 1): both feeds use `scanner.coverage` `missing_windows` / `record_coverage` (imported at `factors_postgres.py:15`). Not read in this step; S1a must confirm.

## 4. Hosts

- `filings` source: `scanner/collect/sources.py:282-355` calls `enrich._candidate_filings` then `enrich.stage_filings` (`enrich.py:245`). `stage_filings` warms the cookie jar against `https://www.nseindia.com` (`enrich.py` around line 286; the comment there says nsearchives rejects a cold client) and downloads each PDF from the `attchmntFile` URL stored on the announcement row (`enrich.py:200`, `factors.py:463`) through `orderval.fetch_filing_text` (`orderval.py:460`). Hosts: `www.nseindia.com` and the NSE archive host named in the stored URLs (`nsearchives.nseindia.com` per the code comment). I did not enumerate the stored URLs from data.
- `announcements` / `corporate_actions`: `https://www.nseindia.com/api/corporate-announcements` and `/api/corporates-corporateActions` (`factors_postgres.py:359, 387`).
- `ath_scan`: Upstox API via `scanner/upstox.py` (`UpstoxClient`); NSE feeds for factor enrichment through `scanner/factors.py` unless `--no-factors`; index membership and history come from Postgres, not fetched.
- `fundamentals`: screener.in via `scanner/screener.py`.
- Reference job: `https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv` (`company_reference.py:70`), `https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv` (`company_reference_job.py:38`), plus the Upstox NSE master.
- `scanner/crosscheck.py:97`: bhavcopy at `https://nsearchives.nseindia.com/products/content` (crosscheck only).

## 5. Consumers of `output/ath_scan_*.csv` (verified by grep on main)

Writer: `scanner/report.py:83-84` (`write_outputs`: `df.to_csv(csv_path)` and the xlsx), called from `ath_scan.py:395`. The `AthScan` source (`sources.py:433-481`) wraps it and raises when no CSV is written (`sources.py:472`).

| draft entry | verdict | what it reads |
| :-- | :-- | :-- |
| `sources.py:376-418` (Fundamentals) | confirmed (glob 376, skip 380, FileNotFoundError skip 418) | `symbol` only |
| `sources.py:301` and `342` (Filings) | confirmed (glob 301, skip 305, FileNotFoundError skip 342) | whole frame passed to `enrich._candidate_filings`: `isin`, `symbol` (`enrich.py:184-187`) |
| `enrich.py:78` | confirmed (`latest_scan` glob); `load_scan` follows | whole frame; requires `symbol`, fills `isin` if missing |
| `enrich.py:1008` | confirmed (`scan_path.stem.replace("ath_scan_", "")`) | the date in the file name only |
| `record_run.py:111` | confirmed (`output/ath_scan_{run_date}.csv`, `_scan_is_empty`) | whether the file has zero rows |
| `portfolio.py:67` | confirmed (`find_latest("ath_scan_*.csv")`, read at 71) | `symbol` plus `bucket`, `distance_pct`, `ath_date`, `above_ema50`, `above_sma200` (`scanner/portfolio.py:231-235`) |
| `crosscheck.py:67` | confirmed (`find_latest_scan` glob; date parsed from the file name at 71-73 and 98) | `symbol`, `ltp` (required); `symbol`, `ath_high`, `ath_date` for `check_ath` (`scanner/crosscheck.py:441`) |
| `start.ps1:207, 228` | CORRECTED to `start.ps1:221` (glob) and `start.ps1:242` ("No output/ath_scan_<date>.csv found" message); the script also takes `RunDate` from the newest file name and counts rows with `Import-Csv` just after line 221 | file name (date), row count |
| `tests/test_collect_ath_scan.py:29,64`, `tests/test_empty_scan.py:26` | confirmed | write the CSV |

Also found, not in the draft:
- `ui/SCHEMA.md:86` mentions the `output/` hand-over files (documentation; update with S2a).
- `tests/test_collect_settings_sources.py:50` only names `ath_scan` as a registered source; not a CSV consumer.
- A stale copy of `start.ps1` and the tests lives under `.claude/worktrees/agent-a78dd32abc729a5e4/` (lines 207 and 228 there); that is the likely origin of the draft's numbers. Ignore it.
- `conclude.py` does not reference `ath_scan_`. The human export (`scanner/report.py:83-98`) stays.

Columns the table must carry (input to S2a): the full `report.write_outputs` frame: `symbol, company, industry, ltp, today_high, ath_high, ath_date, ath_close, distance_pct, bucket, days_since_ath, listed_days, recent_ipo`; trend (`ema50, sma200, above_ema50, above_sma200, trend`); factors (`bonus_issue, demerger, orderbook_signal, expansion_signal, factors_matched` and the rest of `FACTOR_COLUMNS`); plus `isin` where present. Readers use `keep_default_na=False` so a symbol `NA` and the `INSUFFICIENT_HISTORY` label survive; the table reader must keep that (empty string, not NULL, for text columns).

## 6. Mongo consumers beyond filings (grep of `docstore`, `scanner.mongo`, `pymongo`)

Collector sources: `Filings` (`sources.py:295,317`) and `Fundamentals` (`sources.py:370,389,393`) both open `docstore`. `candles_eod`, `index_eod`, `announcements`, `corporate_actions` and `ath_scan` do not import it. `sources.py:13` imports only `scanner.mongo._redact` (a string redactor, no connection).

Outside the collector: `enrich.py:43,1088`, `conclude.py:32,111,143`, `graph_sync.py:22,33,48`, `scanner/fundamentals.py:34`, `scanner/retention.py:24,114`, `scanner/orderval.py`, `scanner/mongo_import.py`, `ui/app/api.py:16` (`_redact` only), `bench_extract.py`, `bench_models.py`. `ath_scan.py:37` lists `scanner/mongo.py` only as a config-file name.

So `fundamentals` needs Mongo as well as `filings`, and must keep the Mongo network and secrets in the split.

## 7. Symbol-update job

`scanner/company_reference_job.py`, run as `python -m scanner.company_reference_job` (its docstring calls it the "Monthly job"). It stores `company_reference` (NSE `EQUITY_L.csv` and the Upstox NSE master) and `index_constituents` for each index in `SCAN_INDEXES`, in one transaction, with a loader role (`POSTGRES_LOADER_USER`, password file named by `POSTGRES_LOADER_PASSWORD_FILE`). It is not a key in `SOURCES` (`sources.py:616-624`: candles_eod, index_eod, announcements, corporate_actions, filings, fundamentals, ath_scan), so the collector does not schedule it today; `enrich.py:253` tells the user to run it by hand. The split needs its own entry for it, kept off the three hot sources.

## 8. `ath_scan` inputs and outputs

- Inputs: Postgres (history through `scanner.marketdata`, `scanner.pg.db`, constituents from `index_constituents`, ISIN master via `isin_resolver`); Upstox API (`UpstoxClient`, `QUOTE_BATCH_SIZE`, instrument keys); corporate factors (`scanner.factors`, NSE feeds, skippable with `--no-factors`). Arguments: `--max-dist` (default 26), `--index`, `--symbols`, `--constituents`, `--rebuild`, `--refresh-history`, `--refresh-factors`, `--output-dir`.
- Outputs: `output/ath_scan_<date>.csv` and `.xlsx` (`report.write_outputs`, `ath_scan.py:395`) and `report.write_skipped` (line 397); run statistics printed (Upstox request and 429 counts). No Mongo.
- The collector wrapper `AthScan` (`sources.py:433-481`) imports `ath_scan` from `/app/ath_scan.py` and fails when no new CSV appears.

## 9. What `portfolio.py` and `crosscheck.py` need, and how they get it

Both are root scripts run by `start.ps1` outside the collector container, so they cannot call the collector.

- `portfolio.py` (via `scanner/portfolio.py:overlay`): `symbol`, `bucket`, `distance_pct`, `ath_date`, `above_ema50`, `above_sma200`; it tests `bucket` values `NEW_ATH_TODAY` and `0-5%`.
- `crosscheck.py` (via `scanner/crosscheck.py`): `symbol`, `ltp` (compared with bhavcopy close) and `symbol`, `ath_high`, `ath_date` (`check_ath`); the scan date currently comes from the file name.

Recommendation for S2a: add one read helper in `scanner/` (for example `read_latest_scan(conn, as_of=None) -> (DataFrame, date)`) that selects the newest `scan_date` from `ath_scan_candidates`. Both scripts call it instead of globbing; `--scan PATH` and `--date` stay as a manual override that reads a CSV a person supplies. The date comes from a `scan_date` column, so `enrich.py:1008`, `record_run.py:111` and `start.ps1:221-242` (row count becomes a `select count(*)`) need that column too. The table needs `scan_date` and a unique `(scan_date, symbol)` so a same-day re-run replaces rather than doubles. The human CSV/xlsx from `scanner/report.py` stays, and no machine path reads it.

## Open items

- Start-up time per container not measured.
- `missing_windows` / `record_coverage` same-day behaviour not read here; S1a must confirm.
- The 26 min `corporate_actions` outlier is not investigated.
- Filing PDF hosts come from stored `attchmntFile` values; the exact host set was not enumerated from data.
