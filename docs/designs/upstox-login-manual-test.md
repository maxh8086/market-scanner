# Upstox login and holdings sync: manual test

Status: to run once by the user. Phase 2 code is in `feat/broker-login-upstox`. Claude cannot do this test, because it needs your own Upstox console access and your own Upstox login.

Purpose: find out three things that the Upstox developer docs do not state clearly:

- (a) whether the Upstox console accepts the redirect URI `http://127.0.0.1:8081/api/broker/upstox/callback`;
- (b) whether a login followed by "Sync portfolio" returns your holdings, or an error;
- (c) whether Upstox demands a static IP for the holdings call.

Record the three outcomes at the end and send them back. Do not paste any client ID, secret, token or code into chat, a file or a URL.

## Before you start

- The stack is running (`start.ps1` brings up the `ui`, `collector` and `server` services).
- You have an Upstox account, and an app in the Upstox developer console. The console may call this an "app"; check the exact name in the console.
- Use `127.0.0.1` in the browser, not `localhost`. The session cookie must be on the same host as the callback.

## Step 1: register the redirect URI on the Upstox app

1. Open your app in the Upstox developer console.
2. Find the redirect URI setting. Check the field and any help text in the console; the exact label may differ.
3. Add `http://127.0.0.1:8081/api/broker/upstox/callback`. It must match exactly: scheme, host, port and path. Do not add a trailing slash.
4. Check whether the console accepts this address. Check also whether it accepts more than one redirect URI. If it allows only one, keep only this one.
5. Save the app.

If the console rejects `127.0.0.1`, go to fallback A below and stop here. Record the console's exact message.

## Step 2: store the app's credentials in the app (not in a file)

1. Copy the app's client ID (the API key) and client secret from the Upstox console.
2. Open the admin secrets page of the app. Check the page's menu for it.
3. Store the client ID as `broker_default_upstox_api_key`.
4. Store the client secret as `broker_default_upstox_api_secret`.
5. Do not put these values in `.env`, `data/secrets.env`, any other file, a URL or chat.

## Step 3: check that no file needs changing

Leave `UPSTOX_REDIRECT_URI` unset. The ui uses its default, `http://127.0.0.1:8081/api/broker/upstox/callback`, which is the value you registered in step 1. Nothing else needs a file change.

## Step 4: log in and sync

1. Open `http://127.0.0.1:5173` in the browser.
2. Go to Holdings and choose the Upstox tab.
3. Press "Log in to Upstox". Upstox opens its own login page. Enter your own login and one-time code there. Do not share them with anyone.
4. Approve the app if Upstox asks.
5. You should land back in the app with a notice that the Upstox login worked. If you land on a failure notice instead, record the notice text (not any code in the address bar).
6. Press "Sync portfolio". The holdings should appear, or an error message should show.

Upstox access tokens expire at about 03:30 IST (secondary sources; check the console or docs if this matters). If a later sync says login is required, log in again.

## Record the three outcomes

Copy this into your reply:

- (a) Redirect: accepted / rejected. If rejected, the console's exact message. If accepted, whether the login returned you to the app with a success notice.
- (b) Holdings: returned (number of rows and the time shown) / error (the exact message the app showed, or the Upstox page's text). Holdings values are fine to describe; do not send tokens or codes.
- (c) Static IP: demanded / not demanded. Demanded means the app shows "Upstox refused the request. Check the static IP setting for the app." That message comes from an HTTP 403 from Upstox.

## Fallbacks (from the design, not yet built unless stated)

A. The console rejects `127.0.0.1`. Try `http://localhost:8081/api/broker/upstox/callback` as the registered redirect URI. Then set `UPSTOX_REDIRECT_URI` to the same value in `.env` and restart the `ui` service. Note that this is a file change, so do it only if fallback A is needed. Check that the callback still reaches the server after the login.

B. The console rejects any local address. A single public HTTPS redirect that forwards to the server would be needed. This is not built. Stop and tell Claude which console message you saw.

C. The sync demands a static IP (outcome c). Check the static IP setting for the app in the console. Do not change your network to satisfy it without deciding that yourself. If a fixed IP is not possible, the design falls back to a manual CSV import for Upstox. That import is not built.
