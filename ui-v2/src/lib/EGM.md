# lib

## Overview
Pure formatting and market-session helpers used across the UI. No React, no
network, no storage.

## Interface
- `format.ts`: `formatInr`, `formatPercent`, `formatPercentWithArrow`,
  `formatChange`, `formatCrore`, `formatIstDateTime`. Indian digit grouping is
  done here.
- `marketSession.ts`: `getMarketSession`, `runAgeDays`, `isRunStale`,
  `MarketSession`, `MarketStatus`, `EXCHANGE_HOLIDAYS_2026`.
- Tests: `format.test.ts`, `marketSession.test.ts`.

## Invariants
- Every function is pure and deterministic for a given input and clock value.
- Indian grouping follows the lakh and crore pattern (for example 12345678 ->
  1,23,45,678).
- `EXCHANGE_HOLIDAYS_2026` is the holiday list used for session status. It must
  be updated each year.

## Side Effects
- None.

## Verification
- Run: `npm test` in `ui-v2/` (covers `format.test.ts`, `marketSession.test.ts`).
