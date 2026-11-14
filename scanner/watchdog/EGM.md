# watchdog

## Overview
The host watchdog. A process on the Windows host (not a container) that asks the
server which collector sources are due, starts them, stops collector runs that
overrun their limit, and brings the ui, server and database back up when their
health checks fail. It connects to no database and imports no psycopg.

## Interface
- `api_client.py`: `fetch_due` (GET `/internal/due`) and `finish_killed`
  (POST `/internal/due/finish`). Never raises; errors come back as a kind.
- `config.py`: `load_config`, `read_token`, `load_runtime`, `RuntimeConfig.max_runtime_s`.
- `docker_runner.py`: `DockerRunner`. Command builders and a thin executor. Only
  `collector-*` containers can be stopped.
- `health.py`: `check_http`, `RestartPolicy`, `Backoff`.
- `main.py`: `Watchdog` (`poll_once`, `enforce_max_runtime`, `health_once`,
  `run_forever`) and `main`. `__main__.py` calls `main`.

## Invariants
- A source is started only when the server lists it as due and it is not already
  running. The first successful pass is sequential, later passes start in parallel.
- A kill is attempted once per container instance (name plus start time).
- ui and server restart after 3 failed checks, spaced by 1, 5, 15, then 15 minutes.
  scanner-postgres is brought up first. Only `compose up` is used, never stop.
- The token goes only into the Authorization header and is redacted from logs.

## Side Effects
- HTTP to the server API (`WATCHDOG_API_BASE_URL`) and to the ui and server health URLs.
- Docker commands: `ps`, `inspect`, `rm -f`, `stop` (collector only), `compose run`
  and `compose up -d` (scanner-postgres, ui, server).
- Writes `logs/watchdog.log` (rotating, 5 MB, 5 backups).
