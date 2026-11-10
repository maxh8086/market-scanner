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
  `Fundamentals`, `AthScan`, `IndexEOD`). Each `run(params)` returns a status.
- `__init__.py` re-exports nothing; import from the module you need.

## Invariants
- A source runs only if `scheduler.due_sources` marks it due. Manual requests
  go through `claim_requests`, so one request is claimed by one runner.
- `is_running` prevents a second run of the same source while one is active.
- `update_setting` and `request_run` validate parameter keys
  (`_valid_param_keys`) before writing.
- Each run is recorded through `start_run` and `finish_run`, and linked to the
  request that caused it.

## Side Effects
- Postgres reads and writes: collector settings, collector sources, run rows,
  request claims.
- The first-run watcher writes a marker file that stops it from re-running.
- Network calls made by the sources (market data, filings, screener.in).

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root (covers
  `tests/test_collect_*.py` and `tests/test_first_run_watcher.py`).
