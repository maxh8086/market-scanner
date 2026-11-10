# src

## Overview
Fastify application source. `app.ts` assembles the routes from small modules.
Each module exports pure query builders and validators, and the route layer
runs them against the injected `query` function. This keeps SQL and validation
testable without a database.

## Interface
- `app.ts`: `buildApp`, and the `AppDeps`, `KiteDeps`, `LiveDeps`, `QueryFn`
  types.
- `index.ts`: process entry point. Not an importable module.
- `config.ts`: `loadPoolConfig`.
- `secrets.ts`: `readSecret`, `secretsFilePath`.
- `candles.ts`: `validateCandlesRequest`, `buildCandlesQuery`, `shapeCandles`.
- `collectorRefresh.ts`: `registerCollectorRefreshRoute`,
  `isBeforeCloseOnTradingDayIst`, `buildIndexEodRefreshInsert`,
  `buildLastIndexEodRunQuery`.
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
- Subdirectories: [holdings](./holdings/EGM.md), [live](./live/EGM.md).
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
- Reads the secrets file through `readSecret`.
- Live-feed socket and server-sent events (see [live](./live/EGM.md)).

## Verification
- Run: `npm test` in `server/`. Tests sit beside modules here and in
  `server/test/`.
