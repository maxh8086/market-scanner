# server Blueprint

## System Overview
A Fastify (TypeScript, ESM) JSON API that sits between the `ui-v2` client and
Postgres, Upstox and Kite. It runs on loopback only. `src/index.ts` loads the
repository-root `.env`, builds a `pg` pool, and starts `buildApp` on
`127.0.0.1`. It never binds `0.0.0.0`. The API provides run results, candles,
sector summaries, filter options, presets, collector refresh, recent closes,
live ticks over server-sent events, holdings and secret lookups.

## Local Interface & Invariants
No direct source files. Source is under `src/`. The test suite is in `test/`
and is test-only, so it is not documented here.

## Subdirectories & System Boundaries
- [src](./src/EGM.md): all server source.
- `test/`: Vitest suites for the query builders and validators. Test-only, so
  not documented here.
- `package.json`, `tsconfig.json`: build manifests.

## Global Invariants
- Routes validate input before they build SQL. Query builders are pure and
  return parameterised statements.
- Binds to `127.0.0.1` only.
- Reads `.env` from the repository root. Existing process environment values
  take precedence over file values.

## Global Side Effects
- Postgres reads through a `pg` pool, which is closed on server shutdown.
- Outbound calls to Upstox (live feed) and Kite (holdings).
- Server-sent events to connected browsers.
- Secrets read from the local secrets file through `secrets.ts`.

## System Verification
- Run: `npm test` (`vitest run`) in `server/`.
- Run: `npm run typecheck` in `server/`.
