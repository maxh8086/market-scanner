# ui-v2

## Overview
The React and Vite client for the market scanner. It talks only to the
`server/` JSON API and to its server-sent events stream. `src/` contains the
application. `vite.config.ts` is the build configuration. `index.html` is the
Vite entry page.

## Interface
- `vite.config.ts`: build and dev-server configuration.
- Source is in [src](./src/EGM.md).

## Invariants
- The client never connects to Postgres, MongoDB or Upstox. All data arrives
  through `src/api/` and `src/live/`.
- Dev-server settings and proxies are defined only in `vite.config.ts`.

## Side Effects
- Dev server and production build output under the build directory (Vite
  defaults). Not source.

## Verification
- Run: `npm test` (`vitest run`) in `ui-v2/`.
- Run: `npm run typecheck` in `ui-v2/`.
