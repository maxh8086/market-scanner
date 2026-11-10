# src

## Overview
Application source for the React client. `main.tsx` mounts `App.tsx`, which
composes the shell, table, stock page and sector heatmap. Each folder owns one
feature and exposes its components and pure helpers.

## Interface
- `main.tsx`: entry point. Mounts the app. Not an importable module.
- `App.tsx`: `App`. Root component.
- Subdirectories: [api](./api/EGM.md), [filters](./filters/EGM.md),
  [lib](./lib/EGM.md), [live](./live/EGM.md), [sectors](./sectors/EGM.md),
  [shell](./shell/EGM.md), [stock](./stock/EGM.md), [table](./table/EGM.md),
  [theme](./theme/EGM.md).
- `styles/`: `index.css` and `tokens.css`, CSS only. No code contract, so it
  is not linked.
- `test/`: `setup.ts`, the Vitest setup file. Test-only, so not documented.
- `*.test.ts(x)` files sit beside their modules and are not part of the
  interface.

## Invariants
- Shared pure formatting and session logic lives in `lib/`.
- Network access goes through `api/` and `live/`.
- `LIVE_SYMBOL_LIMIT` (in `live/`) must be kept in step with the server's
  `MAX_LIVE_SYMBOLS`.

## Side Effects
- Browser-level effects: `window` and `document` listeners (command palette
  shortcut, resize handling), `localStorage` for watchlist and theme state.
- Network calls through the API modules and the live-tick socket.

## Verification
- Run: `npm test` in `ui-v2/` (covers `App.test.tsx` and the per-folder tests).
