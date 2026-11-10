# static

## Overview
Static assets for the legacy SPA: `index.html` (shell), `styles.css`, and
`app.js` (client-side router and views). The page calls only the JSON API
served by `../api.py`.

## Interface
- `app.js` globals: `router`, `renderView`, `renderHome`, `renderRun`,
  `renderResults`, `renderStocks`, `renderStock`, `renderCost`,
  `renderReport`, `renderConfig`, `renderSetup`, `saveConfig`, `saveSecrets`,
  `runNow`, `setResultsSort`, `setResultsPage`, `applyColFilter`,
  `clearAllColFilters`. Route table is `ROUTES`.
- `index.html`: SPA shell. No script exports.
- `styles.css`: stylesheet. No script exports.

## Invariants
- Every data call goes to a relative `/api/...` path. The page holds no
  database or upstream credentials.
- Column filter state is kept in `COLUMN_FILTERS` and serialised into query
  strings by `filterQueryString`.

## Side Effects
- HTTP requests to the UI API (`fetch`), including `runNow` and `saveSecrets`.

## Verification
- Run: `.venv/Scripts/python.exe -m pytest` from the repository root (covers
  `tests/test_ui_stocks_page.py`).
