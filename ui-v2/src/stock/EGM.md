# stock

## Overview
The per-stock page, opened from a results row or a watchlist entry.

## Interface
- `StockPage.tsx`: `StockPage`, `StockPageProps`.
- `StockPage.test.tsx`: test suite (not part of the interface).

## Invariants
- The page takes its symbol through props (`StockPageProps`).
- Candle data comes through `api/candles.ts`, never a direct network call.

## Side Effects
- HTTP calls for candles through `api/candles.ts`.
- Reads computed CSS custom properties from the document root
  (`getComputedStyle`).

## Verification
- Run: `npm test` in `ui-v2/` (covers `StockPage.test.tsx`).
