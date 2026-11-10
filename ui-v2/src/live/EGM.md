# live

## Overview
Client side of the live-tick stream. `useLiveTicks` opens the server-sent
events connection for the watched symbols and index names, and keeps the latest
tick per symbol in React state.

## Interface
- `useLiveTicks.ts`: `useLiveTicks`, `buildLiveTicksUrl`, `buildIndicesUrl`,
  `mapFeedStatus`, `LiveTick`, `LiveStatus`, `LiveTicksState`,
  `UseLiveTicksOptions`. `LIVE_SYMBOL_LIMIT` must match the server's `MAX_LIVE_SYMBOLS`.
- `useLiveTicks.test.ts`: test suite (not part of the interface).

## Invariants
- At most `LIVE_SYMBOL_LIMIT` symbols are requested. Extra symbols are not
  streamed.
- URLs are built by `buildLiveTicksUrl` and `buildIndicesUrl`, so symbol lists
  are encoded in one place.
- `mapFeedStatus` converts the server status values to the UI status values.

## Side Effects
- Opens an `EventSource` connection to the server's live-tick routes.

## Verification
- Run: `npm test` in `ui-v2/` (covers `useLiveTicks.test.ts`).
