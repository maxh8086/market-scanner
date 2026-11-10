# live

## Overview
Live ticks for the UI. The server subscribes to the Upstox market-data feed,
decodes its binary frames, and fans ticks out to browsers over server-sent
events. Reconnect uses a backoff schedule.

## Interface
- `upstoxFeed.ts`: `createLiveFeed`, `LiveFeed`, `FeedMode`, `FeedStatus`,
  `FeedDeps`, `FeedListeners`. Owns the socket.
- `feedDecoder.ts`: `decodeFeedFrame`, `encodeFeedFrame`, `DecodedTick`.
- `liveRoute.ts`: `parseLiveSymbols`, `parseIndexNames`, `nseEquityKey`,
  `formatSseEvent`, `createWsSocket`, `buildIsinLookupQuery`,
  `MAX_LIVE_SYMBOLS`, `INDEX_INSTRUMENT_KEYS`.
- `reconnect.ts`: `backoffDelayMs`, `BACKOFF_STEPS_MS`.
- `*.test.ts`: test suites (not part of the interface).

## Invariants
- At most `MAX_LIVE_SYMBOLS` symbols are streamed per connection. Extra symbols
  are dropped. The UI's `LIVE_SYMBOL_LIMIT` must be kept in step with it.
- Symbols are validated and mapped to NSE instrument keys before subscription.
- Reconnect delays follow `BACKOFF_STEPS_MS`. `backoffDelayMs` is pure, so
  tests run without timers.
- Feed frames are decoded only through `decodeFeedFrame`.

## Side Effects
- Persistent WebSocket to the Upstox feed. The feed is authorised through the
  Upstox authorize endpoint (`AUTHORIZE_URL`) before the socket opens.
- Postgres lookup of ISIN values for symbols (`buildIsinLookupQuery`).
- Server-sent events written to each connected client.

## Verification
- Run: `npm test` in `server/` (covers `feedDecoder.test.ts`,
  `reconnect.test.ts`, `upstoxFeed.test.ts`).
