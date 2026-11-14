# scanner

## Overview
The importable library behind the root CLIs. It holds the ATH logic, all
fetchers and parsers (Upstox, Kite, NSE filings, screener.in), the stores
(Postgres, TinyDB or MongoDB, SQLite caches), the enrichment and LLM stages,
report writers, and the app-secrets subsystem. Pure logic such as `ath.py`
does no I/O, so it can be unit-tested directly.

## Interface
Public symbols by module:

- Core scan: `ath.py` (`compute_ath`, `distance_pct`, `classify_bucket`,
  `scan_symbol`, `ScanResult`), `indicators.py` (`sma`, `ema`,
  `compute_trend`), `volatility.py` (`realized_vol_series`, `vol_state`),
  `significance.py` (`Significance`, `rank`), `intensity.py`
  (`market_intensity`, `MarketIntensity`), `forecast.py` (`empirical_outlook`,
  `multi_horizon`, `timesfm_outlook`, `SeriesForecast`), `revenue.py`
  (`forward_revenue`, `order_backed`, `Reconciliation`).
- Market data: `upstox.py` (`UpstoxClient`, `QuoteSnapshot`, `UpstoxError`),
  `auth.py` (`get_kite_client`), `instruments.py` (`resolve_token`),
  `history.py` (`SymbolHistory`, `get_history`, `collect_eod`),
  `index_candles.py` (`resolve_and_fetch`, `main`), `coverage.py`
  (`missing_windows`, `record_coverage`).
- Fundamentals and filings: `fundamentals.py` (`Fundamentals`,
  `fetch_one`, `fetch_many`), `screener.py` (`ScreenerError`, `fetch_page`,
  `parse_overview`, `parse_profit_loss`), `fund_derive.py` (`key_ratios`,
  `quarterly_eps`), `factors.py`, `orderval.py` (`parse_order_value`,
  `fetch_filing_text`), `home_events.py` (`Feed`, `classify_response`).
- Constituents and membership: `constituents.py` (`load_constituents`),
  `constituent_membership.py` (`parse_csv`, `load_all`),
  `symbol_sector.py` (`parse_csv`, `write_rows`), `isin_resolver.py`
  (`Resolution`, `resolve_all`), `relative_strength.py` (`assign_tiers`,
  `Plan`).
- Stores: `docstore.py` (`open_db`, `put_filing`, `filings_for`),
  `mongo.py` (`MongoDB`, `open_db`), `graph.py` (`Graph`), `runs.py`
  (`start_run`, `finish_run`, `record_snapshots`, `compute_changes`),
  `retention.py` (`Retention`, `purge_docstore`), `metrics.py` (`record_call`,
  `finalize`).
- LLM: `llm.py` (`LLMConfig`, `extract`, `cross_check`, `health`,
  `parse_json_response`), `conclude.py` (`build_packet`, `packet_hash`,
  `data_gaps`, `unverified_numbers`, `Conclusion`), `modelcheck.py`
  (`measure`, `verdict`, `rank`), `extractcheck.py` (`compare`, `verdict`).
- Outputs: `report.py` (`write_outputs`, `print_summary`), `ath_scan_store.py`
  (`write_scan`, `read_latest_scan`, `scan_row_count`; the candidate table), `workbook.py`
  (`write_workbook`, `summary_rows`), `crosscheck.py` (`compare`, `check_ath`,
  `FallbackChain`), `portfolio.py` (`load_holdings`, `overlay`).
- Secrets: `app_secrets.py` (`put`, `get_value`, `list_meta`),
  `secret_crypto.py` (`encrypt`, `decrypt`, `load_master_key`), `secrets_store.py`
  (`read`, `save`, `mask`, `status`), `secrets_cli.py` (`main`),
  `secret_checks.py` (`check_telegram_token`, `check_upstox_token`),
  `service_client.py` (`fetch_secret`), `expiry_alerts.py` (`check_expiry`,
  `send_telegram`).
- Subpackages: [collect](./collect/EGM.md), [marketdata](./marketdata/EGM.md),
  [pg](./pg/EGM.md).
- Not documented: `strategy/` (holds only `data/index_catalog.csv`, no code).

## Invariants
- `ath.py`, `indicators.py`, `significance.py`, `volatility.py` and
  `relative_strength.py` are pure. They do no network, database or file I/O.
- Secrets are encrypted at rest. `secret_crypto.py` binds each ciphertext to
  its secret name through associated data (`aad_for`), so a value cannot be
  moved between names.
- `conclude.py` stamps each conclusion packet with `packet_hash`. Numbers in a
  conclusion must come from the packet (`unverified_numbers` flags those that
  do not).
- Fetchers are paced. `screener.py` uses a paced fetcher. Upstox uses a rate
  limiter (`_RateLimiter`).
- Parsers return a typed result (`Fundamentals`, `OrderValue`, `Resolution`)
  and raise on malformed input (`BadCsv`, `ParseError`, `InvalidSecret`).

## Side Effects
- Postgres reads and writes (through `pg/`, `marketdata/`, `runs.py`,
  `app_secrets.py`, `constituent_membership.py`, `symbol_sector.py`).
- Document store writes (TinyDB JSON or MongoDB), subject to `retention.py`
  purges. MongoDB containers may be restarted by `mongo.py`'s healing path.
- SQLite caches under `data/` (`history.py`).
- Network calls: Upstox, Kite, NSE (instrument master, filings, constituents),
  screener.in, Telegram (`expiry_alerts.py`), and the local LLM endpoint
  (`llm.py`).
- Neo4j writes (`graph.py`).
- Writes to `output/` (report and workbook files) and to the encrypted
  secrets file and master key file (`secret_crypto.py`, `secrets_store.py`).

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root.
