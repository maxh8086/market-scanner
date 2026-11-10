# table

## Overview
The screener results table: column definitions, column chooser, per-column
filters, column resizing, sparklines and the recent-closes lookup.

## Interface
- `ScreenerTable.tsx`: `ScreenerTable`, `ScreenerTableProps`. Virtualised
  table built on TanStack Table and Virtual.
- `ColumnChooser.tsx`: `ColumnChooser`, `ChooserColumn`, `ColumnChooserProps`.
- `ColumnFilter.tsx`: `ColumnFilter`, `ColumnFilterKind`, `ColumnFilterProps`.
- `columnWidths.tsx`: `useColumnWidths`, `ColumnResizeHandle`,
  `MIN_COLUMN_WIDTH`, `ColumnWidthsState`.
- `Sparkline.tsx`: `Sparkline`, `sparklinePoints`, `SparklineTrend`,
  `SPARKLINE_WIDTH`, `SPARKLINE_HEIGHT`.
- `recentCloses.ts`: `fetchRecentCloses`, `RecentCloses`, `RecentClosesError`,
  `RECENT_CLOSES_LIMIT`, `RECENT_CLOSES_BATCH_SIZE`.
- `reducedMotion.ts`: `usePrefersReducedMotion`.
- Tests: `ScreenerTable.test.tsx`, `ScreenerTable.filters.test.tsx`,
  `ScreenerTable.perf.test.tsx`, `ColumnFilter.test.tsx`,
  `Sparkline.test.tsx`.

## Invariants
- Sparklines are fixed-size (`SPARKLINE_WIDTH`, `SPARKLINE_HEIGHT`), so a
  column never changes width as data arrives.
- Column width never drops below `MIN_COLUMN_WIDTH`.
- Recent-closes requests go out in batches of `RECENT_CLOSES_BATCH_SIZE`, with
  at most `RECENT_CLOSES_LIMIT` symbols in total.
- Animation respects `usePrefersReducedMotion`.

## Side Effects
- HTTP calls for recent closes (`fetchRecentCloses`).
- No browser storage. Column widths are not persisted between visits.

## Verification
- Run: `npm test` in `ui-v2/` (covers the `*.test.tsx` and `*.test.ts` files in
  this folder).
