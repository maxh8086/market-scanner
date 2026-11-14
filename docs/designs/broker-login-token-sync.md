# Broker login and token sync from the UI (Kite first, then Upstox)

Status: design v3 was approved by the user 2026-11-14, with the user decisions listed below. The v3.1 implementation notes were not separately approved by the user. Their content is folded into this body. Phase 1 (Kite) and phase 2 (Upstox) are merged (PRs 127 and 128).

Open items (the only ones still open):

- Live Upstox console checks: whether the console accepts the redirect URI `http://127.0.0.1:8081/api/broker/upstox/callback`, whether it allows more than one redirect URI, and whether holdings need a static IP. Not verified. Run `docs/designs/upstox-login-manual-test.md`.
- Kite multi-user: whether a Kite Connect personal app may be used by a second person. Not verified. Check Zerodha's current terms first.

This design partly supersedes Decision 16 in `docs/designs/secrets-and-roles.md`. The rules that now apply to broker access tokens are in [Decision 17](secrets-and-roles.md).

## Changes from v3

- Broker access tokens are stored as `broker_<profile>_<broker>_access_token`. v3 named a global `kite_access_token`.
- Expiry is computed from `app_secret.updated_at` plus the broker cut-off. No schema change. `expires_on` is set but is informational only. v3 stored an `expires_at`.
- The global `kite_access_token` is never served to any service. v3 let the server read it.
- Secret names use underscores, not dots, because `app_secret.name` must match `^[a-z][a-z0-9_]{1,63}$`.
- The callback is the server's: `http://127.0.0.1:8081/api/broker/{broker}/callback`. The stray `8080` callback is removed.
- Writes go through `scanner/app_secrets.py`. v3 named `scanner/secrets_store.py`.
- `KITE_REDIRECT_URI` is removed. It was never implemented. The real variables are `UPSTOX_REDIRECT_URI`, `BROKER_RETURN_URL` and `SERVER_PORT`.
- The stored-portfolio tables are as built in migration 058. `portfolio_holding` gained `day_change` and `day_change_pct`. The key is `(sync_id, symbol, exchange)`. `user_profile` is seeded with `default`.
- Duplicate `(symbol, exchange)` rows in a broker reply are merged before the insert.
- The holdings read takes a broker: `GET /api/holdings?profile=&broker=`. v3 had no broker parameter.
- Upstox is added as phase 2, with the same flow. The ui holds its client ID and secret. The server reads only the access token.
- The Kite and Upstox callbacks are exempt from the session gate by exact path only.
- `server/src/index.ts` reads only `upstox_analytics_token` for the live feed. v3 said it read `kite_access_token`.
- Per-profile api key and api secret names are used. The global `kite_api_key` and `kite_api_secret` remain as a fallback for the `default` profile (Kite only).

## Problem

After S3b the server container cannot read `kite_access_token` (Decision 16), so Kite holdings report "unconfigured". The user wants to log in to the broker from the UI, under Holdings, press "Sync portfolio", and have the holdings stored in the database and shown until the next sync or refresh. The same method applies to Upstox.

## User decisions (2026-11-14)

1. Token path: the ui stores the daily token encrypted in `app_secret` and serves it to the server (supersedes Decision 16 for broker tokens).
2. Redirect URL: local, `127.0.0.1`, registered once in each broker console.
3. Serving and routing: resolved below.
4. Holdings are stored in the database per user profile. The stored portfolio is what the UI shows until the next sync or refresh.
5. Upstox licence: the user owns their own data, so storing the user's own Upstox holdings is the user's call. The Upstox data-sharing licence check in `docs/designs/ui-redesign-spec.md` section 9 is treated as not blocking for the user's own holdings. It still blocks redistributing Upstox market data. The spec section was not re-read in this pass.

## Facts that shape the design

- Neither Kite Connect nor Upstox has an API that accepts a one-time password. The user enters the OTP/TOTP on the broker's own login page. The broker redirects the browser to the registered redirect URL with a `request_token` (Kite) or `code` (Upstox).
- Exchanging that value for an access token needs the api secret (Kite: SHA-256 checksum of api_key + request_token + api_secret; Upstox: client_secret). Only the ui holds the master key, so only the ui can do the exchange.
- Kite access tokens expire at about 06:00 IST daily; Upstox at about 03:30 IST daily. The code uses these cut-offs. The provider behaviour is not verified in this pass.
- `ui-v2` is a Vite SPA. In dev it proxies `/api` to the Fastify server (`ui-v2/vite.config.ts`, target `http://127.0.0.1:8081`). The server is the only API the browser talks to (rule: UI data only through the API).
- `scanner/auth.py` does the Kite exchange as an offline CLI (`.kite_token`). It stays as the offline path.
- Before migration 058 there was no user or profile table. Migration 058 adds `user_profile`.

## Decision 17 (replaces Decision 16 for broker tokens)

- The ui stores each daily broker token encrypted in `app_secret` as `broker_<profile>_<broker>_access_token`. The expiry is computed (see Behaviour rules). An expired token is treated as not stored: the ui answers 404 without decrypting it.
- The `server` identity may read `upstox_analytics_token`, `kite_api_key`, and any name matching `broker_<profile>_<broker>_access_token` or `broker_<profile>_<broker>_api_key`. It never reads `*_api_secret`, and it never reads the global `kite_access_token`.
- `collector` and `llm_client` get 403 for every `broker_*` name. `collector` may read `upstox_analytics_token` only. `llm_client` reads `llm_key_*` names only.
- Tokens are never logged, never put in a URL, never returned to the browser. The browser learns only "connected until <time>" or "not connected".

## Routing decision: the browser talks only to the server

The server owns every browser-facing route. The ui keeps the secrets and does the exchange, behind internal endpoints that only the server identity may call.

Browser (ui-v2) -> server `/api/broker/{broker}/...` -> ui `/internal/broker/{broker}/...`.

This keeps the rule intact (no browser call to FastAPI or to a provider API), keeps the api secret and the master key inside the ui, and needs no new public port. The redirect URL registered with each broker is the server's callback, `http://127.0.0.1:8081/api/broker/{broker}/callback`, on the published server port (127.0.0.1 only), not a ui URL.

## Flow (Kite; Upstox is the same with its own endpoints)

1. The Holdings panel (`ui-v2/src/shell/HoldingsPanel.tsx`) calls `GET /api/broker/kite/status?profile=default`. The server asks the ui `GET /internal/broker/kite/status?profile_id=default`, which answers `{connected, expires_at}`. The server answers the browser with `{connected, expiresAt}`. No token is sent. The button shows "Log in to Kite" when not connected, and "Sync portfolio" when connected.
2. "Log in": `POST /api/broker/kite/login-url` with `{profile}`. The server calls ui `POST /internal/broker/kite/login-url`. The ui builds the Kite login URL from the profile's `api_key` (the `default` profile falls back to the global `kite_api_key`). It creates a single-use `state`, holds it in the ui, and returns the URL. The browser navigates to it. The URL carries `v`, `api_key` and `redirect_params=state=...`. No redirect URL is sent to Kite (see Setup).
3. The user enters password and OTP on the Zerodha page. Zerodha redirects to `http://127.0.0.1:8081/api/broker/kite/callback?request_token=...&state=...`.
4. The server callback forwards `request_token` and `state` to ui `POST /internal/broker/kite/exchange`. The ui consumes `state` (the profile comes from the state, not from the URL), exchanges the token with the profile's api secret, stores `broker_<profile>_kite_access_token` with the computed expiry, and answers `{profile_id, expires_at}`. The server then redirects the browser to `BROKER_RETURN_URL` with `?broker=kite&login=ok`. No token is in the URL.
5. "Sync portfolio": `POST /api/holdings/sync` with `{profile, broker}`. The server reads the access token and the api key from the ui secrets endpoint, calls the broker's holdings endpoint, and writes the result to the database (next section). The panel then reads the stored portfolio.
6. A failed or expired token during sync returns 401 "login required" and leaves the stored portfolio unchanged.

## Stored portfolio (per profile and broker)

- Each sync writes a new snapshot. The UI reads the latest `ok` snapshot for the profile and broker until the next sync or refresh. A failed sync never replaces it.
- Migration `db/migrations/058_portfolio_snapshots.sql` builds the tables. Grants go to `market_scanner_server` only. No secrets are stored in them.
  - `user_profile(profile_id text primary key, display_name text, created_at timestamptz)`. `profile_id` must match `^[a-z][a-z0-9]{0,15}$`. The row `default` is seeded.
  - `portfolio_sync(sync_id uuid primary key, profile_id text references user_profile, broker text in ('kite','upstox'), synced_at timestamptz, status text in ('ok','failed'), row_count integer)`. Only `ok` is written in phases 1 and 2.
  - `portfolio_holding(sync_id uuid references portfolio_sync on delete cascade, profile_id, broker, symbol text, isin text, exchange text not null default '', quantity numeric, average_price numeric, last_price numeric, pnl numeric, day_change numeric, day_change_pct numeric, raw jsonb)`. Primary key `(sync_id, symbol, exchange)`. `raw` holds the parsed broker row only.
- Grants: the server role has `SELECT` on `user_profile`, and `SELECT, INSERT` on `portfolio_sync` and `portfolio_holding`. It never updates or deletes a snapshot.
- Read endpoint: `GET /api/holdings?profile=default&broker=kite`. `profile` defaults to `default`. `broker` defaults to `kite`. Any other broker value is a 400.
- Live prices still come from Upstox feeds, as today. The stored last price is shown as of the sync time.

## Components and files (as built)

Server (`server/src/`):

- `index.ts`: wires the secrets client, the ui client, `BROKER_RETURN_URL` (default `http://127.0.0.1:5173/`) and the portfolio store. The live feed token is `upstox_analytics_token`.
- `broker/brokerRoutes.ts`: status, login-url, the Kite and Upstox callbacks, `POST /api/holdings/sync`, `GET /api/holdings`. Tests: `broker/brokerRoutes.test.ts`, `broker/noApiSecret.test.ts`.
- `broker/credentials.ts`: reads the access token and the api key per profile. Tests: `broker/credentials.test.ts`.
- `broker/names.ts`: builds `broker_<profile>_<broker>_<kind>` and checks the profile. Tests: `broker/names.test.ts`.
- `broker/portfolioStore.ts`: writes one `ok` snapshot in one transaction and reads the latest one. Tests: `broker/portfolioStore.test.ts`.
- `holdings/kiteHoldings.ts`, `holdings/upstoxHoldings.ts`: fetch and parse the broker holdings. Tests: `holdings/kiteHoldings.test.ts`, `holdings/upstoxHoldings.test.ts`.
- `uiClient.ts` (ui internal API), `secretsClient.ts` (secret reads), `session.ts` (session gate and the two exempt callback paths).
- `indexWiring.test.ts`: checks the server wiring.

UI client (`ui-v2/src/`):

- `shell/HoldingsPanel.tsx`, with `shell/HoldingsPanel.test.tsx`: broker tabs, status line, Log in and Sync buttons, stored holdings.
- `api/broker.ts`: status, login-url and sync calls.
- `api/holdings.ts`, with `api/holdings.test.ts`: reads the stored snapshot.

UI service (`ui/app/`):

- `broker_login.py`: internal `login-url`, `exchange` and `status` routes, and the in-process `state` store. Writes go through `scanner/app_secrets.py`.
- `internal_secrets.py`: the service allowlist and the expiry check.
- `main.py`: includes the `broker_login` router.

Scanner and database:

- `scanner/broker_tokens.py`: names, `SECRET_NAME_RE`, profile check and expiry cut-offs.
- `scanner/app_secrets.py`: encrypted `app_secret` store.
- `scanner/secrets_cli.py`: admin `set` command (value typed at a hidden prompt).
- `scanner/auth.py`: offline Kite CLI. Its current state was not re-checked in this pass.
- `db/migrations/045_app_secret.sql`: `app_secret` table. `db/migrations/058_portfolio_snapshots.sql`: the portfolio tables.

Compose and config:

- `docker-compose.yml`: `ui` service (holds the master key, sets `UPSTOX_REDIRECT_URI`) and `server` service (sets `BROKER_RETURN_URL`, publishes `127.0.0.1:${SERVER_PORT:-8081}:8081`).
- `env.template`: documents `SERVER_PORT`, `BROKER_RETURN_URL` and `UPSTOX_REDIRECT_URI`.

Tests (Python): `tests/test_broker_login.py`, `tests/test_broker_tokens.py`, `tests/test_compose_server_service.py`.

## Behaviour rules

(a) What counts as a successful sync.

- Rule: a sync is successful when the broker call succeeds and the snapshot transaction commits. The parser drops rows without a symbol (Upstox: `trading_symbol`) or without a quantity. Rows with the same `(symbol, exchange)` are merged before the insert. The exact rule for a non-list broker reply was not re-verified in this pass.
- Why: a broker reply that parses to nothing must not look like a real portfolio.
- Known gap (not implemented): an empty reply, or a reply whose rows are all dropped, writes a zero-row `ok` snapshot. The intended rule is that non-empty input with zero parsed rows is a failed sync, which leaves the previous snapshot in place.
- Errors: a Kite 403 is returned as 401 "login required". An Upstox 401 is returned as 401. An Upstox 403 is passed through as 403 with the static IP message. A missing api key returns 409. A failed database write is 500 "portfolio save failed". The other broker error codes were not re-verified in this pass.

(b) "Connected" means inside the assumed cut-off window, not verified with the broker.

- Rule: the status route reports connected while `now` is before the next cut-off (06:00 IST for Kite, 03:30 IST for Upstox) after the token was stored. Nothing calls the broker to check.
- Why: the check is free and offline. A broker can revoke a token before the cut-off.
- What the UI does after a sync 401 today: `HoldingsPanel.tsx` sets the state to disconnected and shows a login-required notice, so the login button returns for that session. After a reload the status still says connected until the cut-off, so the UI shows "Sync portfolio" and no login action. The user gets the login action back only after a sync returns 401. Known gap.
- After an Upstox 403 (static IP), the UI behaviour was not re-verified in this pass. The design intends an error message only, with no login action. A new login would not fix a static IP refusal.

(c) A profile is a naming and keying label, not an authorization boundary.

- Rule: all `/api` routes sit behind the one browser session. The profile is checked only for its format. Any user with that session can use any profile name.
- Why: the design has one user. Profiles keep the data keyed from the start.
- Add a profile:
  1. An administrator inserts a `user_profile` row first. The server role has only `SELECT` on `user_profile`, so the insert must run under an admin role, not the server role.
  2. Store the profile's broker api key and api secret with `scanner.secrets_cli set`, using the names `broker_<profile>_<broker>_api_key` and `..._api_secret`.
  3. Log in and sync.
- Why step 1 comes first: `portfolio_sync.profile_id` references `user_profile`. Login, status and exchange do not check `user_profile`. A new profile therefore logs in, but its first sync fails at the insert with 500 "portfolio save failed", and nothing is stored.

(d) The server-held OAuth token is order-capable, and the server uses it only for holdings.

- Rule: the server reads the broker access token and uses it only for the two holdings GET calls (`api.kite.trade/portfolio/holdings` and `api.upstox.com/v2/portfolio/long-term-holdings`). It never sends an order.
- Why: the broker token is not verified to be read-only, so the design treats it as able to place orders. Its scope at each broker is not verified.

(e) One-time setup: redirect URLs.

- Register at Upstox (the Upstox app): `http://127.0.0.1:8081/api/broker/upstox/callback`. Whether the console accepts `127.0.0.1` or more than one URI: not verified.
- Register at Kite (the Kite Connect app redirect URL): `http://127.0.0.1:8081/api/broker/kite/callback`. The code sends no redirect URL to Kite, so the registered value is the one Kite uses. The exact Kite console behaviour: not verified.
- These values must change together: the server host port (`SERVER_PORT`, default 8081; the container port stays 8081), `UPSTOX_REDIRECT_URI` (ui, default `http://127.0.0.1:8081/api/broker/upstox/callback`), and the URLs registered at each broker. If `SERVER_PORT` changes, update all three.
- `BROKER_RETURN_URL` is not registered anywhere. It is where the server sends the browser after the callback (default `http://127.0.0.1:5173/`).
- Open the app at `127.0.0.1`, not `localhost`. The session cookie must be on the same host as the callback.

## Implementation notes that the code enforces

- Names: `broker_<profile>_<broker>_<kind>`, with `<kind>` one of `access_token`, `api_key`, `api_secret`. Profile regex `^[a-z][a-z0-9]{0,15}$` (no underscores). The full name regex is `^broker_([a-z][a-z0-9]{0,15})_(kite|upstox)_(access_token|api_key|api_secret)$` in `scanner/broker_tokens.py` (`SECRET_NAME_RE`). `server/src/broker/names.ts` builds the names and checks the profile, but has no full-name regex. Names also pass the `app_secret` rule `^[a-z][a-z0-9_]{1,63}$` (`scanner/app_secrets.py`).
- Expiry: computed from `app_secret.updated_at`. Kite: next 06:00 Asia/Kolkata. Upstox: next 03:30 Asia/Kolkata (`token_expiry` in `scanner/broker_tokens.py`). `expires_on` is set to the expiry date in IST, for information. No `app_secret` schema change.
- Default profile fallback: only for Kite. `default` falls back to the global `kite_api_key` and `kite_api_secret` when its own name is not stored. Upstox has no global fallback: its credentials are per profile only.
- Login state: a random single-use `state`, valid for 10 minutes (`STATE_TTL_S = 600`), held in one in-process store in the ui. It is bound to a profile and a broker, and the exchange consumes it whatever the outcome. The ui must run one uvicorn worker, because the store is per process. Kite `state` travels in `redirect_params`, so Kite returns it on the callback.
- Callbacks: `GET /api/broker/kite/callback` and `GET /api/broker/upstox/callback` are exempt from the session gate by exact path only, like `/api/health`. Look-alike paths stay gated. A failed callback redirects with `login=failed` and calls nothing. The per-case handling in `brokerRoutes.ts` was not re-verified in this pass.
- Exchanges: Kite posts to `api.kite.trade/session/token` with the SHA-256 checksum. Upstox posts to `api.upstox.com/v2/login/authorization/token` with `client_id`, `client_secret`, `redirect_uri` and `grant_type=authorization_code`. The redirect URI at login and at the exchange must be the same value.
- Upstox login URL: `https://api.upstox.com/v2/login/authorization/dialog` with `response_type=code`, `client_id`, `redirect_uri` and `state`. `UPSTOX_REDIRECT_URI` is read at call time, not at import. The server never reads the Upstox client ID or secret.
- Holdings UI: a broker switch (Kite | Upstox) drives the status line, the login button, "Sync portfolio" and the stored holdings. The first broker comes from `?broker=` after a login redirect, else Kite.
- Callback notice: the login notice names the broker from `?broker=`. The notice text is "login complete" on success and "login failed" otherwise.

## Security notes

- Local single-user setup only. A non-local host needs HTTPS and a fresh review.
- `state` stops a forged callback from planting an attacker's token. The exchange accepts nothing without a valid unused `state`. The callback is the only browser-reachable path that causes a token write, and it can only write the token for the broker named in its own route.
- The design lists these tests. Not all were re-verified in this pass: an expired token is not served; `collector` and `llm_client` get 403 for broker names; no token or api secret appears in logs or in any response to the browser; a failed sync keeps the previous snapshot; a replayed or expired `state` is rejected. Test files: `tests/test_broker_login.py`, `server/src/broker/brokerRoutes.test.ts`, `server/src/broker/noApiSecret.test.ts`.

## Upstox facts (carried from the v3 text; developer docs not re-checked in this pass)

- Holdings endpoint: `GET https://api.upstox.com/v2/portfolio/long-term-holdings`, `Authorization: Bearer <token>`. The code uses this URL. The docs do not name which token types the endpoint accepts.
- Analytics token: read-only, valid one year, one active per account. Secondary sources say it also works for account-specific GET APIs, including Portfolio, but only with Static IP enabled. Whether the standard OAuth token needs static IP for Portfolio: not verified.
- An Extended token (one-year, read-only, includes Get Holdings) exists. Secondary sources say it is available on request for business integrations.
- Standard access tokens expire at about 03:30 IST daily (secondary sources).

Decision for Upstox holdings (as built): the same Upstox app as the rest of the user's Upstox access, with the OAuth login flow. Each profile logs in and gets its own daily token. The Analytics Token is not used for holdings: it belongs to one account, may need a static IP, and would return only that account's holdings. The analytics token stays for the live feed and market data, so a daily token never affects live prices.

Not verified and to check in the manual test: whether the console accepts `127.0.0.1` and more than one redirect URI, and whether the OAuth token needs a whitelisted static IP for Portfolio. If it does, a home connection without a fixed IP cannot sync Upstox holdings. The fallback is a manual CSV import, which is not built.

## Open questions

1. Does the Upstox OAuth token need Static IP for Portfolio, and does the console accept `127.0.0.1` as a redirect URI? Not verified. Answered only by a login against the real console (manual test).
2. Is a Kite Connect personal app limited to the owner's account? Not verified. Check Zerodha's current terms before promising multi-user Kite.
3. Known gaps, not implemented: the empty-reply sync rule (Behaviour rules a), the missing login action after a reload (Behaviour rules b), and the missing login action after an Upstox 403 (Behaviour rules b).
