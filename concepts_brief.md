# Redesign the Market Scanner UI

* **Author:** Vaibhav Pavtekar
* **Date:** 2026-11-09
* **Status:** Goldfish review done (BRAINSTORM mode). Not approved. Open questions below need your answers before design starts.

## Overview

Concept under review: a dense, desktop-first screen for Indian equities (NSE/BSE, INR, IST). Each stock shows its scanner data beside it. The app gives no buy, sell or hold verdicts. Current filters, scan logic, API contracts and routes stay unchanged. The old UI keeps running until you approve the switch.

Stack: Vite + React + TypeScript. Data grids and tables: TanStack Table (virtualized rows, sorting, filtering, column pinning). Charts: TradingView Lightweight Charts, or Chart.js as the alternative, for canvas-based financial rendering.

Tailwind/shadcn/ui: not yet confirmed by owner.

## Analysis

Six lenses reviewed the concept: design, codebase details, zoom-out (scope), comprehension, implementation readiness and structure. The synthesis was done by Haiku. Sonnet should re-check it before it is treated as final.

The concept and the on-disk brief (`docs/designs/ui-redesign-brief.md`, 2026-11-08) describe different scope. The concept covers the scanner table and stock view. The brief also adds portfolio (Zerodha, Upstox, CSV), Telegram alerts, policy RSS with LLM classification, events, fundamentals, concall summaries and a Home feed. Settle scope first.

### Blockers

1. **No-verdict rule conflicts with approved decisions.** `docs/wireframe-review-2026-11-01.md` approved BUY, HOLD, EXIT and REJECT, plus a Trim, Add and Hold action set. `ui/wireframes/strategy.html` styles those labels. The brief gives holdings buy, add, hold, trim, sell or rebalance labels. The stance values CONSTRUCTIVE, MIXED and CAUTIOUS (`scanner/conclude.py`, `db/migrations/001_core.sql`) are part of the stance filter. Needed: a written decision on which rule governs, a banned-word list, and neutral wording.
2. **Scope is unbounded.** The brief adds at least eight subsystems. Suggested v1: scanner table and stock page on existing endpoints, delayed or end-of-day data, five states, no chart, no websocket, no portfolio.
3. **No live data path exists.** The app is REST only, with no WebSocket, SSE, polling or setInterval. Stored data is end-of-day from Upstox REST. The live, reconnecting and pre-open states cannot be built or tested on real data. Broker licence terms for sharing with others are unchecked. Upstox supports live market data, but live data is not required for v1. WebSocket on Fastify is therefore deferred until live tickers are scoped. Broker licence terms for sharing data with others are still unchecked.
4. **Backend and stack:** resolved by the owner. Backend is Node.js + TypeScript + Fastify, replacing FastAPI. Frontend is Vite + React + TypeScript, built to static files and served by Fastify. Fastify handles WebSocket connections for live stock tickers. Tailwind/shadcn/ui: not yet confirmed by owner.
5. **Chart library:** resolved by the owner. TradingView Lightweight Charts v5 only. KLineChart is rejected and must not appear in new code or designs. Chart.js is the alternative only if Lightweight Charts cannot meet a need.
6. **Baseline UI is ambiguous.** There is a root `ui/app/` (FastAPI, port 8080), a nested `app/` git repo, and a third copy at `ui/wireframes/strategy.html`. A OneDrive path was named but not checked. No screenshots exist.
7. **Security exposure.** `ui/app/main.py` binds 0.0.0.0:8080 with no auth. `README.md` says "loopback only, no login", which contradicts the code. Config and secrets write endpoints have no auth (not re-verified). The UI builds `innerHTML` from `location.hash`. Broker and Telegram tokens sit on the same server. Settle auth and bind address before any portfolio, broker or socket work.
8. **Switch mechanism is undefined.** The catch-all route at `ui/app/main.py:37` would shadow or be shadowed by a second build. Missing: hash-route compatibility, port or prefix, flag, rollback command, approver.
9. **Users are unknown.** Self, family or traders changes density, auth, holdings privacy and licence position. Do not start design until this is answered.

### Major

10. **Virtualization conflicts with API caps.** Results cap `per_page` at 100. `/api/stocks` caps at 200. No all-rows endpoint exists. The 5,000-row figure is unsourced; the wireframe mentions 750 companies. TanStack Table does not virtualize rows.
11. **Errors return HTTP 200.** Error bodies look like "no results", so the UI cannot tell them apart.
12. **State definitions are missing.** Pre-open, market closed, stale and reconnecting have no triggers, thresholds, holiday calendar or session times. The "data as of" stamp uses the browser clock, so stale data looks fresh.
13. **Timezone is inconsistent.** `api.py` line 419 uses naive server-local time. The UI uses browser locale. Docker containers often default to UTC.
14. **Row key is undefined.** A stock can list on NSE and BSE and appear in several runs.
15. **"Scanner data" and "beside it" are undefined.** No field list, column set, default sort or minimum width exists.
16. **Filter parity is unclear.** The API has bucket and stance filters; the UI has no bucket control. `/api/stocks` returns only symbol, bucket, stance score and run date.
17. **Layout decision is not recorded.** The brief says Option D awaits your confirmation; the directions doc recommends C. Option D makes Home the scan table, which conflicts with the brief's Home requirement.
18. **Accessibility and format rules are missing.** The brief requires WCAG AA, never colour alone for gain and loss, reduced motion, tabular numerals, lakh and crore grouping. The existing UI fails several of these.
19. **Rollback is missing.** Migrations 025 and 026 are untracked. `fundamentals-tables.md` proposes deleting old Mongo documents.
20. **Phases are referenced but not defined** in the brief.
21. **Phase 1 audit status contradicts the concept.** `docs/designs/ui-redesign-audit.md` exists and is untracked. The brief says Phase 2 is complete. Decide which governs.
22. **Fundamentals source rule conflicts.** `directions.md` says layout and fields only, no scraping. `fundamentals-tables.md` uses screener.in row labels verbatim.
23. **Three design systems conflict.** `ui/DESIGN.md`, the approved wireframe and the brief's shadcn tokens differ.
24. **No observability.** One `logger.exception`, no metrics or request IDs.
25. **Query load.** Each request opens a new connection with no pool. `get_results` is `async def` but calls synchronous code. Cache by run ID and query string; completed runs do not change.

### Minor

26. Dark and light mode doubles token and test work. Define the token set once.
27. Named skills are not installed; their rules must be written into the spec.
28. TanStack Query is in the brief but not the concept. Decide whether it stays.
29. "Calm, not fear" is not actionable. Turn it into rules, such as no full-row red or green fills and a visible "data as of" on every screen.
30. The brief uses phase numbers and "Option D" without definitions.
31. Existing tests (`tests/test_ui_api.py`, `test_ui_stocks_page.py`, `test_results_sort.py`, `test_relative_strength_ui.py`) could serve as API contract checks. Their contents were not read.
32. The root API has no published contract. `app/docs/contract/openapi.yaml` exists in the nested repo; its coverage is unchecked.

## Goals vs. Non-Goals

* **In-Scope Goals (proposed v1):** Scanner table and stock page on existing endpoints. Delayed or end-of-day data. Five states. No chart, no websocket, no portfolio.
* **Out-of-Scope Non-Goals:** Portfolio, broker feeds, Telegram alerts, policy RSS, concall summaries, Home feed, websocket. Pending your decision.

## Key Decisions & Staging for Next Steps

Answers received (2026-11-09):

1. **Verdicts:** the approved 2026-11-01 labels (BUY, HOLD, EXIT, REJECT) stay as they are. The user's reply, "any one of them, but not all", is still open. Clarify whether one label per stock is allowed, or only on holdings.
2. **Scope:** the full 2026-11-08 brief is in scope as a redesign requirement. Portfolio, Telegram, policy RSS, concall summaries and Home feed are all included. Ordering is still to be set.
3. **Live data:** agreed. No live path. Design uses REST and end-of-day data. Live and reconnecting states are out of v1.
4. **Security:** agreed that bind address and auth must be settled before any broker or socket work. Preferred secret store: Docker secret. Docker Swarm is not present (see the earlier decision record), so the option is Compose file-based secrets, which need no Swarm. Migration not started.
5. **Chart:** lightweight-charts v5 (TradingView, Apache 2.0). KLineChart is a separate open-source candlestick library and is not chosen.

Answers received (2026-11-09, round 2):

- **Verdicts:** one label per stock. A stock may show one of BUY, HOLD, EXIT or REJECT. No view shows all four together for the same stock.
- **Users:** me and family, on one home network. Needs login and per-user holdings privacy. Not reachable outside the home network.
- **Stack:** chosen by the owner's criteria (fast, low resource use, wide UI design choice). Confirmed by owner: Backend is Node.js + TypeScript + Fastify, replacing FastAPI. Frontend is Vite + React + TypeScript, built to static files and served by Fastify. Fastify handles WebSocket connections for live stock tickers. Data grids and tables: TanStack Table (virtualized rows, sorting, filtering, column pinning). Charts: TradingView Lightweight Charts, or Chart.js as the alternative, for canvas-based financial rendering. Tailwind/shadcn/ui: not yet confirmed by owner.
- **Secrets:** Docker secret. Swarm is not present, so this means Compose file-based secrets. Migration needs docker-compose.yml to change, which earlier notes said to hold until the alert service exists. Owner to confirm.

Answers received (2026-11-09, round 3):

- **Docker-compose hold:** lifted by owner. Compose file-based secrets may be wired now.
- **Ordering:** data collection first, then backend, then API, then UI.
- **Baseline and switch:** the current UI is the baseline. The switch target is the final UI revamp, which replaces it once approved.
- **Migrations 025 and 026:** in scope as the first step of data collection. Application is pending a separate explicit go, because `start.ps1` applies every pending migration on its next run.

Collector note (2026-11-09):

- **Cause:** `collector_settings` has rows for `index_eod`, `exchange_results` and `gov_feeds`. `scanner/collect/sources.py` defines none of them (it defines announcements, ath_scan, candles_eod, corporate_actions, filings, fundamentals). The serve loop tried to run the two scheduled rows, failed with "unknown source", and never recorded a run. So they were due, and failed, every minute from at least 20:30 UTC on 8 Nov.
- **Fix in code:** `collect.split_registered` skips rows with no collector and logs each name once. Tests in `tests/test_collect_missing_source.py`. Running collector still has the old code until it is rebuilt and restarted.
- **Done (2026-11-09):** the three orphan `collector_settings` rows were deleted, with their 12 `collector_runs` rows and 1 `collector_requests` row (approved by you). Backup of the settings is in the session scratchpad.

Completed (2026-11-09, round 4):

- **Sector load:** run for real. 751 symbols in 22 NSE industries upserted into `symbol_sector` with `as_of` 2026-11-09. The first attempt stamped 2026-11-08 because the container clock is UTC. The loader now uses the IST date (`today_ist`), and the load was rerun to correct it. The `sub_sector` columns were not touched.
- **Face value:** `fund_derive.key_ratios` now outputs `face_value` from the #top-ratios "Face Value" row (`face_value_from_overview`). Market cap and book value use it. A missing or zero face value leaves those two values empty. Tests: `tests/test_fund_derive.py`, plus IST tests in `tests/test_symbol_sector.py`.
- **Chart library:** KLineChart replaced with TradingView lightweight-charts v5 in `ui/wireframes/strategy.html` (4 places) and `app/docs/strategy/handoff_ui_rollout.md` (3 places).
- **UI stack:** Vite + React + TypeScript (owner confirmed). Tailwind/shadcn/ui: not yet confirmed by owner.

Still open:

- Secrets (decided 2026-11-09): deferred to the end of development. Until then, `.env` stays the single secrets file. Compose file secrets are not wired. The Swarm route needs `docker stack deploy`, because Compose cannot read Swarm secrets (tested locally).
- Migrations 025, 026 and 027 (fundamentals tables, empty): applied on 2026-11-09. The scanner image was rebuilt so 027 was included.

## Verification notes

- Confirmed in code by reviewers: no WebSocket or polling; end-of-day data only; `per_page` cap of 100; `/api/stocks` cap of 200; bind to 0.0.0.0; the stamp uses the browser clock; errors return HTTP 200.
- Not re-verified: innerHTML, dark-token duplication, keyboard access, the OneDrive wireframe, and the cost of the announcement-coverage query.
- The 750 and 5,000 row figures are unresolved. No reviewer queried the database.
