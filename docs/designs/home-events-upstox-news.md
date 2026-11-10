# Home events: Upstox News (per stock)

Status: stub. OFF (not registered and not run; D9 covers enforcement). Blocked until Upstox confirms in writing (A6). Not registered until unblocked (A3). Detail is written only after the licence gate clears (A6).

Values owner: overview section 5.4 ([home-event-sources.md](home-event-sources.md)) owns the Upstox values until the build spec is approved (A4). D10 covers any owner question beyond A4.

Decisions file: `docs/progress/home-events-decisions-needed.md` (sections A and D).

Screen: Home, shortlist and event feed (`docs/designs/ui-redesign-spec.md` section 5.1, section 6).

## Scope

- Per-stock news from the Upstox News endpoint, as the overview describes it (section 5.4).
- This stub holds only what is decided below, plus values marked proposed. Everything else waits for the build spec.
- Licence and Home feed rules stay in the overview (sections 4, 7.1, 7.2).

## Decided and proposed

Tags: decided (accepted in the decisions file), proposed (not decided), open (not answered).

- Route: `POST /internal/events/intake/upstox` (decided, A1; name proposed in overview 6.3). Each source has its own ingest route.
- Ingest token: role `upstox_news_ingest` (A1; proposed, not built). Each source has its own ingest token. Role rows are in `secrets-and-roles.md`. The News call uses `upstox_analytics_token` (overview sections 3 and 5.4), not the ingest token.
- Schedule: one daily run (decided, A2), after the exchange-filings poll window ends at 20:55 IST (overview 7.3). Run time: proposed at 21:30 IST, to confirm.
- Rate limits: the schedule relies on the client's 429 handling, and a 403 or 429 also starts the shared `upstox` cooldown (A2 status, 2026-11-10). The News page rate-limit class is unchecked. The gap and cap numbers stay open (overview 8.2 items 9 and 19).
- Downtime and cooldown: a host off for longer than the 7-day window (the 1-week age limit, D5) loses items older than that window (overview 5.4). Upstox has a cooldown. A 403 or 429 from News writes the shared `upstox` row in `source_cooldown` (renamed from `exchange_cooldown`, decided 2026-11-10), and every Upstox caller backs off for it (collector-split 4.3 and 4.3a, decided 2026-11-10). The user said on 2026-11-10 that Upstox is an API host with a per-second limit, so it can retry within minutes. Backoff class: API class (`upstox`, `fred`): start at 3 minutes, double to 6 minutes, cap at 15 minutes (user, 2026-11-10). The backoff values are written by split S2, not here. This supersedes the Upstox clause of A2. The split-spec owner (the user) confirms the values; decisions file E4 is resolved 2026-11-10.
- Registration: Upstox is not in `SOURCES` (scanner/collect/sources.py:616) or in `config/collector_services.json` (planned by the collector-split spec) until its blocker clears (A3).
- Retention: terminal `event_intake` rows (`rejected`, `expired`) are kept 30 days (decided, overview 8.2 item 3; A7).
- Build order: Upstox is last. It waits for the LLM relevance stage, so nothing reaches `news_events` or the API before that stage exists (A5), and it waits for the licence answer.

## Blocked by

1. Licence gate: written confirmation from Upstox that News may be stored and shown for personal use (A6). Not received. Nothing is enabled before it is recorded in the overview (sections 4.1 and 8.2 item 18).
2. Sample capture: A6 accepts one redacted live sample now, kept out of git, with nothing enabled by it. Not captured yet.
3. Terms gate: the Upstox API terms and developer agreement are not read and recorded (overview 8.2 item 15; A6). Nothing is enabled before that record exists.

## Open questions (pointers only, no answers)

D1 to D10 are in the decisions file, section D. The item on line 49 has no number in that file yet.

- D1: feed tier and event type for Upstox items.
- D2: attribution when an item has no instrument key (the per-stock key, overview 5.4), and what empty data means.
- D3: dedupe key and a seen-links store.
- D4: resolved 2026-11-10 as `UpstoxClient._get` (scanner/upstox.py), because it supports every required feature (decisions file, D4). Two checks stay in the live capture: the request headers on the News call, and the 403 discriminator (D7).
- D5: the 1-week age limit.
- D6: universe and first-poll size.
- D7 and D8: error handling. D7 covers a 403 from Cloudflare (the web-protection layer in front of the host) versus an auth failure. D8 covers request timeout, HTTP 5xx retry, how a batch failure (one request covering several keys) appears, and the News-page rate-limit class check (overview 8.2 item 19).
- D9: how OFF is enforced beyond A3. The decisions file gives a recommended answer (specs may be written while it is disabled); it is not decided.
- D10: owner of the Upstox values beyond A4.
- Ingest token location, and the events API base-URL setting (`EVENTS_API_BASE_URL`): open, not decided. `secrets-and-roles.md` points here for this item.

## Related docs

- `home-events-news-telegram.md`: `event_intake` and `news_events` tables, and the relevance stage.
- `collector-split-spec.md`: run-once containers and the scheduler.
- `home-events-filings-spec.md`: events database, ingest token pattern, purge.
- `secrets-and-roles.md`: role rows and the token pattern for each ingest route.

## Removed in this stub

The Upstox endpoint name and URL, request shape, field tables, batch sizes and rate limits are removed from this doc. They remain in git history at commit 729e093 on branch `docs/home-events-decisions` (`git show 729e093:docs/designs/home-events-upstox-news.md`) and return in the build spec after the gate.
