# Broker login and token sync from the UI (Kite first, then Upstox)

Status: DRAFT, unreviewed (no review subagents were run). Needs user approval before any task is dispatched.
Depends on: PR 126 (S3b, the `server` identity on the ui secrets endpoint). Cut the implementation branch after that merges, or stack on it.
Supersedes: Decision 16 in `docs/designs/secrets-and-roles.md` (Kite access token runtime-only).

## Problem

After S3b the server container cannot read `kite_access_token` (Decision 16), so Kite holdings report "unconfigured". The user wants to log in to the broker from the UI, under Holdings, and have the daily token fetched and used by the server. The same method applies to the Upstox non-analytics token, used for Upstox holdings sync.

## Facts that shape the design

- Neither Kite Connect nor Upstox has an API that accepts a one-time password. The user enters the OTP/TOTP on the broker's own login page. The broker then redirects the browser to our registered redirect URL with a `request_token` (Kite) or `code` (Upstox).
- The exchange of that value for an access token needs `api_secret` (Kite: SHA-256 checksum of api_key + request_token + api_secret; Upstox: client_secret in the token call). Only the ui holds the master key, so only the ui can do the exchange.
- Kite access tokens expire at about 06:00 IST each day. Upstox access tokens expire at about 03:30 IST each day.
- `scanner/auth.py` already does the Kite exchange as a CLI (`generate_session`, cached in `.kite_token`). That stays as the offline path.
- The Upstox holdings screen is blocked on the data-sharing licence check (`docs/designs/ui-redesign-spec.md` section 9, decision 1). Phase 2 below does not ship until that is cleared.

## Decision 16 replacement (Decision 17)

- The ui stores each daily broker token encrypted in `app_secret` under `kite_access_token` and `upstox_access_token`, with an `expires_at` (next 06:00 IST for Kite, 03:30 IST for Upstox).
- An expired token is never served; the endpoint returns 404 for it, and the server reports "login required".
- `server` allowlist grows to: `upstox_analytics_token`, `kite_api_key`, `kite_access_token`, and later `upstox_access_token`. `collector` and `llm_client` do not get them. `kite_api_secret` and `upstox_api_secret` are never served.
- Tokens are never logged, never put in a URL, and never returned to the browser. The browser only learns "connected until <time>" or "login required".

## Flow (Kite; Upstox is the same with its own endpoints)

1. Holdings panel shows a "Log in to Kite" button when status is `login_required`, or "Sync portfolio" when connected.
2. The button calls `POST /api/broker/kite/login-url` on the ui (route exposure is open question 1). The ui builds the Kite login URL from the stored `kite_api_key`, adds a signed `state` value (HMAC with a ui-held key, 10-minute expiry, single use), and returns it. The browser navigates to it.
3. The user enters password and OTP on the Zerodha page. Zerodha redirects to `http://127.0.0.1:8080/auth/callback/kite?request_token=...&state=...`.
4. The ui callback validates `state`, exchanges `request_token` for the access token using `kite_api_secret`, writes `kite_access_token` to `app_secret` with `expires_at`, and redirects the browser back to Holdings with no token in the URL.
5. "Sync portfolio" calls the server `/api/holdings`. The server fetches `kite_api_key` and `kite_access_token` from the ui secrets endpoint and calls Kite.
6. `GET /api/broker/kite/status` (ui) returns `{connected, expires_at}` for the panel.

## Components and files (to be confirmed in review)

- ui (FastAPI): new router `ui/app/broker_login.py` with `login-url`, `auth/callback/{broker}`, `status`. Reuses the secrets store in `scanner/secrets_store.py` for encrypted writes. Register in `ui/app/main.py`.
- ui internal secrets: extend `SERVICE_ALLOWED["server"]` in `ui/app/internal_secrets.py`; add expiry check on read.
- server: `server/src/index.ts` takes `accessToken` from `secrets.get("kite_access_token")` instead of `process.env.KITE_ACCESS_TOKEN`. `kiteHoldings.ts` unchanged.
- ui-v2: `HoldingsPanel.tsx` gets the login and sync buttons and the status line.
- compose and env: add `KITE_REDIRECT_URI` (default `http://127.0.0.1:8080/auth/callback/kite`) and a ui-held state-signing key, delivered as a single-file mount like the other tokens (no env secret).
- docs: Decision 17 in `secrets-and-roles.md`, CHANGELOG, `t4f-mvp-plan`, `collector-split-spec`, `db-touchpoint-v2`.

## Phases

1. Kite login, callback, encrypted store with expiry, server allowlist, server reads the stored token, Holdings panel buttons.
2. Upstox login and `upstox_access_token`, then Upstox holdings sync. Blocked on the licence check.

## Security notes

- The redirect URL is `127.0.0.1` only, which assumes a single-user local setup. A non-local host needs HTTPS and a fresh review.
- `state` stops a forged callback from planting an attacker's token. The callback accepts nothing without a valid unused `state`.
- The callback endpoint is the only unauthenticated write to `app_secret`; it can only write the one token name for that broker.
- Tests assert: expired token is not served; `collector`/`llm_client` get 403 for broker access tokens; the secret never appears in logs or in any response to the browser.

## Open questions

1. How is `ui-v2` served and how does it reach FastAPI endpoints under the "UI data only through API" rule (via the server proxying to the ui, or directly)? Review must settle this before tasks are written.
2. Does the Holdings panel's "Sync portfolio" also refresh stored holdings, or only fetch live (current behaviour: live fetch per request)?
3. Upstox: does the data-sharing licence allow holdings storage, or only a live display?
