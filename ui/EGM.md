# ui Blueprint

## System Overview
The legacy Market Scanner UI. A FastAPI server (`app/`) serves an
app shell and a vanilla-JavaScript single-page app
(`app/static/`). It reads run results and configuration through
`app/queries.py` and returns JSON from `app/api.py`. The wireframe mockups in
`wireframes/` are design references, not code. The newer client is `ui-v2/`.

## Local Interface & Invariants
No direct source files at this level. Source is in `app/`.

## Subdirectories & System Boundaries
- [app](./app/EGM.md): FastAPI application, API routes and queries.
- `wireframes/`: HTML design mockups (`index.html`, `strategy.html`). No code
  contract, so not linked.

## Global Invariants
- Queries are read-only except for configuration, secrets and collector-request
  writes.
- Internal secret lookups go through `app/internal_secrets.py`, which compares
  against an expected token before it returns a value.

## Global Side Effects
- Postgres reads, and configuration and secrets writes.
- Serves the static SPA and triggers a manual run through the API.

## System Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root (covers
  `tests/test_ui_api.py`, `tests/test_ui_indicators.py`,
  `tests/test_ui_stocks_page.py`).
