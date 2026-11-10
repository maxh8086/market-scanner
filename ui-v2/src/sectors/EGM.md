# sectors

## Overview
Sector heatmap and sector table. `sectorView.ts` holds pure sorting, tone and
breadth helpers. `SectorHeatmap.tsx` renders them.

## Interface
- `sectorView.ts`: `sortSectors`, `toneOf`, `advDecRatio`, `breadthShares`,
  `topAndBottom`, `stockCountLabel`, `SortKey`, `SortDir`, `SortState`, `Tone`.
- `SectorHeatmap.tsx`: `SectorHeatmap`, `SectorHeatmapProps`.
- Tests: `sectorView.test.ts`, `SectorHeatmap.test.tsx`.

## Invariants
- `sectorView.ts` has no React and no network. Its functions are pure.
- Sector data comes in through props. The component does not fetch it.

## Side Effects
- None in `sectorView.ts`. `SectorHeatmap.tsx` has no side effects beyond
  rendering.

## Verification
- Run: `npm test` in `ui-v2/` (covers `sectorView.test.ts`,
  `SectorHeatmap.test.tsx`).
