# Upstox V3 API reference

Fetched 2026-11-09 from the Upstox developer docs. Index used: `https://upstox.com/developer/api-documentation/llms.txt`.

**Accuracy note:** the fetch tool returned condensed summaries, not byte-for-byte copies. Field names, numbers and codes below match those summaries and the protobuf file. Check the live page before writing code that depends on a field that is not exercised yet.

**Version note:** the API overview page (`/developer/api-documentation/api-overview/`) shows only `/v2/` base URLs and does not mention V3. V3 lives on its own sub-pages (listed in section 1). Market data feed V2 was shut down on 2025-08-22; use V3 only.

## 1. V3 endpoint index

| API | Method and path | Source page |
| :--- | :--- | :--- |
| Market Data Feed (WebSocket) | `WSS /feed/market-data-feed` | `/developer/api-documentation/v3/get-market-data-feed` |
| Market Data Feed Authorize | `GET /feed/market-data-feed/authorize` | `/developer/api-documentation/get-market-data-feed-authorize-v3` |
| Full Market Quotes | `GET /v3/market-quote/quotes` | `/developer/api-documentation/get-full-market-quote-v3` |
| LTP Quotes | `GET /v3/market-quote/ltp` | `/developer/api-documentation/ltp-v3` |
| OHLC Quotes | `GET /v3/market-quote/ohlc` | `/developer/api-documentation/get-market-quote-ohlc-v3` |
| Historical Candle Data | `GET /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}` | `/developer/api-documentation/v3/get-historical-candle-data` |
| Intraday Candle Data | `GET /v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}` | `/developer/api-documentation/v3/get-intra-day-candle-data` |
| Place Order | `POST https://api-hft.upstox.com/v3/order/place` | `/developer/api-documentation/v3/place-order` |
| Modify Order | `PUT https://api-hft.upstox.com/v3/order/modify` | `/developer/api-documentation/v3/modify-order` |
| Cancel Order | `DELETE https://api-hft.upstox.com/v3/order/cancel` | `/developer/api-documentation/v3/cancel-order` |
| Get Funds and Margin | `GET https://api.upstox.com/v3/user/get-funds-and-margin` | `/developer/api-documentation/get-funds-and-margin-v3` |

Order endpoints use `api-hft.upstox.com`. Market data and funds use `api.upstox.com`.

## 2. Authentication and headers

- Token: `Authorization: Bearer <access_token>`. Get it from the Token API. The standard token expires daily. The Analytics Token needs no daily re-login and covers market data and streaming.
- Typical headers: `Accept: application/json`, `Content-Type: application/json`.
- Get Funds and Margin also sends `Api-Version: 3.0`.
- Place Order accepts an optional `X-Algo-Name` header. It is required only for exchange-approved algo strategies, and its value must match an algo name configured in the app.
- Static IP: some endpoints reject requests from IPs that are not whitelisted (`UDAPI1154`). Order endpoints are the main case.

## 3. Market Data Feed V3 (WebSocket)

### 3.1 Connect

1. Call the Authorize endpoint (section 3.2) to get `data.authorized_redirect_uri`.
2. Open a WebSocket to that URL. The server replies with a 302 redirect to the authorized endpoint, so the client must follow redirects. The docs cite the Node.js `followRedirects` option. Our `createWsSocket` in `server/src/live/liveRoute.ts` has not been re-checked against this for this document.
3. The authorized URL is single-use (its `code` parameter is one-time). Call Authorize again for each new connection, including reconnects.
4. Keep the connection alive. The server sends WebSocket `ping` frames when there is no data. Most client libraries reply with `pong` automatically.

### 3.2 Authorize

- `GET https://api.upstox.com/v3/feed/market-data-feed/authorize`
- Headers: `Authorization: Bearer <access_token>`, `Accept: application/json`.
- Response: `status` and `data.authorized_redirect_uri` (a `wss://` URL).
- Query parameters: none.

### 3.3 Subscription requests (must be binary frames)

Send requests as **binary frames**, not text. Encode the JSON as bytes. A text frame gets no data. This was confirmed in our live test.

```json
{
  "guid": "13syxu852ztodyqncwt0",
  "method": "sub",
  "data": {
    "mode": "full",
    "instrumentKeys": ["NSE_INDEX|Nifty Bank"]
  }
}
```

| Field | Values |
| :--- | :--- |
| `guid` | Unique id per request |
| `method` | `sub` (subscribe; defaults to `ltpc` if no mode), `change_mode` (switch mode for already-subscribed keys; needs keys and target mode), `unsub` (stop keys) |
| `mode` | `ltpc`, `option_greeks`, `full` (5 depth levels), `full_d30` (30 depth levels) |
| `instrumentKeys` | Array of keys in `EXCHANGE|ISIN` or index form, for example `NSE_INDEX|Nifty Bank`, `NSE_INDEX|India VIX` |

Note: the protobuf `RequestMode` enum names the full-depth mode `full_d5` (value 1). The subscribe `mode` string is `full`. Use the string form in requests.

### 3.4 Subscription limits

| Tier | Connections per user | Single category (keys) | Combined categories (keys) |
| :--- | :--- | :--- | :--- |
| Standard | 2 | LTPC 5000, Option Greeks 3000, Full 2000 | LTPC 2000, Option Greeks 2000, Full 1500 |
| Upstox Plus | 5 | Full D30: 50 | Full D30: 1500 |

Our server caps live streams at 50 symbols (`MAX_LIVE_SYMBOLS`). That is our own limit, well under the feed limit. Raise it only if the UI needs more.

### 3.5 Message sequence

1. `market_info` (first message): segment status plus CAS and pre-open status.
2. `live_feed` snapshot (second message): current data at connect time.
3. `live_feed` updates: real-time ticks.

### 3.6 Protobuf schema (`MarketDataFeed.proto`)

Source: `https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto`. Package `com.upstox.marketdatafeederv3udapi.rpc.proto`, proto3, imports `google/protobuf/wrappers.proto`.

| Message | Fields (name = number, type) |
| :--- | :--- |
| `FeedResponse` | `type` = 1 (Type enum), `feeds` = 2 (map string→Feed), `currentTs` = 3 (int64), `marketInfo` = 4 (MarketInfo) |
| `Feed` | oneof `FeedUnion`: `ltpc` = 1 (LTPC), `fullFeed` = 2 (FullFeed), `firstLevelWithGreeks` = 3 (FirstLevelWithGreeks); `requestMode` = 4 (RequestMode) |
| `LTPC` | `ltp` = 1 (double), `ltt` = 2 (int64), `ltq` = 3 (int64), `cp` = 4 (double), `iep` = 5 (DoubleValue wrapper) |
| `FullFeed` | oneof `FullFeedUnion`: `marketFF` = 1 (MarketFullFeed), `indexFF` = 2 (IndexFullFeed) |
| `MarketFullFeed` | `ltpc` = 1, `marketLevel` = 2 (MarketLevel), `optionGreeks` = 3, `marketOHLC` = 4 (MarketOHLC), `atp` = 5 (double), `vtt` = 6 (int64), `oi` = 7 (double), `iv` = 8 (double), `tbq` = 9 (double), `tsq` = 10 (double), `iep` = 11 (double), `rp` = 12 (double), `ieq` = 13 (int64), `iiqTotal` = 14 (int64), `iiqM` = 15 (int64), `casEligible` = 16 (bool) |
| `IndexFullFeed` | `ltpc` = 1, `marketOHLC` = 2 |
| `FirstLevelWithGreeks` | `ltpc` = 1, `firstDepth` = 2 (Quote), `optionGreeks` = 3, `vtt` = 4 (int64), `oi` = 5 (double), `iv` = 6 (double) |
| `MarketLevel` | `bidAskQuote` = 1 (repeated Quote) |
| `Quote` | `bidQ` = 1 (int64), `bidP` = 2 (double), `askQ` = 3 (int64), `askP` = 4 (double) |
| `MarketOHLC` | `ohlc` = 1 (repeated OHLC) |
| `OHLC` | `interval` = 1 (string, for example `1d`, `I1`), `open` = 2, `high` = 3, `low` = 4, `close` = 5 (double), `vol` = 6 (int64), `ts` = 7 (int64) |
| `OptionGreeks` | `delta` = 1, `theta` = 2, `gamma` = 3, `vega` = 4, `rho` = 5 (double) |
| `MarketInfo` | `segmentStatus` = 1 (map string→MarketStatus), `casMarketStatus` = 2 (map string→StatusInfo), `preOpenSessionStatus` = 3 (map string→StatusInfo) |
| `StatusInfo` | `status` = 1 (string), `updatedTime` = 2 (int64, ms) |

Enums:
- `Type`: `initial_feed` = 0, `live_feed` = 1, `market_info` = 2.
- `RequestMode`: `ltpc` = 0, `full_d5` = 1, `option_greeks` = 2, `full_d30` = 3.
- `MarketStatus`: `PRE_OPEN_START` = 0, `PRE_OPEN_END` = 1, `NORMAL_OPEN` = 2, `NORMAL_CLOSE` = 3, `CLOSING_START` = 4, `CLOSING_END` = 5.

Our decoder (`server/src/live/feedDecoder.ts`) reads `FeedResponse.feeds` (field 2) and `Feed.ltpc` (field 1) → `LTPC` fields `ltp`, `ltt`, `cp`. Field numbers match. It also ignores `ltq`, `iep`, `marketInfo`, and the full and Greeks payloads.

### 3.7 Market status fields

- `market_info.marketInfo.segmentStatus`: map of segment → status (for example `NORMAL_OPEN`).
- `casMarketStatus` (present only in the closing auction window): `CTS_CLOSE`, `CAS_LM_START`, `CAS_M_STOP`, `CAS_STOP`.
- `preOpenSessionStatus` (present only in pre-open): `PRE_OPEN_START`, `PRE_OPEN_M_END`, `PRE_OPEN_END`.

### 3.8 Deprecated fields (effective 2024-10-10)

| Field | Action |
| :--- | :--- |
| `bidAskQuote.ano`, `bidAskQuote.bno`, `eFeedDetails.fp`, `eFeedDetails.fv`, `eFeedDetails.dhoi`, `eFeedDetails.dloi` | Removed. No replacement. |
| `bidAskQuote.aq` (int32) | Use `askQ` (int64). |
| `bidAskQuote.bq` (int32) | Use `bidQ` (int64). |
| `marketOHLC.ohlc[].volume` (int32) | Use `vol` (int64). |

### 3.9 Migration and V2 shutdown

- V3 launched with V2 available through 2025-03-02. V3 became the only feeder on 2025-03-03.
- V2 WebSocket discontinued on 2025-08-22 and fully shut down after that date.
- V3 adds: bulk subscription, market status on the first tick, market-level depth, option Greeks, improved OHLC.

## 4. Full Market Quotes V3

- `GET https://api.upstox.com/v3/market-quote/quotes?instrument_key=<keys>`
- `instrument_key`: comma-separated, **up to 500 keys per call**. Keys may be URL-encoded (`|` as `%7C`).
- Returns a snapshot taken from the exchange at request time.

Response: `status`, `data` keyed by `EXCHANGE:SYMBOL` (for example `NSE_EQ:NHPC`; index keys use `NSE_INDEX:Nifty 50`).

Per instrument:
- `ohlc`: `open`, `high`, `low`, `close`, `volume`, `ts` (candle start, ms).
- `depth`: `buy` and `sell`, each an array of 5 levels with `quantity`, `price`, `orders`.
- `timestamp` (ISO 8601 with offset), `instrument_token`, `symbol`.
- `last_price`, `volume`, `average_price`, `oi`, `net_change`.
- `total_buy_quantity`, `total_sell_quantity`, `lower_circuit_limit`, `upper_circuit_limit`.
- `last_trade_time` (ms as string), `oi_day_high`, `oi_day_low`.
- `prev_close_price`, `year_high`, `year_low`, `previous_oi` (F&O).
- CAS fields: `indicative_equilibrium_price`, `indicative_equilibrium_quantity`, `indicative_imbalance_quantity_total`, `indicative_imbalance_quantity_market`, `reference_price`, `cas_eligible`.

Errors: `UDAPI1009` (missing key), `UDAPI1011` (bad format), `UDAPI100011` (invalid key), `UDAPI100095` (key not accepted on this endpoint), `UDAPI100042` (over 500 keys).

## 5. LTP Quotes V3

- `GET https://api.upstox.com/v3/market-quote/ltp?instrument_key=<keys>` (comma-separated).
- Response per instrument: `last_price`, `instrument_token`, `ltq` (last traded quantity), `volume` (today, so far), `cp` (previous day close).
- Errors: `UDAPI1009`, `UDAPI1011`, `UDAPI1087` (invalid key), `UDAPI100043` (over the key limit; the number is not stated).

## 6. OHLC Quotes V3

- `GET https://api.upstox.com/v3/market-quote/ohlc?instrument_key=<keys>&interval=<value>`
- `interval`: `1d` (day), `I1` (1 minute), `I30` (30 minutes).
- Response per instrument: `last_price`, `instrument_token`, `prev_ohlc` (`open`, `high`, `low`, `close`, `volume`, `ts`), `live_ohlc` (same fields for the current candle).
- Errors: `UDAPI1009` (`symbol` missing), `UDAPI1011` (bad format), `UDAPI1027` (`interval` missing), `UDAPI1028` (bad interval), `UDAPI1087` (invalid key), `UDAPI100043` (over the key limit; number not stated).

## 7. Historical Candle Data V3

- `GET https://api.upstox.com/v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}`
- Path parameters:
  - `instrument_key` (required, Field Pattern Appendix format).
  - `unit` (required): `minutes`, `hours`, `days`, `weeks`, `months`.
  - `interval` (required): depends on unit.
  - `to_date` (required, inclusive, `YYYY-MM-DD`).
  - `from_date` (optional, `YYYY-MM-DD`, must not be later than `to_date`).

| Unit | Interval | History from | Max window |
| :--- | :--- | :--- | :--- |
| minutes | 1–300 | Jan 2022 | 1 month for 1–15 min; 1 quarter for >15 min |
| hours | 1–5 | Jan 2022 | 1 quarter up to `to_date` |
| days | 1 | Jan 2000 | 1 decade up to `to_date` |
| weeks | 1 | Jan 2000 | No limit |
| months | 1 | Jan 2000 | No limit |

- Response: `status`, `data.candles`. Each candle is a 7-item array: `[timestamp (ISO 8601 +05:30), open, high, low, close, volume, open_interest]`.
- Errors: `UDAPI1021` (bad key format), `UDAPI1022` (`to_date` missing), `UDAPI100011` (key not recognized), `UDAPI1015` (`to_date` before `from_date`, or bad date format), `UDAPI1146` (bad unit), `UDAPI1147` (bad interval for unit), `UDAPI1148` (date range too large for the interval).
- Newer V3 additions: custom intervals; global indices, global indicators (for example USD INR, Brent, WTI); India VIX (`NSE_INDEX|India VIX`).

## 8. Intraday Candle Data V3

- `GET https://api.upstox.com/v3/historical-candle/intraday/{instrument_key}/{unit}/{interval}`
- Current trading day only.
- `unit`: `minutes`, `hours`, `days`. `interval`: minutes 1–300, hours 1–5, days 1.
- Response: same 7-item candle array as section 7.
- Errors: `UDAPI1021`, `UDAPI100011`, `UDAPI1146` (bad unit), `UDAPI1147` (bad interval).

## 9. Place Order V3

- `POST https://api-hft.upstox.com/v3/order/place`
- Headers: `Content-Type`, `Accept`, `Authorization`, optional `X-Algo-Name`.

Body:

| Field | Required | Type | Values and notes |
| :--- | :--- | :--- | :--- |
| `quantity` | Yes | int32 | Lots for commodities; units in tick-size multiples for F&O and equity |
| `product` | Yes | string | `I` (intraday), `D` (delivery), `MTF` |
| `validity` | Yes | string | `DAY` (default), `IOC` |
| `price` | Yes | float | Order price |
| `tag` | No | string | Max 40 characters |
| `instrument_token` | Yes | string | From the BOD instruments file |
| `order_type` | Yes | string | `MARKET`, `LIMIT`, `SL`, `SL-M` |
| `transaction_type` | Yes | string | `BUY`, `SELL` |
| `disclosed_quantity` | Yes | int32 | Quantity shown in depth |
| `trigger_price` | Yes | float | For stop-loss orders |
| `is_amo` | No | bool | Ignored; the system infers AMO from the session |
| `slice` | No | bool | Default `false`. `true` splits by the exchange freeze quantity |
| `market_protection` | No | int32 | Default `-1` (automatic). `1`–`25` = custom %. `0` = none. Only for `MARKET` and `SL-M` |

- Response (200): `status`, `data.order_ids` (array), `metadata.latency` (ms).
- Errors (selected): `UDAPI1026` (key missing), `UDAPI1004` (order type missing), `UDAPI1056` (bad order type), `UDAPI1057` (bad transaction type), `UDAPI1006` (product missing), `UDAPI1054` (bad product), `UDAPI1007` (validity missing), `UDAPI1055` (bad validity), `UDAPI1008` (price missing), `UDAPI100049` (API restricted for account; needs Uplink Business), `UDAPI1052` (quantity zero), `UDAPI1040` (price not allowed for order type), `UDAPI1043` (price required), `UDAPI1041` (price and trigger both required), `UDAPI1042` (only trigger required), `UDAPI1037` (trigger must be below limit), `UDAPI1038` (trigger must be above limit), `UDAPI100011` (invalid key), `UDAPI100039` (AMO during market hours), `UDAPI100074` (API only 05:30–00:00 IST), `UDAPI1118` (slicing exceeds max orders), `UDAPI1119` (tag over 40 chars), `UDAPI1154` (non-whitelisted static IP), `UDAPI1156` (bad `X-Algo-Name`), `UDAPI1158` (market orders blocked; use limit or market protection), `UDAPI1159` (market protection over 25%), `UDAPI1160` (bad market protection), `UDAPI1161` (MCX via API disabled).

## 10. Modify Order V3

- `PUT https://api-hft.upstox.com/v3/order/modify`
- Omitted optional fields keep the original order's values.

| Field | Required | Type | Values |
| :--- | :--- | :--- | :--- |
| `order_id` | Yes | string | Field Pattern Appendix format |
| `quantity` | No | int32 | |
| `validity` | Yes | string | `DAY`, `IOC` |
| `price` | Yes | float | |
| `order_type` | Yes | string | `MARKET`, `LIMIT`, `SL`, `SL-M` |
| `disclosed_quantity` | No | int32 | Non-zero if sent; at least 10% of quantity (`UDAPI1039`) |
| `trigger_price` | Yes | float | |
| `market_protection` | No | int32 | `MARKET` and `SL-M` only. `-1` automatic, `1`–`25` custom, `0` rejected for API market orders |

- Response: `status`, `data.order_id`, `metadata.latency`.
- Errors (selected): `UDAPI1004`, `UDAPI1007`, `UDAPI1056`, `UDAPI1055`, `UDAPI1008`, `UDAPI1036` (trigger missing), `UDAPI1030` (price not allowed for type), `UDAPI1029` (price missing for type), `UDAPI1031`, `UDAPI1032`, `UDAPI100049`, `UDAPI100010` (order not found), `UDAPI100041` (cancelled, rejected or completed orders cannot change), `UDAPI1039`, `UDAPI1003` (order id missing), `UDAPI1154`, `UDAPI1156`, `UDAPI1158`, `UDAPI1159`, `UDAPI1160`, `UDAPI1161`.

## 11. Cancel Order V3

- `DELETE https://api-hft.upstox.com/v3/order/cancel?order_id=<id>`
- Response: `status`, `data.order_id`, `metadata.latency`.
- Errors: `UDAPI1023` (order id missing), `UDAPI1010` (bad characters; letters, digits and hyphens only), `UDAPI100049`, `UDAPI100010` (not found), `UDAPI100040` (already cancelled, rejected or completed), `UDAPI1154`, `UDAPI1156`.

## 12. Get Funds and Margin V3

- `GET https://api.upstox.com/v3/user/get-funds-and-margin`
- Headers: `Accept: application/json`, `Api-Version: 3.0`, `Authorization`.
- No query parameters.
- Response: `status` (`success` or `error`) and `data` with three groups: `available_to_trade`, `margin_used`, `unavailable_to_trade`, plus `cash` and `margin_from_pledge`.
- Key fields:
  - `available_to_trade.total`, `available_to_trade.cash_available_to_trade.total`, `available_to_trade.pledge_available_to_trade.total`.
  - `cash.opening_balance`, `cash.added_today`, `cash.withdrawn_today`, `cash.amount_from_stock_sale`, `cash.unpaid_charges`.
  - `margin_used.*`: `total`, `mtf`, `loss` (`total`, `realised`, `unrealised`), `span_exposure`, `cash_margin_var_elm`, `premium_present`, `delivery_margin` (`total`, `equity`, `fo_settlement`).
  - `margin_from_pledge.total`, `equity`, `mutual_funds`.
  - `unavailable_to_trade.cash_unavailable_to_trade.unsettled_profit` (`todays_profit`, `previous_days`), `unavailable_to_trade.pledge_unavailable_to_trade` (`equity`, `mutual_funds`).
- Errors: `UDAPI100072` (called outside service hours). Service is down 00:00–05:30 IST; it returns `423 Locked` during that window.

## 13. Cross-cutting rules

- **Service hours:** order and funds APIs run 05:30–00:00 IST (`UDAPI100074`, `UDAPI100072`).
- **Static IP:** `UDAPI1154` on order and some account endpoints if the IP is not whitelisted.
- **Restricted accounts:** `UDAPI100049` on order endpoints means the account needs Uplink Business.
- **MCX via API:** `UDAPI1161` means disabled for now.
- **Rate limits:** the detail is on `/developer/api-documentation/rate-limiting`. Not fetched yet.
- **Instrument keys:** format `EXCHANGE|ISIN` (equity) and `EXCHANGE|name` (index). Field Pattern Appendix defines the regex.

## 14. Open items

- Rate limits page: not fetched.
- Protobuf: pulled from the summarized `.proto` text; verify field numbers against the raw file before the next decoder change.
- Market data feed key limits are now documented (section 3.4). The Full Market Quotes and LTP key caps still need the exact numbers (the error code exists; the number is not stated).
- Error body formats for 4XX responses are not documented on several pages.
