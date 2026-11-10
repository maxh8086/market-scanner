# Home events: Upstox News (per stock)

Status: draft, not approved. Storage route decided 2026-11-10 (overview 6.3). Per-source route and token decided 2026-11-10 (decision A1 in `docs/progress/home-events-decisions-needed.md`). Build specs are not written yet. Review: `docs/progress/home-events-upstox-news-review.md`. Only 2 of 6 lenses have run, so the review is not complete. Open user decisions: `docs/progress/home-events-upstox-news-decisions.md`.
Owner: Vaibhav Pavtekar
Screen: Home, shortlist and event feed (`docs/designs/ui-redesign-spec.md` section 5.1, section 6)
Overview: [home-event-sources.md](home-event-sources.md). Licence and Home feed rules are owned by the overview (sections 4, 7.1, 7.2). The retention value is in overview 7.4. The purge design is in `home-events-filings-spec.md` section 5.5 (deferred); the filings doc (`home-events-filings.md`) owns it by overview section 2.

Status words used in this doc: **decided** (user-confirmed), **proposed** (written, not confirmed), **open** (needs a decision or a check), **unverified** (not checked against a live source or a captured sample).

## Scope

- Per-stock news from the Upstox News endpoint (overview 5.4).
- Licence and retention rules: overview sections 4 and 7.4.

## Blocked

- Blocked until written confirmation from Upstox that News may be stored and shown for personal use. Not received (overview sections 4.1 and 8.2 item 18).
- No build until that confirmation is recorded in the overview.
- Source stays OFF until then (overview section 5.4). How OFF is enforced is open (see Open).
- Build deferred (overview section 7.7).
- Question to put to Upstox. The project owner sends it and records the answer in overview 4.1 and 8.2 item 18. It should ask whether Upstox allows:
  - storing headlines, summaries and links in a personal database, and for how long;
  - showing them on a personal dashboard;
  - sending headlines and summaries to the local LLM at `LLM_URL`, and to a third-party host if `LLM_URL` moves to OpenRouter (overview 6.2);
  - whether the terms cover the underlying publisher content, since the News page may carry syndicated items (unverified).
- Not read: the Upstox API terms and developer agreement. Overview 8.2 item 15 lists them as not read.
- Why Upstox waits when NSE, BSE and the news feeds do not: overview section 4 accepts those sources at the user's risk. For Upstox the News page gives no storage or redistribution terms and forum replies conflict, so written confirmation is required (overview 4.1).

## Storage route (decided 2026-11-10)

- Raw items go to `event_intake` in the events database (migration 002, owned by `home-events-news-telegram.md`, status proposed). Every fetched Upstox item is inserted there first. No Upstox item is written straight to an event table.
- Processed items go to `news_events` in the events database (migration 003, owned by `home-events-news-telegram.md`, status proposed). Upstox items share this table with the other news sources. This doc adds no table and claims no migration number.
- Not `home_events`. That table holds NSE filings only and cannot hold news (overview 6.3; `home-events-filings-spec.md` 4.1).
- Only the Fastify API connects to the events database (overview 6.3; filings spec 4.6). No Mongo.
- The poller runs in a collector container (one run-once container per source, `collector-split-spec.md` 4.1). It reads `upstox_analytics_token` through the collector's secret path and posts raw items to the Fastify ingest route below. It never connects to the events database.
- Relevance: Upstox items pass through `event_intake` first. The keyword prefilter and the LLM relevance stage that move an item from `event_intake` to `news_events` are owned by `home-events-news-telegram.md` (overview section 2 table; pipeline in overview 6.1). This doc does not define them. Whether the Upstox build may ship before that stage exists is open (see Open).

### Ingest route and token (proposed)

- Route: `POST /internal/events/intake/upstox` (proposed, decision A1). Body: rows with the `event_intake` columns. Columns: to be specified in the build spec (owned by the news doc). The response follows the filings route pattern (`inserted`, `duplicates`, `invalid`). The insert is idempotent on the dedupe hash; the hash key is open (see Open).
- Auth: a bearer token. 401 without one, 403 for a token of another role. This follows `home-events-filings-spec.md` 4.6. The filings build (T5b) adds the first Fastify bearer check.
- Token role: `upstox_news_ingest` (proposed, decision A1). It is distinct from `home_events_ingest` (filings 4.6), so this poller's token can change without touching filings. The role rows are in `secrets-and-roles.md`.
- Token location and the API base URL variable (`EVENTS_API_BASE_URL`): open. They follow the collector split spec's S3 and S4 pattern (filings 4.6).
- Token values never go in the repo, a doc or a log (filings 4.6).
- API down: the source records `skipped` with `api_unavailable` (`collector-split-spec.md` 4.5; filings 4.6).

## Dependencies

- `collector-split-spec.md`: run-once containers and scheduler (4.1, 4.2); exchange cooldown and the shared `exchange_cooldown` table (4.3, 4.3a, S2); API-down skip (4.5); migration number claims (S2 and the registration migration); S3 and S4 for env and token location; risk 5 (only the latest missed slot runs).
- `home-events-filings-spec.md`: events database and migration runner (4.5, T2a, T2b); events API and token pattern (4.6, T5a to T5c); retention and purge (5.5, deferred); universe rule (4.3), if reused for the universe (see Open).
- `home-events-news-telegram.md`: `event_intake` (002) and `news_events` (003) DDL, the LLM stage, and the dedupe rule (overview 8.2 item 3).
- `fundamentals-upstox-secondary.md`: the Upstox analytics token and the shared Upstox client context.
- Overview: sections 4, 5.4, 6.3, 7.3, 7.4, and 8.2 items 8, 9, 15, 18, 19.

## Owned rules

### Endpoint and request shape

- Endpoint: `GET https://api.upstox.com/v2/news` (overview 5.4). The client that makes the call is open: the official SDK or `UpstoxClient` (see Rate limit and Open).
- Category `instrument_keys`. Keys are `NSE_EQ|<ISIN>`, built from `symbol_sector.isin`. The column is nullable (`db/migrations/025_symbol_sector.sql`), so the request set is rows `WHERE isin IS NOT NULL`. The count of 751 is as of 2026-11-10 (from `fundamentals-upstox-secondary.md`). It is not checked against the database here.
- Up to 30 keys per request. Keys are batched in groups of 30 (batch size decided). The API's per-request key limit is unverified.
- Other categories: `positions` and `holdings` returned 0 records with no error (2026-11-10 test). Not used.
- No static IP is needed (overview 5.4).
- Response fields: unverified, needs a captured redacted sample. The installed SDK item model (review file finding) defines heading, summary, thumbnail, article_link and published_time, with no instrument key field. Whether the live payload carries an instrument key on each item is unverified. Paging fields and the page size are unverified too.

### Token

- Token: `upstox_analytics_token`, read-only, in the secret store (`secrets-and-roles.md`).
- The secret endpoint serves it only to the service token mapped to `collector` (`ui/app/internal_secrets.py:33`). The secret-store roles in `secrets-and-roles.md` are admin and named user. The poller runs under the collector token, and this read adds no new service identity (review finding 19; `secrets-and-roles.md`).
- Fastify also reads the Upstox token from the environment (`server/src/index.ts:30`: `UPSTOX_ACCESS_TOKEN` or `UPSTOX_ANALYTICS_ACCESS_TOKEN`). "Collector only" therefore holds for the secret endpoint, not for every process. The review file also reports a file fallback; this is unverified because `data/` was not read.
- Expiry date: recorded with the token in the secret store (`secrets-and-roles.md`). Not checked here.

### Poll and window

- The endpoint returns about the last 7 days (overview 5.4). The source of the 7 days is unrecorded; unverified.
- Poll cadence: once a day, resolved 2026-11-10 (overview 7.3, which names it as the one exception to the schedule in 7.3). The time of day and the cron slot are not set; they are build-spec items.
- A daily poll loses nothing only while the collector runs at least once in each 7-day window. The split spec runs only the latest missed slot (`collector-split-spec.md` section 5, risk 5). If the collector host is off for more than about 7 days, articles older than the window are lost.
- Dedupe by `article_link` (overview 5.4). The dedupe key is open (see Open).
- 1-week age limit: proposed, not decided (overview 8.2 item 8). The endpoint already returns about 7 days, so the limit removes little (see Open).

### Stored fields

- Headline, summary, `article_link`, source name `Upstox`, the instrument key (if the live payload carries it; unverified, see Open), and `published_at` from `published_time`. The timezone and format of `published_time` are unverified; needs a captured redacted sample. Store `published_at` with an offset, as filings 4.6 requires.
- No article body, and no publisher page is fetched (overview 5.4).
- Column list: to be specified in the build spec. The news doc owns the tables.

### Rate limit

- Assumed: Upstox "Other Standard APIs" class (50 per second, 500 per minute, 2000 per 30 minutes per user), as in `fundamentals-upstox-secondary.md` (overview 5.4). The News page class is not checked (overview 8.2 item 19).
- `UpstoxClient` (`scanner/upstox.py`) already limits every request that goes through its `_get` method. It uses sliding windows of 40 per second, 400 per minute and 1,600 per 30 minutes (`RATE_LIMIT_WINDOWS`, lines 89 to 93; 80 percent of the assumed class). It also escalates the cool-down after repeated 429 responses (`_handle_429`). These windows apply only if the News call goes through `_get`. An SDK call does not.
- So the statement that the Upstox per-host gap and cap are not set is not accurate: the cap is the `UpstoxClient` windows. No separate gap is set.
- Call volume: 751 keys in batches of 30 is about 26 calls per daily poll, before any paging. That is far below each window.
- No daily limit applies (project owner, 2026-11-10; overview 5.4).

### Failure states (behaviour to be set in the build spec)

- Failed request (timeout, network or 5xx): retried per the config keys. A run that still fails records `failed`. Whether a failed batch waits for the next daily poll: to be set.
- HTTP 401 or 403 from Upstox: `UpstoxClient` raises `UpstoxError` with the status only in the message. The shared expiry alert (`alert_auth_failure` in `scanner/expiry_alerts.py`) has no production caller; the review file finds only tests call it (unverified). The build spec decides how the status reaches the alert. The poller does not parse the message ad hoc.
- HTTP 403 from Cloudflare, from a non-SDK client (`fundamentals-upstox-secondary.md` item 6): not an auth failure. It must not start the shared cooldown the way the split spec's cooldown rule treats an NSE 403 (`collector-split-spec.md` 4.3a). Mapping: to be set.
- Secret fetch failure (`SecretUnavailable`, 404 or 503): the run fails and writes nothing.
- HTTP 429: the `UpstoxClient` escalation applies. Whether it also sets the `upstox` row in `exchange_cooldown` (split 4.3a): to be set.
- No data: zero items across all keys is not yet a failure. The empty-feed rule is open (see Open).
- Key without ISIN: excluded by `WHERE isin IS NOT NULL`. The review file reports (unverified) that a stale ISIN returns an empty result with no error. How that is counted: to be set.
- API down: the run is `skipped` with `api_unavailable` (split 4.5; filings 4.6).

## Retention

- Event rows (`news_events`): 3 years (overview 7.4). This value was set before the licence is known. It is subject to the terms Upstox confirms.
- Terminal `event_intake` rows (`rejected`, `expired`): 14 to 30 days (value open; overview 6.3 and 7.4). They are kept only so a re-polled item is not re-queued.
- Purge: no job covers these tables yet. The events-database purge is deferred (filings spec 5.5; overview 8.2 item 4). The planned purge runs inside the `home_filings` run, which does not cover the news tables. This gap is owned by the filings doc.

## Carried from the overview (not owned here)

- Licence and feed rights: overview section 4.
- Retention value: overview section 7.4. Purge design: filings spec 5.5.
- Build order: overview section 7.7.
- Shortlist and event tiers: overview sections 7.1 and 7.2.

## Build specs (stub, not written)

Missing before any build:

1. Upstox terms confirmation recorded in the overview (blocked).
2. Captured redacted sample: one live call, kept out of git while the licence is unconfirmed. Then a field table: response fields, `published_time` format and timezone, whether an item carries one or several instrument keys, and paging fields. Whether a sample may be captured before the confirmation is open. Unverified, needs a captured redacted sample.
3. Migrations: none in this doc. `event_intake` (002) and `news_events` (003) DDL are owned by `home-events-news-telegram.md`. This doc adds only the ingest route and its token.
4. Config keys with defaults and units: batch size (decided: 30 keys); poll time of day and cron slot (once a day; time not set); age limit (proposed: 1 week, not decided); `request_timeout_s`; retry and backoff after 429 or 5xx; `enabled` switch (OFF by default; enforcement open).
5. Env var names: `upstox_analytics_token` (existing). Ingest token location and `EVENTS_API_BASE_URL`: open (split S3 and S4 pattern; filings 4.6).
6. Owner module paths for the poller, the batcher and the ingest route: not chosen. Create, Modify or Delete marker per file after the paths are chosen.
7. Batch failure handling for the 30-key request, including whether a failed batch is retried at the next daily poll (overview 8.2 item 19).
8. Failure states: each item in "Failure states" above needs its behaviour set.
9. Collector-split integration: `events_source = True` and the `api_unavailable` skip (split 4.5); an `upstox` row in `exchange_cooldown` (split 4.3a, S2); an `exchange` field in `config/collector_services.json`; a `collector_sources` registration migration (number from the split spec's claims); the cron; an entry in `_valid_param_keys` (`scanner/collect/settings.py:195`), which rejects all params of an unknown source.
10. Ingest route and token: the route, the token role and its file location (see "Ingest route and token").
11. Test plan, fixtures (synthetic only while the licence is unresolved), test counts and the acceptance command: to be set before build.

## Open

Items for the user to decide. Each one is also in `docs/progress/home-events-upstox-news-decisions.md`.

- Feed tier and event type for Upstox items (overview 7.1), and whether the Upstox build waits for the LLM stage (overview 7.7).
- Ingest token location and `EVENTS_API_BASE_URL` (open; the route and per-source token are decided under A1).
- Attribution: how an article is linked to a symbol if the live payload carries no instrument key (one request per key, or symbol extraction in the LLM stage). Also whether a sample may be captured before the Upstox confirmation, and whether zero items across all keys means "no news" or "broken". Unverified, needs a captured redacted sample.
- Dedupe key: `article_link` alone, or `(article_link, instrument key)`. Also whether to adopt a seen-links store, or overview 8.2 item 3 for this source. Terminal-row retention (14 to 30 days, overview 6.3) depends on this.
- OFF enforcement: register no source until unblocked, or add a default-disabled parameter that the run checks first (as filings `default_enabled`). Also whether build specs may be written while the source is blocked.
- Client: the official SDK (adds the `upstox-python-sdk` dependency to `requirements.txt`, `requirements.lock.txt` and the Dockerfile) or `UpstoxClient._get` (no new dependency; keeps its headers and limiter). The endpoint wording and the rate-limit text depend on this.
- Age limit (overview 8.2 item 8): keep or drop the 1-week limit. If kept, what it measures (`published_at` or fetch time).
- Universe: which rows form the universe (`symbol_sector` with an ISIN, 751 as of 2026-11-10; the shortlist; or the browser watchlist, which is not stored server-side). Also the volume and LLM time estimate.
- Ownership of the values: this doc or the overview. Until decided, overview 5.4 governs.
- Prefilter owner (the filings doc or the news doc): held until news decision B4 is made.
- Still open in the overview: item 9 (per-host gap and cap for Upstox; owner: each split doc), item 18 (blocked on the Upstox confirmation), and item 19 (batch failure handling; News page rate-limit class).
