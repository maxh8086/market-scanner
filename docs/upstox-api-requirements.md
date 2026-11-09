# Upstox API requirements (Market Scanner reference)

Last updated: 2026-11-09. Source: Upstox developer docs pasted into the session (Market Data Feed V3, Authorize V3, Full Market Quotes V3, LTP V3). Re-check the live docs before relying on any limit not marked as verified.

## 1. Authentication and tokens

- Every REST call sends `Authorization: Bearer <access_token>`, plus `Accept: application/json`. `Content-Type: application/json` is sent in the docs samples.
- The server reads `UPSTOX_ACCESS_TOKEN` first, then falls back to `UPSTOX_ANALYTICS_ACCESS_TOKEN` (the token the Python pipeline already uses). Verified: the analytics token gets HTTP 200 from the authorize endpoint and streams market-data frames.
- Never put tokens in source, logs, or chat. Keep them in `.env` (see `env.template`).
- Access tokens expire daily. An expired token returns an auth error; the live feed then shows as unavailable until a new token is set.

## 2. Market Data Feed V3 (WebSocket, live ticks)

### 2.1 Authorize

- `GET https://api.upstox.com/v3/feed/market-data-feed/authorize` with the Bearer token.
- Response: `data.authorized_redirect_uri` is a single-use `wss://wsfeeder-api.upstox.com/...` URL. Get a new one for each connection. Do not reuse it.

### 2.2 Connecting

- Open the WebSocket on `authorized_redirect_uri`. Our code uses the `ws` package in `server/src/live/liveRoute.ts` (`createWsSocket`).

### 2.3 Subscribe (required binary frame)

- Send the subscribe request as a **binary** frame, not a text frame. The docs say it "should be sent in binary format, not as a text message." A text frame gets no ticks.
- Payload (JSON, then encoded as bytes):
  ```json
  { "guid": "<unique id>", "method": "sub", "data": { "mode": "ltpc", "instrumentKeys": ["NSE_EQ|INE002A01018"] } }
  ```
- Modes used: `ltpc` (last traded price and close). Other modes exist in the docs (for example full depth) and are not used yet.
- Instrument keys use the format `EXCHANGE|ISIN`, for example `NSE_EQ|INE002A01018` (RELIANCE). Our server maps trading symbols to ISINs from the `stock_snapshots` table and builds `NSE_EQ|<ISIN>`.
- Feed-side limits (standard tier): 2 connections per user; 5000 keys in LTPC mode, 3000 in Option Greeks, 2000 in Full, per subscription category. Combined-category caps are lower (LTPC 2000, Greeks 2000, Full 1500). Full depth D30 is Plus-tier only. Full detail: `docs/upstox-v3-api.md` section 3.4.
- Our own cap: the server caps live streams at 50 symbols (`MAX_LIVE_SYMBOLS`, mirrored in `ui-v2/src/live/useLiveTicks.ts`). This is well under the feed limits.

### 2.4 Frame order and decoding

- Frames are protobuf (`FeedResponse`). Field numbers used: `type`=1, `feeds`=2 (map keyed by instrument key), `currentTs`=3, `marketInfo`=4.
- Sequence: a `market_info` frame first (type 2), then a snapshot, then `live_feed` updates.
- We read `feeds[instrumentKey].ltpc` (`ltp`, `ltt`, `cp`). `ltt` is documented as a string; the decoder reads it as a number. Verified: decoded `ltt` values are millisecond timestamps for the current session.
- Ticks with `ltp <= 0` are dropped. `ltt` or `cp` of 0 become null.

### 2.5 Verified behaviour (2026-11-09, market hours)

- Subscribe as text: stream reached `live`, zero ticks in 25 seconds. Root cause: text frame.
- Subscribe as binary: 244 tick events in 45 seconds for RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK (`/api/live/ticks`). Status sequence: `connecting` → `live`.

### 2.6 Session and connection rules (our policy)

- Stream only during the open session, 09:15 to 15:30 IST (`ui-v2/src/App.tsx`, `liveEnabled`).
- Reconnect with backoff; the UI shows a reconnecting caution state while retrying.
- Heartbeat: the server sends `: ping` every 15 seconds on the SSE stream.

## 3. Full Market Quotes V3 (REST snapshot)

- `GET https://api.upstox.com/v3/market-quote/quotes?instrument_key=<keys>`
- `instrument_key` is comma-separated, **up to 500 keys per call** (error `UDAPI100042` if exceeded).
- Keys can be URL-encoded (`|` as `%7C`). Both `NSE_EQ|INE...` and `NSE_EQ%7CINE...` appear in the docs samples.
- Response: `data` is keyed by `EXCHANGE:TRADING_SYMBOL` (for example `NSE_EQ:NHPC`). Index keys use a colon, for example `NSE_INDEX:Nifty 50`.
- Fields per instrument: `ohlc` (open, high, low, close, volume, ts), `depth` (top 5 buy and sell levels with quantity, price, orders), `timestamp` (ISO 8601 with offset), `instrument_token`, `symbol`, `last_price`, `volume`, `average_price`, `oi`, `net_change`, `total_buy_quantity`, `total_sell_quantity`, `lower_circuit_limit`, `upper_circuit_limit`, `last_trade_time` (ms string), `oi_day_high`, `oi_day_low`, `prev_close_price`, `year_high`, `year_low`, `previous_oi`.
- Closing auction session (CAS) fields: `indicative_equilibrium_price`, `indicative_equilibrium_quantity`, `indicative_imbalance_quantity_total`, `indicative_imbalance_quantity_market`, `reference_price`, `cas_eligible`.
- Error codes: `UDAPI1009` (missing key), `UDAPI1011` (bad format), `UDAPI100011` and `UDAPI100095` (invalid or not allowed on this endpoint), `UDAPI100042` (more than 500 keys).
- New instruments: Global indices (for example GIFT NIFTY, Dow Jones, S&P, FTSE 100; keys in the Global Instruments file) and India VIX (`NSE_INDEX|India VIX`).

## 4. LTP V3 (REST last traded price)

- `GET https://api.upstox.com/v3/market-quote/ltp?instrument_key=<keys>` (comma-separated).
- Response per instrument: `last_price`, `instrument_token`, `ltq` (last traded quantity), `volume` (day volume so far), `cp` (previous day close).
- Error codes: `UDAPI1009` (missing key), `UDAPI1011` (bad format), `UDAPI1087` (invalid key), `UDAPI100043` (too many keys; the docs do not state the number, so check before using large batches).
- Use this endpoint for a cheap snapshot when the WebSocket is not streaming (for example after hours). It is not used yet.

## 5. Common response shape and errors

- Success responses: `{ "status": "success", "data": { ... } }`.
- Error responses: non-2xx status with an error code such as `UDAPI1009`. Log the code and the request shape, never the token.

## 6. Known gaps and open items

- Feed-side key limits: now documented in section 2.3 and `docs/upstox-v3-api.md` section 3.4.
- REST V3 endpoints (quotes, LTP, OHLC, historical and intraday candles, orders, funds): summarized in `docs/upstox-v3-api.md`. Those pages were fetched as condensed summaries, not verbatim text.
- Token refresh: the docs pasted here do not cover the token-generation (OAuth) flow. Tokens are created outside this app.
- Rate limits: not fetched yet (`/developer/api-documentation/rate-limiting`). Fetch before adding polling.
- Market hours on the feed side: the server enforces 09:15 to 15:30 IST on the client; the feed itself may send nothing outside those hours.

## 7. Where this lives in the code

- `server/src/live/upstoxFeed.ts`: authorize, subscribe (binary), reconnect, `createLiveFeed`.
- `server/src/live/liveRoute.ts`: `createWsSocket`, ISIN lookup, SSE route wiring.
- `server/src/live/feedDecoder.ts`: protobuf decode of `FeedResponse`.
- `server/src/app.ts`: `GET /api/live/ticks` (SSE, `status` and `tick` events).
- `server/src/index.ts`: token selection (`UPSTOX_ACCESS_TOKEN` then analytics fallback).
- `ui-v2/src/live/useLiveTicks.ts`: EventSource client, 250 ms batching.
