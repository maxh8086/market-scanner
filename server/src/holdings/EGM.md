# holdings

## Overview
Broker holdings fetch and parse for Zerodha Kite and Upstox. Credentials are
supplied by the caller, and each module returns a normalised holdings result.
Both brokers map onto the same `Holding` shape and result union, so the stored
snapshot is one shape for both.

## Interface
- `kiteHoldings.ts`: `fetchKiteHoldings`, `parseKiteHoldings`, and the types
  `Holding`, `KiteFetch`, `KiteFetchResponse`, `KiteHoldingsOptions`,
  `KiteHoldingsResult`. `KITE_HOLDINGS_URL` is the endpoint constant. The
  `Holding` type and `KiteHoldingsResult` union are shared by the Upstox module.
- `kiteHoldings.test.ts`: test suite (not part of the interface).
- `upstoxHoldings.ts`: `fetchUpstoxHoldings` (`accessToken`, `fetch`),
  `parseUpstoxHoldings`, and `UPSTOX_HOLDINGS_URL` (the v2 long-term holdings
  endpoint). It imports `Holding`, `KiteFetch` and `KiteHoldingsResult` from
  `kiteHoldings.ts` and does not copy them.
- `upstoxHoldings.test.ts`: test suite (not part of the interface).

## Invariants
- `parseKiteHoldings` and `parseUpstoxHoldings` are pure functions. The network
  call is isolated in each `fetch*` function, so parsing is testable without the
  network.
- Upstox maps `trading_symbol` to `symbol` and `day_change_percentage` to
  `dayChangePct`. A row without a symbol or a numeric quantity is skipped.
  Missing numbers default to 0, and missing day change to null, as for Kite.
- Upstox status mapping: 401 is login expired (`status` 401); 403 is the static
  IP message (`status` 403, unverified cause); other non-2xx is 502. Errors
  never include the response body or the token.
- Access tokens are passed in per call. They are never stored in this module.

## Side Effects
- One outbound HTTPS request to the broker holdings endpoint per call (Kite or
  Upstox).

## Verification
- Run: `npm test` in `server/` (covers `kiteHoldings.test.ts` and
  `upstoxHoldings.test.ts`). The tests mock `fetch`; nothing reaches a broker.
