# UI redesign: Phase 1 audit (read-only)

Date: 2026-11-08. Scope: the live UI in `ui/app/` (FastAPI on port 8080, vanilla JavaScript) and the reference wireframe in `C:\Users\vaibh\OneDrive\Desktop\ui`. No code was changed.

## 1. Screens (live UI, `ui/app/static/app.js`)

| Route | Screen | Data source |
|---|---|---|
| `#/` | Home: latest run summary, cards to other screens | `/api/runs?limit=1` |
| `#/run` and `#/run/{date}` | Run dashboard: run stats | `/api/runs/{id}` |
| `#/results/{date}` | Results table with paging, sort and column filters | `/api/runs/{id}/results` |
| `#/stocks` | Stock list (one row per symbol, search by `q`) | `/api/stocks` |
| `#/stock/{symbol}` | Stock page: snapshot, timeline, relative strength, tabs | `/api/stocks/{symbol}` |
| `#/report` | Report dashboard | `/api/report` |
| `#/cost` and `#/cost/{run}` | Cost center (measured tokens, time, GPU energy) | `/api/cost`, `/api/cost/{id}` |
| `#/config` | Master configuration (per-source schedule, Run now) | `/api/config`, `/api/config/{source}` |
| `#/setup` | API keys | `/api/secrets` |

Navigation (`ui/app/static/index.html`, lines 29-35): Home, Latest run, Stocks, Report dashboard, Cost center, Master configuration, API keys.

## 2. Filters, columns and data flow

- Results columns are defined in `RESULT_COLUMNS` (`app.js:265`). Each column can carry a filter popover (`COLUMN_FILTERS`). Sort is set by clicking a header.
- Paging is server-side: 20 rows per page (`app.js:450`). Sort, filter and page are sent as query parameters on every change.
- The Stocks list endpoint caps `limit` at 200 (`ui/app/api.py:584`).
- Each route runs one or more `fetch()` calls, then rebuilds the view with `innerHTML` (5 places in `app.js`).
- No polling, no `setInterval`, no WebSocket, no SSE. Data is fetched once per navigation.
- Stock chart: no charting library is loaded (`index.html` loads only `app.js`, `styles.css` and Google Fonts). The page notes "Candles are end-of-day prices only" (`app.js:813`).
- Styling: `styles.css` defines colour tokens as CSS variables, and has a dark-mode block and a `prefers-reduced-motion` rule.

## 3. Top 5 usability and performance problems

1. **No live data path.** Nothing refreshes after the page loads, and there is no websocket or polling code. Live ticks, a "stale data" state and a "reconnecting" state cannot be built on the current data layer. A new provider and transport are needed first.
2. **Large lists are paged, not virtualized.** The results table shows 20 rows per page, so scanning 5,000 rows means about 250 page loads with a server round trip for each. The Stocks list stops at 200 rows per request. Row virtualization, sticky first column and resizable columns all need a table component that does not exist yet.
3. **Every view is rebuilt from HTML strings.** The five `innerHTML` writes replace whole sections. No component keeps its own state, so column hide and resize, saved scan presets and a persistent watchlist panel would each need a rewrite of the affected view.
4. **No real chart.** Price charts have no timeframe switch, no volume pane, no log scale, no crosshair legend and no indicator overlays in the browser. The backend already has `ui/app/indicators.py`, but it is not wired to any chart. The end-of-day-only note means the 1m, 5m and 15m timeframes in the brief have no data source yet.
5. **Status and gain/loss signalling is incomplete.** Gain and loss use `up` and `down` classes (`app.js:581`), and the sort arrows are the only ▲ ▼ marks found. The audit did not confirm that every gain or loss cell shows a sign or arrow, so the "never colour alone" rule is not yet met. The market-closed, pre-open, stale, no-results and reconnecting states do not exist. Only the latest run date tells the user how old the data is.

## 4. Reference wireframe (`C:\Users\vaibh\OneDrive\Desktop\ui`)

- It is the source form of the wireframe: `wireframes/src/*.js` and `*.css`, built into `wireframes/strategy.html` by `build.py`. It has more screens than the live app: Holdings review, Position sizing, For review, and the Order book and Sector tabs on the stock page.
- It has no real data (mock data in `data.js`). Its charts are drawn placeholders.
- `DESIGN.md` there names one design system: slate canvas, emerald gain, rose loss, indigo accent, tabular figures. It is a starting point for Phase 4, not a decided design.

## 5. Skills named in the brief that are not installed here

These were not in the available skill list when this audit ran:
- `financial-ui-patterns` / `financial-ui-suite`
- `financial-ui-styles`
- `shadcn/ui` skill
- `frontend-design` and `design-register-commit`
- `Interface Design`
- Vercel `agent-skills` (react-best-practices, web-design-guidelines)
- `awesome-design-md` (the DESIGN.md references)

`ui-ux-pro-max` is installed. The phases that rely on the missing skills will need the rules written into the spec, or the skills installed first.

## 6. Open assumptions

- The brief's "existing UI" is `ui/app/` (the live app). The OneDrive folder is treated as the reference wireframe only.
- The brief's stack (Next.js or Vite, React, TypeScript, Tailwind v4, shadcn/ui, TanStack) is a change of stack, not a restyle. The current app has no build step. A migration would run the old UI side by side until the switch is approved, as the brief requires.
- Data is end-of-day only today. Intraday ticks depend on a data source that the project does not have.

## 7. Live code review (read-only, no fixes applied)

Files read: `ui/app/main.py`, `ui/app/api.py`, `ui/app/static/index.html`, `ui/app/static/app.js` (all), `ui/app/static/styles.css`, `ui/app/queries.py`, `ui/app/indicators.py`.

### Security (highest first)

1. **Write endpoints have no authentication, and the server listens on all interfaces.** `main.py:48-53` binds `0.0.0.0:8080`. `PUT /api/config/{source}`, `POST /api/config/{source}/run` and `PUT /api/secrets` are open to anyone on the network. The secrets PUT can overwrite broker keys.
2. **DOM XSS through `innerHTML`.** The breadcrumb builds HTML from `location.hash` (`app.js:60-63`). The router error view writes `Error: ${err.message}` without escaping. A crafted link can run script in the user's browser, and that script can then call the unauthenticated write endpoints in item 1.
3. **Unescaped values in HTML and inline handlers.** `renderReport` puts `a.symbol` into an `href` (`app.js:716`). `renderConfig` puts `s.source` and `s.cron` into `onclick` strings and `value` (`app.js:763-782`). The values come from the database today, so the risk is low, but they are not escaped.

### Correctness and data trust

4. **"Stocks OK" overstates coverage.** `ANNOUNCEMENT_COVERAGE` (`queries.py:300-323`) marks a stock OK if it has any announcement row at all. The page text (`app.js:804`) says coverage must run from `max(listing date, today - 3 years)` to today. The query checks neither bound, so the number on the Master configuration page does not match what it claims.
5. **Saving a source wipes its params.** `saveConfig` always sends `params: {}` (`app.js:848`). Any stored parameter for that source is silently replaced.
6. **The "data as of" stamp shows the browser's clock.** `updateStamp` (`app.js:819-823`) writes the run date followed by `new Date()`, the current time. A stale run looks fresh. The stamp is also hidden below 1180px (`styles.css:51`) and on phones (`styles.css:195`), so the user cannot see data age on those screens.
7. **Errors look like empty data.** `renderCost`, `renderReport` and `renderConfig` call `res.json()` without checking `res.ok`. The home screen shows "No runs yet" when the API fails. Error and empty states are not separate.
8. **RSI returns 100 for a flat series.** In `indicators.py:50-51`, when both average gain and average loss are 0, the code returns 100. A flat price series should be neutral (50) or `None`.
9. **Secret fields may be cleared on save.** `saveSecrets` sends every `input[data-key]`, including secret fields that show "Saved" with an empty value. Whether an empty value keeps or clears the stored key depends on `put_secrets` in `api.py`. Not verified; check before any change.
10. **Possible dead SQL.** `RESULTS_QUERY` in `queries.py:163-183` looks like a copy of the query built inline in `api.py:228`. If the constant is unused, it will drift. Confirm with a search before removing it.

### Performance

11. **Sync database calls inside async routes.** Several routes in `api.py` call the database synchronously, which blocks the event loop while a query runs. Use `def` routes or a thread pool.
12. **`ANNOUNCEMENT_COVERAGE` scans all announcements on every load** with a `GROUP BY` over the full table and a `DISTINCT` subquery. The cost grows with the table. It needs a cache or a precomputed table.
13. **Paged results, not virtualized.** 20 rows per page (`app.js:450`), capped at 100 by the API. Scanning 5,000 rows means many round trips.

### Accessibility and UI

14. **Table rows cannot be reached by keyboard.** Rows use `tbody tr.link` with a click handler (`styles.css:101`) but no `tabindex`, no Enter or Space handler, and no link inside the row.
15. **Gain and loss use colour as well as position.** `.up` and `.down` set colour only (`styles.css:92`). The brief requires a sign or arrow in addition to colour.
16. **Sticky table header does nothing.** `th` is `position:sticky; top:0` (`styles.css:97`), but `.tbl-wrap` only sets `overflow-x:auto` with no `max-height`, so there is no vertical scroll container for the header to stick to.
17. **Dark-mode tokens are written twice** (`styles.css:11-28`). Any token change must be made in two places.
18. **Hard-coded shadow colour** in `.col-filter-pop` (`styles.css:131`). It bypasses the token system.

### Not reviewed yet

- The API functions for secrets and config writes in `api.py`, which item 9 depends on.
- `api.py` routes outside the results and config paths.
