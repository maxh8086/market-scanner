# collect

## Overview
The collector. It decides which data sources are due, claims run requests from
the database, runs each source, and records the run. It also holds the
first-run watcher, which starts the first ATH scan once broker API details
exist.

## Interface
- `first_run.py`: `marker_path`, `decide`, `tick`. Watches for the first run.
- `scheduler.py`: `due_sources`, `claim_requests`, `start_run`, `finish_run`,
  `link_request_to_run`, `get_settings`, `get_last_runs`, `is_running`.
- `settings.py`: `get_settings`, `ensure_sources`, `update_setting`,
  `request_run`, `list_runs`.
- `sources.py`: `Source` base class and one class per source type
  (`CandlesEOD`, `Announcements`, `CorporateActions`, `Filings`,
  `Fundamentals`, `AthScan`, `IndexEOD`, `CompanyReference`, `HomeFilings`).
  Each `run(params)` returns a status.
- `HomeFilings` (`home_filings`, `events = True`): calls
  `scanner.home_events.run_cycle` and returns `status` ("ok", "failed" or
  "skipped"), `fetched`, `new`, `from`/`to` as dates, and `message`. `plan` is
  offline. Its failure messages are `token_unavailable`,
  `index_unavailable: <ExceptionClass>` and `<ExceptionClass>: <text>`, and never
  hold the token or the token path.
- `__init__.py` re-exports nothing; import from the module you need.

## Invariants
- A source runs only if `scheduler.due_sources` marks it due. Manual requests
  go through `claim_requests`, so one request is claimed by one runner.
- `is_running` prevents a second run of the same source while one is active.
- `update_setting` and `request_run` validate parameter keys
  (`_valid_param_keys`) before writing.
- Each run is recorded through `start_run` and `finish_run`, and linked to the
  request that caused it.
- When a source's `run` result has a `status` of `failed` or `skipped`,
  `_run_locked` records that status (a skip uses the result message as its
  reason). Other results are recorded as `ok`.
- An events source (`events = True`) is skipped with `api_unavailable` when the
  API health check fails.

## Side Effects
- Postgres reads and writes: collector settings, collector sources, run rows,
  request claims.
- The first-run watcher writes a marker file that stops it from re-running.
- Network calls made by the sources (market data, filings, screener.in).

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root (covers
  `tests/test_collect_*.py` and `tests/test_first_run_watcher.py`).
