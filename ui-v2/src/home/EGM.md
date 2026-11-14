# home

## Overview
The Home filings block. `HomeEventFeed` sits above the screener table and
shows the stored filings from `GET /api/events` in two groups: High priority
and Catalyst, with an Other group only when a row has an unknown tier.

## Interface
- `HomeEventFeed.tsx`: `HomeEventFeed` (no props), `EVENTS_REFRESH_MS`
  (300000 ms), `EVENT_TYPE_LABELS`, `TIER_LABELS`, `relativeAge`,
  `safeSourceUrl`.
- Tests: `*.test.tsx` beside the component (not part of the interface).

## Invariants
- The block fetches through `api/events.ts` only. The browser never reaches
  the events database.
- The "Events as of" stamp comes from the response's `latest_fetched_at`. Ages
  are computed against the response's `generated_at`. Neither uses the
  browser clock for display.
- Headlines, company names and every other field are third-party text. They
  render as React text only. A source link is shown only for an http or https
  URL; any other value shows "Source unavailable".
- A refetch that fails after a success keeps the rows on screen. Only the first
  load can show the error state. The block never throws into its parent.
- Unknown event types show the raw stored value; a null type shows "Filing".

## Side Effects
- One request on mount, then one every `EVENTS_REFRESH_MS` while the document
  is visible, and one on becoming visible when the last fetch is older than the
  interval. The timer, the `visibilitychange` listener and any in-flight request
  are released on unmount.

## Verification
- Run: `npm test` in `ui-v2/` (covers `HomeEventFeed.test.tsx`).
