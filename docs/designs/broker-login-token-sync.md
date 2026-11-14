# Broker login and token sync from the UI (Kite first, then Upstox)

Status: v3.1, approved by the user 2026-11-14. Phase 1 (Kite) is in feat/broker-login-impl (stacked on PR 126). Phase 2 (Upstox) code is in feat/broker-login-upstox, awaiting the manual test in docs/designs/upstox-login-manual-test.md. Open questions answered by the user 2026-11-14 (including per-profile and per-broker connections).
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

## Scope of connections: per profile and per broker (user decision, 2026-11-14)

A user may hold accounts at one or many brokers, and there may be several profiles. So a broker connection is keyed by `(profile_id, broker)`:

- The access token, and also the api key and api secret for that broker app, are stored per `(profile_id, broker)` in `app_secret` under names of the form `broker.<profile_id>.<broker>.access_token`, `.api_key`, `.api_secret` (exact scheme to be checked against the `app_secret` schema in `db/migrations/045_app_secret.sql` in review). Reason for per-profile api credentials: a Kite Connect personal app only lets its owner's account log in (to be verified against Zerodha's current plan terms), so a second person needs their own app and key.
- The server allowlist becomes a prefix rule: `server` may read `broker.<profile_id>.<broker>.access_token` and `.api_key`, never `.api_secret`. The existing global names (`kite_api_key`, `upstox_analytics_token`) stay for the analytics and live-feed use and for the `default` profile until migrated.
- The `state` value, the callback and the status call carry `profile_id`; the stored `portfolio_*` rows already do.
- Phase 1 still ships with one `default` profile, but with the per-profile names so no rename is needed later.

## Upstox: same app or its own? (checked against Upstox docs, 2026-11-14)

Facts from the Upstox developer docs:

- Holdings endpoint: `GET https://api.upstox.com/v2/portfolio/long-term-holdings`, `Authorization: Bearer <token>`. Response items include `isin`, `trading_symbol`, `exchange`, `instrument_token`, `quantity`, `average_price`, `last_price`, `close_price`, `pnl`, `day_change`, `product`. The page does not name which token types it accepts.
- Login: `https://api.upstox.com/v2/login/authorization/dialog` (`response_type=code`, `client_id`, `redirect_uri`, `state`); token exchange by server-to-server POST to `https://api.upstox.com/v2/login/authorization/token` with `code`, `client_id`, `client_secret`, `redirect_uri`, `grant_type=authorization_code`. The code is single-use. The redirect URI must exactly match the one registered on the app. The docs do not say whether `127.0.0.1` is allowed or whether an app can register more than one redirect URI. Standard access tokens expire at about 03:30 IST daily (secondary sources).
- Analytics token: read-only, valid one year, one active per account. Since 2026-06-06 it also works for account-specific GET APIs, including Portfolio (holdings), but only with Static IP enabled on the account. Market-data GETs need no static IP. The docs do not say whether the standard OAuth token needs static IP for Portfolio.
- An Extended token (one-year, read-only, includes Get Holdings) exists but secondary sources say it is available on request for business integrations.

Recommendation:

1. Use the same Upstox app (same `client_id` and secret) for holdings as for the rest of the user's Upstox access, and use the OAuth login flow above. It is the only route that works for another user's account, and it fits the per-profile model: each profile logs in and gets its own daily token. Do not use the Analytics Token for holdings: it belongs to one account, needs a static IP, and would only ever return that account's holdings.
2. Register the server callback `http://127.0.0.1:8081/api/broker/upstox/callback` as the redirect URI on that app. Because the docs don't confirm `127.0.0.1` or multiple redirect URIs, make this the first task of phase 2: register it in the Upstox console and run one test login by hand. If Upstox rejects it, fall back to a `localhost` URL, or to a single public HTTPS redirect that forwards to the server.
3. Keep the existing analytics token for the live feed and market data (no static IP needed for those). Holdings use the profile's own OAuth token, so a daily-expiring token never affects live prices.
4. First check in phase 2: whether the OAuth token also needs a whitelisted static IP for Portfolio. If it does, a home connection without a fixed IP cannot sync Upstox holdings, and the design falls back to manual CSV import for Upstox.

## Open questions

1. Does the Upstox OAuth token need Static IP for Portfolio, and does the console accept `127.0.0.1` as a redirect URI? Both answered only by trying a login against the real console (phase 2, first task).
2. Is a Kite Connect personal app limited to the owner's account? Check Zerodha's current terms before promising multi-user Kite.

## Implementation notes (v3.1)

These corrections were found while implementing. Where they differ from the sections above, these notes win.

- Secret names use underscores, not dots, because `app_secret.name` must match `^[a-z][a-z0-9_]{1,63}$`. Names: `broker_<profile>_<broker>_access_token`, `_api_key`, `_api_secret`. `<profile>` has no underscores. Regex: `^broker_([a-z][a-z0-9]{0,15})_(kite|upstox)_(access_token|api_key|api_secret)$`.
- Token expiry is computed from `app_secret.updated_at`: Kite at the next 06:00 Asia/Kolkata. `expires_on` is set to the expiry date. No `app_secret` schema change, so no expiry column is added.
- Migration 058 (`db/migrations/058_portfolio_snapshots.sql`) adds `day_change` and `day_change_pct` to `portfolio_holding`. The key is `(sync_id, symbol, exchange)`, with `exchange` NOT NULL DEFAULT ''. The server merges rows with the same symbol and exchange before the insert (quantity and pnl summed, average price quantity-weighted), so a duplicate in the broker response cannot fail the whole sync.
- The callback `GET /api/broker/kite/callback` is exempt from the session gate by exact path only, like `/api/health`. It is protected by the single-use `state`. Look-alike paths stay gated.
- `BROKER_RETURN_URL` (default `http://127.0.0.1:5173/`) is where the callback sends the browser. It adds `?broker=kite&login=ok` or `?login=failed`.
- Cookie note: open the app at `127.0.0.1`, not `localhost`, so the session cookie is on the same host as the callback.
- Kite `state` travels in `redirect_params`, so Kite returns it on the callback.
- The ui keeps the pending `state` values in one in-process store, so the ui must run a single uvicorn worker.
- A non-default profile needs a `user_profile` row before its portfolio can be stored (foreign key in `portfolio_sync`). Only `default` is seeded.

## Implementation notes (phase 2, Upstox)

- Names: `broker_<profile>_upstox_api_key`, `broker_<profile>_upstox_api_secret` and `broker_<profile>_upstox_access_token`, with the same rules as Kite (Decision 17 in `docs/designs/secrets-and-roles.md`).
- No global fallback. Unlike `default` for Kite, the `default` profile does not fall back to a global Upstox key. Credentials must be stored per profile.
- Redirect URI: env `UPSTOX_REDIRECT_URI`, read by the ui at call time (not at import). Default `http://127.0.0.1:8081/api/broker/upstox/callback`, the server's callback. The ui service sets it in `docker-compose.yml`, and `env.template` documents it. The same value must be used at login and at the token exchange, and it must match the URI registered on the Upstox app.
- The server needs only the access token. The ui does the exchange with the client ID and secret, and the server never reads either. Upstox access tokens expire at 03:30 IST (`token_expiry` in `scanner/broker_tokens.py`).
- Callback: `GET /api/broker/upstox/callback` is session-exempt by exact path, like the Kite callback. Upstox denial (`error` with no `code`) redirects with `login=failed` and calls nothing.
- Holdings panel: a broker switch (Kite | Upstox) drives the status line, the login button, "Sync portfolio" and the stored holdings. The initial broker comes from `?broker=` after a login redirect, else Kite.
- `GET /api/holdings?profile=&broker=` returns the stored snapshot for that broker; `broker` defaults to `kite`, and any other value is a 400.
- Not yet verified against the live Upstox console: whether it accepts `127.0.0.1` and more than one redirect URI, and whether holdings need a static IP. These are for the manual test in `docs/designs/upstox-login-manual-test.md`.
