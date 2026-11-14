# Broker login and token sync from the UI (Kite first, then Upstox)

Status: DRAFT v2, unreviewed (no review subagents were run). Open questions answered by the user 2026-11-14; needs user approval of this version before any task is dispatched.
Depends on: PR 126 (S3b, the `server` identity on the ui secrets endpoint). Cut the implementation branch after that merges, or stack on it.
Supersedes: Decision 16 in `docs/designs/secrets-and-roles.md` (see Decision 17 below).

## Problem

After S3b the server container cannot read `kite_access_token` (Decision 16), so Kite holdings report "unconfigured". The user wants to log in to the broker from the UI, under Holdings, press "Sync portfolio", and have the holdings stored in the database and shown until the next sync or refresh. The same method applies to Upstox.

## User decisions (2026-11-14)

1. Token path: the ui stores the daily token encrypted in `app_secret` with an expiry, and serves it to the server (supersedes Decision 16).
2. Redirect URL: local, `127.0.0.1`, registered once in each broker console.
3. Serving and routing: "you decide" (resolved below).
4. Holdings are stored in the database per user profile, and the stored portfolio is what the UI shows until the next sync or refresh.
5. Upstox licence: the user owns their own data, so storing the user's own Upstox holdings is the user's call. The Upstox data-sharing licence check in `docs/designs/ui-redesign-spec.md` section 9 is treated as not blocking for the user's own holdings. It still blocks redistributing Upstox market data.

## Facts that shape the design

- Neither Kite Connect nor Upstox has an API that accepts a one-time password. The user enters the OTP/TOTP on the broker's own login page. The broker redirects the browser to the registered redirect URL with a `request_token` (Kite) or `code` (Upstox).
- Exchanging that value for an access token needs the api secret (Kite: SHA-256 checksum of api_key + request_token + api_secret; Upstox: client_secret). Only the ui holds the master key, so only the ui can do the exchange.
- Kite access tokens expire at about 06:00 IST daily; Upstox at about 03:30 IST daily.
- `ui-v2` is a Vite SPA; in dev it proxies `/api` to the Fastify server (`ui-v2/vite.config.ts`, target `http://127.0.0.1:8081`). The server is the only API the browser talks to (rule: UI data only through the API).
- `scanner/auth.py` already does the Kite exchange as a CLI (`.kite_token`). It stays as the offline path.
- There is no user or profile table today (`db/migrations` up to 057). Tokens are app-level secrets with one Kite app.

## Decision 17 (replaces Decision 16)

- The ui stores each daily broker token encrypted in `app_secret` as `kite_access_token` / `upstox_access_token`, with an `expires_at`. An expired token is never served (404, server reports "login required").
- `server` allowlist grows to `upstox_analytics_token`, `kite_api_key`, `kite_access_token` and later `upstox_access_token`. `collector` and `llm_client` get none of the broker access tokens. `kite_api_secret` and `upstox_api_secret` are never served.
- Tokens are never logged, never in a URL, never returned to the browser. The browser only learns "connected until <time>" or "login required".

## Routing decision: the browser talks only to the server

The server owns every browser-facing route. The ui keeps the secrets and does the exchange, behind internal endpoints only the server identity may call.

Browser (ui-v2) -> server `/api/broker/{broker}/...` -> ui `/internal/broker/{broker}/...`.

This keeps the rule intact (no browser call to FastAPI or to a provider API), keeps the api secret and the master key inside the ui, and needs no new public port. The redirect URL registered with the broker is the server's callback, `http://127.0.0.1:8081/api/broker/{broker}/callback` (the published server port, 127.0.0.1 only), not a ui URL. This replaces the earlier `8080` callback in the decision above; the user's choice (local 127.0.0.1) is unchanged.

## Flow (Kite; Upstox is the same with its own endpoints)

1. Holdings panel (`ui-v2/src/shell/HoldingsPanel.tsx`) calls `GET /api/broker/kite/status`. The server asks the ui, which answers `{connected, expires_at}` (never the token). Button shows "Log in to Kite" when not connected, "Sync portfolio" when connected.
2. "Log in": `POST /api/broker/kite/login-url`. The server calls ui `POST /internal/broker/kite/login-url`. The ui builds the Kite login URL from `kite_api_key`, creates a single-use `state` (random, 10-minute expiry, held in the ui), and returns the URL. The browser navigates to it.
3. The user enters password and OTP on the Zerodha page. Zerodha redirects to `http://127.0.0.1:8081/api/broker/kite/callback?request_token=...&state=...`.
4. The server callback forwards `request_token` and `state` to ui `POST /internal/broker/kite/exchange`. The ui checks and consumes `state`, exchanges the token with `kite_api_secret`, stores `kite_access_token` with `expires_at`, and answers "ok". The server then redirects the browser to the Holdings page with no token in the URL.
5. "Sync portfolio": `POST /api/holdings/sync`. The server fetches `kite_api_key` and `kite_access_token` from the ui secrets endpoint, calls Kite, and writes the result to the database (next section). The panel then reads the stored portfolio.
6. A failed or expired token during sync returns "login required" and leaves the stored portfolio unchanged.

## Stored portfolio (per profile)

- Each sync writes a new snapshot; the UI reads the latest successful snapshot until the next sync or refresh. A failed sync never replaces it.
- Proposed tables (migration number is the next free one on main at build time, 058 today; GRANT only to `market_scanner_server`; no secrets in it):
  - `user_profile(profile_id, display_name, created_at)`, seeded with one row, `default`. A real login and multi-user is out of scope; the key exists so holdings are profile-scoped from the start.
  - `portfolio_sync(sync_id, profile_id, broker, synced_at, status, row_count)`.
  - `portfolio_holding(sync_id, profile_id, broker, symbol, isin, exchange, quantity, average_price, last_price, pnl, raw jsonb)`.
- The server reads and writes these through its dedicated DB role. Holdings read endpoint: `GET /api/holdings?profile=default` (profile defaults to `default`).
- Live prices still come from Upstox feeds (as today); the stored last price is shown as of the sync time.

## Components and files (to be confirmed in review)

- ui (FastAPI): `ui/app/broker_login.py` with internal `login-url`, `exchange`, `status`; encrypted writes through `scanner/secrets_store.py`; register in `ui/app/main.py`. Internal-only, authorised by the `server` bearer token. Extend `SERVICE_ALLOWED["server"]` and add an expiry check in `ui/app/internal_secrets.py`.
- server: `/api/broker/{broker}/status|login-url|callback`, `/api/holdings/sync`, store read and write; `server/src/index.ts` takes the access token from `secrets.get("kite_access_token")` (update `indexWiring.test.ts` to match). `kiteHoldings.ts` fetch/parse stays.
- ui-v2: Holdings panel buttons and the status line; reads stored holdings.
- compose and env: `KITE_REDIRECT_URI` default above. No new secret mounts: `state` is held in the ui, not signed with a key.
- docs: Decision 17 in `secrets-and-roles.md`, CHANGELOG, `t4f-mvp-plan`, `collector-split-spec`, `db-touchpoint-v2`.

## Phases

1. Kite: login, callback, encrypted token with expiry, server allowlist, sync into the stored portfolio, Holdings buttons.
2. Upstox: same flow with `upstox_access_token` and the Upstox holdings endpoint, reusing the stored-portfolio tables with `broker = 'upstox'`.

## Security notes

- Local single-user setup only. A non-local host needs HTTPS and a fresh review.
- `state` stops a forged callback from planting an attacker's token; the exchange accepts nothing without a valid unused `state`. The callback is the only browser-reachable path that causes a token write, and it can only write the token for that broker.
- Tests assert: expired token is not served; `collector` and `llm_client` get 403 for broker access tokens; no token or api secret in logs or in any response to the browser; a failed sync keeps the previous snapshot; a replayed or expired `state` is rejected.

## Open questions

1. Profile scope: one `default` profile now. Should broker tokens also become per-profile later, or stay one app-level connection per broker? (Affects only the future multi-user work; not needed for phase 1.)
2. Is the Upstox holdings endpoint covered by the same API key and app as the analytics token, or does it need its own registered Upstox app (and its own redirect URL)? To check against Upstox's docs at the start of phase 2.
