# api

## Overview
Typed HTTP clients for the `server/` API. Each module mirrors one server route,
and its types are kept in step with the matching server module.

## Interface
- `candles.ts`: `fetchCandles`, `Candle`, `CandlesResponse`, `CandlesError`.
  Route: `GET /api/stocks/:symbol/candles`.
- `collectorRefresh.ts`: `requestIndexEodRefresh`, `fetchIndexEodStatus`,
  `IndexEodRefreshResult`, `IndexEodStatus`, `CollectorRefreshError`. Routes:
  `POST /api/collector/index-eod/refresh` and its status route.
- `filterOptions.ts`: `fetchFilterOptions`, `FilterOptions`,
  `FilterOptionsError`. Route: `GET /api/runs/:runId/filter-options`.
- `holdings.ts`: `fetchHoldings`, `Holding`, `HoldingsError`. Route:
  `GET /api/holdings`.
- `latestRun.ts`: `fetchLatestRun`, `LatestRun`, `LatestRunError`. Route:
  `GET /api/runs/latest`.
- `presets.ts`: `listPresets`, `createPreset`, `deletePreset`, `Preset`,
  `PresetsError`. Route: `/api/presets`.
- `results.ts`: `fetchResults`, `buildResultsQueryString`, `Row`, `ResultsPage`,
  `ResultsQuery`, `SortOrder`, `ResultsError`. Route:
  `GET /api/runs/:runId/results`.
- `sectorSummary.ts`: `fetchSectorSummary`, `SECTOR_PERIODS`, `SectorPeriod`,
  `SectorSummaryRow`, `SectorSummaryError`. Route:
  `GET /api/runs/:runId/sector-summary`.
- Tests: `*.test.ts` beside each module (not part of the interface).

## Invariants
- Every error is a typed error class, so callers can tell a failed request
  from an unexpected payload.
- Query strings are built only through `buildResultsQueryString` and
  `URLSearchParams`, never by string concatenation of user input.
- Response shapes match the server's shape functions. A server change must
  update the matching client file.

## Side Effects
- One HTTP request per call. `requestIndexEodRefresh` and `createPreset` /
  `deletePreset` change server state.

## Verification
- Run: `npm test` in `ui-v2/` (covers the `*.test.ts` files in this folder).
