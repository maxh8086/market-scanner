# src

## Overview
Fastify application source. `app.ts` assembles the routes from small modules.
Each module exports pure query builders and validators, and the route layer
runs them against the injected `query` function. This keeps SQL and validation
testable without a database.

## Interface
- `app.ts`: `buildApp`, and the `AppDeps`, `BrokerAppDeps`, `LiveDeps`,
  `QueryFn` types. Broker routes register only when both `broker` and
  `portfolioTx` are passed.
- `index.ts`: process entry point. Not an importable module.
- `config.ts`: `loadPoolConfig`.
- `secretsClient.ts`: `createSecretsClient` (`get`, `invalidate`). `index.ts`
  uses it to fetch app secrets from the ui internal secrets endpoint.
  `secrets.ts` (`readSecret`) is no longer used by `index.ts`. `invalidate`
  drops a cached value; a fetch that was in flight during the invalidate does
  not write its stale result back.
- `uiClient.ts`: `createUiClient`. Bearer-authorised calls to the ui internal
  broker API. Transport failures come back as status 0.
- `portfolioTx.ts`: `makePortfolioTx`, `PortfolioTx`. One pooled-client
  transaction for the snapshot writes, same shape as `eventsTx`.
- `broker/`: broker login routes (`brokerRoutes.ts`) for the broker set
  `kite|upstox`, credential names (`names.ts`, `credentials.ts`) and stored
  portfolio snapshots (`portfolioStore.ts`). It has no EGM.md of its own; this
  file covers it. `isBrokerId` is the one place the broker set is checked.
- `candles.ts`: `validateCandlesRequest`, `buildCandlesQuery`, `shapeCandles`.
- `collectorRefresh.ts`: `registerCollectorRefreshRoute`,
  `isBeforeCloseOnTradingDayIst`, `buildIndexEodRefreshInsert`,
  `buildLastIndexEodRunQuery`.
- `collectorDue.ts`: `computeDue` (pure due rules for the watchdog poll),
  `buildDueQueries`, `mapDueRows`, `parseServicesFile`, `isConnectionError`.
- `collectorDueRoute.ts`: `registerCollectorDueRoute` (GET `/internal/due`,
  role `collector_watchdog`; returns `getLastDuePollAt`).
- `filterOptions.ts`: `buildFilterOptionsQuery`, `shapeFilterOptions`.
- `homeEventsBatch.ts`: `validateBatch`, `buildInsert`.
- `indexEod.ts`: `buildIndexEodQuery`, `shapeIndexEod`.
- `presets.ts`: `validatePresetInput`, `isPresetId`, `buildListPresetsQuery`,
  `buildInsertPresetQuery`, `buildDeletePresetQuery`.
- `recentCloses.ts`: `validateRecentClosesRequest`, `buildRecentClosesQuery`,
  `shapeRecentCloses`.
- `results.ts`: `normalizePaging`, `buildResultsQuery`, `buildCountQuery`,
  `buildRunLookupQuery`, `buildLatestRunQuery`, `formatRunDate`.
- `sectorSummary.ts`: `validateSectorPeriod`, `buildSectorSummaryQuery`,
  `shapeSectorSummary`.
- Subdirectories: [holdings](./holdings/EGM.md), [live](./live/EGM.md),
  `broker/` (no EGM.md of its own; see Interface).
- Test files (`*.test.ts`) sit beside their modules and are not part of the
  interface.

## Invariants
- Page size and similar inputs are clamped to documented bounds
  (`MAX_PER_PAGE`, `MAX_LIMIT`, `MAX_CLOSES_SYMBOLS`) before a query is built.
- Date inputs are checked as ISO dates (`isIsoDate`) before they reach SQL.
- Preset names and filter payloads are length-checked (`NAME_MIN`, `NAME_MAX`,
  `MAX_FILTER_KEYS`, `MAX_FILTER_STRING`).
- `collectorRefresh.ts` owns the post-market rule: a manual EOD refresh is
  refused before market close on a trading day.

## Side Effects
- Postgres reads through the injected `query` function. `presets.ts` and
  `collectorRefresh.ts` also write (preset insert and delete, index EOD refresh
  insert).
- App secrets are fetched over HTTP from the ui internal secrets endpoint by
  `secretsClient.ts` (`index.ts` wiring), not read from a file.
- Broker login goes through the ui internal broker API (`uiClient.ts`): login
  URL, code exchange and status. The browser never receives a broker token or
  API key. The Kite and Upstox callbacks redirect back to the UI without them,
  and a callback with an Upstox `error` or a missing code or state calls nothing.
- Upstox sync needs only the stored access token. The app's client_id and
  secret stay in the ui.
- Holdings: `GET /api/holdings?broker=` (default `kite`) reads the stored
  snapshot only. Only `POST /api/holdings/sync` calls a broker (`broker`
  `kite|upstox`, default `kite`), and it writes Postgres
  (`portfolio_sync` and `portfolio_holding`) in one transaction through
  `portfolioTx.ts`. A failed sync writes nothing.
- Live-feed socket and server-sent events (see [live](./live/EGM.md)).

## Verification
- Run: `npm test` in `server/`. Tests sit beside modules here and in
  `server/test/`.
