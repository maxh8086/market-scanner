# shell

## Overview
The application chrome: top bar, tab strip, resizable panels, watchlist and
market-watch panels, holdings panel, command palette, EOD refresh control, and
the shared loading and error view.

## Interface
- `AppShell.tsx`: `AppShell`, `AppShellProps`.
- `TopBar.tsx`: `TopBar`. Top application bar.
- `TabStrip.tsx`: `TabStrip`, `TabItem`. Tab strip for open views.
- `ResizablePanels.tsx`: `ResizablePanels`.
- `WatchlistPanel.tsx`: `WatchlistPanel`, `indexChange`, `eodTicksFromResponse`.
- `watchlistStore.ts`: `loadCustomWatchlist`, `saveCustomWatchlist`,
  `addCustomSymbol`, `normalizeSymbol`, `segmentIndices`, `INDEX_SEGMENTS`,
  `DEFAULT_INDICES`, `ALL_INDICES`.
- `HoldingsPanel.tsx`: `HoldingsPanel`, `toHoldingRow`, `totalHoldings`.
- `CommandPalette.tsx`: `CommandPalette`, `openCommandPalette`,
  `OPEN_COMMAND_PALETTE_EVENT`.
- `EodRefreshButton.tsx`: `EodRefreshButton`, `formatCountdown`,
  `estimateSeconds`, `queuedProgressText`.
- `DataAgeStamp.tsx`: `DataAgeStamp`.
- `StateView.tsx`: `StateView`, `StateKind`, `StateViewAction`.
- Tests: `*.test.tsx` beside each component.

## Invariants
- Watchlist sections are fixed by `INDEX_SEGMENTS` and displayed in that order.
- Custom watchlist symbols pass through `normalizeSymbol` before they are
  stored.
- `openCommandPalette` opens the palette by dispatching a window event
  (`OPEN_COMMAND_PALETTE_EVENT`).
- The server decides whether an EOD refresh is allowed (see
  `server/src/collectorRefresh.ts`). The button shows a countdown while a
  refresh is queued.

## Side Effects
- `localStorage` for the custom watchlist (`watchlistStore.ts`), the panel
  widths (`ResizablePanels.tsx`) and the watchlist column choice
  (`WatchlistPanel.tsx`).
- Window event dispatch and listeners (command palette), and window resize
  listeners (`ResizablePanels.tsx`).
- HTTP calls for the EOD refresh (`api/collectorRefresh.ts`) and the holdings
  panel (`api/holdings.ts`).

## Verification
- Run: `npm test` in `ui-v2/` (covers the `*.test.tsx` files in this folder).
