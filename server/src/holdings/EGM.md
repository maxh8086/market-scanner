# holdings

## Overview
Zerodha Kite holdings fetch and parse. Credentials are supplied by the caller,
and the module returns a normalised holdings result.

## Interface
- `kiteHoldings.ts`: `fetchKiteHoldings`, `parseKiteHoldings`, and the types
  `Holding`, `KiteFetch`, `KiteFetchResponse`, `KiteHoldingsOptions`,
  `KiteHoldingsResult`. `KITE_HOLDINGS_URL` is the endpoint constant.
- `kiteHoldings.test.ts`: test suite (not part of the interface).

## Invariants
- `parseKiteHoldings` is a pure function. The network call is isolated in
  `fetchKiteHoldings`, so parsing is testable without the network.
- Access tokens are passed in per call. They are never stored in this module.

## Side Effects
- One outbound HTTPS request to the Kite holdings endpoint per call.

## Verification
- Run: `npm test` in `server/` (covers `kiteHoldings.test.ts`).
