# NEW-HOME-FEED contract addendum (draft, unreviewed)

Status: approved 2026-11-14 (Q1 hold shortlist, Q2 7 days, Q3 both groups). The EGM review lenses were not run, so the design is unreviewed.

Sources read: `ui-redesign-spec.md` 5.1, 7.1 to 7.2 (`home-event-sources.md` lines 160 to 176 for the cap), `home-events-filings-spec.md` 4.6, `db/events_migrations/001` and `002`, `server/src/results.ts`, `ui-v2/src/api/results.ts`.

## 1. Scope of the first slice

Filings only (the eight NSE feeds already stored in `home_events`). Two parts, built in this order, one writer at a time:

- **A. Server:** `GET /api/events` and the events read grant.
- **B. UI:** a Home event feed above `ScreenerTable` in `ui-v2`. The shortlist is held (decision Q1, section 7).

Out of scope: the stock-tab events section, the Events screen (5.4), alerts, the LLM stage, any write route, paging beyond one page.

## 2. Findings that change the plan

1. **A migration is needed.** The plan says "No database migration", but `db/events_migrations/002_server_role_grants.sql` grants only `INSERT` on `home_events` to `market_scanner_server`. A read route needs `SELECT`. Add `db/events_migrations/003_server_role_select_grant.sql` (`GRANT SELECT ON home_events TO market_scanner_server;`), with a down note. Written, not applied; you apply it.
2. **One database.** With the shortlist held, the route reads only the events database. `AppDeps` gains `eventsQuery?: QueryFn` (read-only, built from the existing `eventsPool` in `index.ts`). Without it the route is not registered. The main-database `query` is not used.
3. **Tiers.** The spec says "tier 1 and tier 2"; the stored column is `feed_tier` with `high_priority` and `catalyst`. The API exposes `feed_tier` as stored. High priority is the top stream, catalyst the secondary one (`home-event-sources.md` lines 160 to 163).
4. **Shortlist held (your decision, Q1).** Spec 7.2 needs an ATH match, UPTREND and at least one of `bonus_issue`, `demerger`, `orderbook_signal`, `expansion_signal`. The filings slice produces none of those factors, and their stored value encodings are not documented. The response has no `shortlist` field and the UI has no chips. To unlock it later: document the factor value encodings in `stock_snapshots.metrics`, then add a `shortlist` field in a follow-up contract (the join would use the current run's snapshots on `isin`).

## 3. `GET /api/events` (part A)

Registered in `server/src/app.ts` next to the other read routes, in a new `server/src/eventsRead.ts` (pure SQL builder, like `results.ts`) and `eventsReadRoute.ts`. Like every `/api/*` read except the exempt paths in `session.ts`, it needs a live session (the same gate as `/api/results`); the CSRF checks apply to writes only. Route tests use `sessionTestHelper.ts`.

Query params (all optional; unknown params are ignored; invalid values answer 400 `invalid_query`):

| Param | Rule | Default |
| :--- | :--- | :--- |
| `days` | integer 1 to 30, window back from now | 7 |
| `tier` | `high_priority` or `catalyst` | both |
| `limit` | integer 1 to 200, events returned after the cap | 100 |
| `symbol` | NSE symbol, upper-cased, `^[A-Z0-9&-]{1,20}$`, no 3-per-stock cap | none |

Events SQL (events pool, parameter placeholders only):

```sql
SELECT dedupe_key, symbol, isin, company, event_type, feed_tier, feed_code,
       headline, published_at, fetched_at, source_url
FROM (
  SELECT *, row_number() OVER (PARTITION BY isin ORDER BY published_at DESC) AS rn
  FROM home_events
  WHERE published_at >= now() - make_interval(days => $1)
    AND ($2::text IS NULL OR feed_tier = $2)
    AND ($3::text IS NULL OR symbol = $3)
) t
WHERE ($3::text IS NOT NULL OR rn <= 3)
ORDER BY (feed_tier = 'high_priority') DESC, published_at DESC
LIMIT $4;
```

The 3-per-stock cap is a display cap only (spec): rows stay stored and a `symbol` query returns all.

Response `200`, `Cache-Control: no-store`:

```json
{
  "generated_at": "2026-11-14T20:15:00+05:30",
  "latest_fetched_at": "2026-11-14T20:10:03+05:30",
  "window_days": 7,
  "events": [
    {"id": "<dedupe_key>", "symbol": "ABC", "isin": "INE000A01010", "company": "ABC Ltd",
     "event_type": "results", "feed_tier": "high_priority", "feed_code": "Sast_Regulation31",
     "headline": "...", "published_at": "2026-11-14T18:00:00+05:30",
     "fetched_at": "2026-11-14T18:05:02+05:30", "source_url": "https://..."}
  ]
}
```

- Timestamps are ISO with the IST offset (reuse `toIstIso`). `latest_fetched_at` is the newest `fetched_at` in the window across all stored rows (null when none); the UI shows it as the data-age stamp, never the browser clock.

Errors: `400 {"error":"invalid_query"}`; `503 {"error":"events_database_unavailable"}` for a connection error on the events pool (reuse `isConnectionError`); `500 {"error":"internal_error"}`. Fixed bodies, no error text, `no-store`.

Headlines and company names are third-party text: stored and returned verbatim, rendered only as text by the UI. `source_url` is http or https by ingest validation; the UI still checks the scheme before linking.

## 4. Home block (part B), `ui-v2`

- `ui-v2/src/api/events.ts` (pattern of `results.ts`): `buildEventsQueryString`, `fetchEvents(query, {signal})`, `EventsError` with `status`, type guards for the body (reject on a bad shape).
- `ui-v2/src/home/HomeEventFeed.tsx` mounted above `ScreenerTable`. Two groups, "High priority" and "Catalyst", each a list of `EventRow` (company, event type label, headline, relative time from the event's own `published_at` against `generated_at`, source link `rel="noopener noreferrer" target="_blank"`). Cap shown by the server.
- No shortlist chips in this slice (held, Q1).
- Header stamp: "Events as of <latest_fetched_at>", read from the response, not `Date.now()`.
- States through the existing `StateView`: loading, empty ("No filings in the last 7 days"), error (503 shows "Events database unavailable", others a generic line). The block's failure never blocks the table.
- Refetch on mount and every 5 minutes while the tab is visible; abort on unmount.
- Event type and tier labels come from one map in the component file; an unknown value shows the raw value.
- No new dependency, no browser access to Postgres, Mongo or Upstox (all data through the API).

## 5. Tests (written by Haiku, run by Sonnet)

- Server: SQL builder (placeholders only, defaults, bounds, `symbol` regex, cap bypass for `symbol`); route with a fake `eventsQuery` (200 shape, `latest_fetched_at` null on empty, `invalid_query` cases, 503 on a connection error, 500 on other errors, no error text or secret in any error body, no-store header, session required, route absent without `eventsQuery`); `index.ts` wiring assertion (`eventsQuery` built from `eventsPool`).
- Migration file 003 test in the style of `tests/test_migration_050_internal_due_grants.py` (grants only `SELECT` on `home_events` to `market_scanner_server`, no role created).
- UI: client (query string, bad body, abort), component (both groups shown, empty, error 503, link scheme check, stamp from the response).

## 6. Dispatch plan and limits

1. Part A, one Haiku task: files `server/src/eventsRead.ts`, `eventsReadRoute.ts`, their tests, `app.ts` and `index.ts` wiring, `db/events_migrations/003_*.sql`, its down note and test, `CHANGELOG.md`. Acceptance: `(cd server && npx tsc --noEmit)`, `(cd server && npm test)`, the migration test. Must not change: ingest route, auth, `eventsTx.ts`, existing routes.
2. Part B after A merges (server first, then UI): one Haiku task, files under `ui-v2/src/api/events.ts`, `ui-v2/src/home/`, mount in the Home screen, tests, CHANGELOG. Acceptance: the `ui-v2` test and type-check commands (read its `package.json` first).
3. Sonnet reviews each diff and runs the checks before each commit and PR.

Not verifiable without you: the route against a real events database (needs 003 applied and rows present) and how the block looks in a browser at your data sizes.

## 7. Questions for you

- **Q1 shortlist: decided 2026-11-14.** Hold the shortlist until the factor fields can be read (see 2.4).
- **Q2 default window: decided 2026-11-14.** 7 days.
- **Q3 groups: decided 2026-11-14.** Show both groups on Home.
