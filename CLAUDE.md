# ath-scanner

## Code navigation (codebase-memory-mcp)

The repo is indexed as graph project `C-Users-vaibh-Downloads-Projects-Kite-ATH-Scanner`.
The architecture decision record is in the graph: read it with `manage_adr` (mode `get`) before
changing storage, collection, cost metrics or the start/stop scripts.

**Use the graph first. Do not search through files to answer structural questions.**

- Find a function, class or route: `search_graph`. Do not grep or glob for it.
- Who calls X, or what X calls: `trace_path`. Do not grep for the name.
- Read one symbol's source: `get_code_snippet`. Do not open the whole file.
- Structure, entry points, routes, clusters: `get_architecture`. Multi-hop questions: `query_graph`.
- Fall back to grep or a file read only for literals, configs, SQL, PowerShell, Docker and other
  non-code files, or when `check_index_coverage` says a file is stale or partially parsed
  (`db/migrations/001_core.sql`, `run_migration.ps1`, `scripts/gpu_sample.ps1`).
- Run `check_index_coverage` on the files you rely on. Re-run `index_repository` (mode `full`) after
  large edits. `.env*`, `.venv` and `data/` are not indexed.

## Testing

- Offline: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q` (forces sqlite + tinydb).
- Offline tests do not exercise Postgres/Mongo types (e.g. `Decimal` from NUMERIC columns); the live tests
  need the infra env from `../Shared-Market-Research-Infra/secrets/ath_scanner.env` with `INFRA_LOCAL=1`.
