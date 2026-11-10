# Home events: exchange filings build spec (approved, revision 4)

- Status: approved by the user (confirmed 2026-11-11). Revision 4 of 2026-11-10, after the third review ([home-events-filings-spec-review3.md](../progress/home-events-filings-spec-review3.md), NOT READY, fixes applied here) and the second review ([home-events-filings-spec-review2.md](../progress/home-events-filings-spec-review2.md), NOT READY) and the first ([home-events-filings-spec-review.md](../progress/home-events-filings-spec-review.md)). The user answered Q1 to Q4 on 2026-11-10 (applied below: cron `8-20` kept; order-win feed deferred; fundamentals trigger moved out; flagged feeds on). Revision 4 has the third-pass fixes and is not re-reviewed. No task may be dispatched from this spec until the user approves it.
- Owner: Vaibhav Pavtekar
- Screen: Home, shortlist and event feed (`docs/designs/ui-redesign-spec.md` sections 5.1 and 6)
- Parent docs: [home-events-filings.md](home-events-filings.md) (owned rules), [home-event-sources.md](home-event-sources.md) (overview).
- Governing spec: where this spec and [collector-split-spec.md](collector-split-spec.md) disagree on the runner, the due rule, the cooldown or a migration number, the collector-split spec governs (user, 2026-11-10).

## 0. How to read this spec

**Legend.** *Decided* = the user decided it (date given). *Proposed* = my default, usable unless you change it. *Open* = needs an answer or a sample before the task that depends on it. *Confirmed* = the user confirmed my proposal (date given). *Deferred* = decided, not built here. *Parked* = never requested. *To verify* = a fact I could not check (NSE timed out and BSE returned HTTP 403 from here, and no feed sample is recorded in the repo).

**Decision tags.** The user's cuts of 2026-11-10 are cited by tag: Z2 defer BSE; Z3 drop the value and market-cap columns; Z4 drop `rows_rejected`; Z5 defer the purge; Z6 one module; Z7 weekday-hours cron; Z12 reuse the `announcements` store (decided, then deferred with the order-win feed, Q2). Z2 to Z7 and Z12 are the cuts the user accepted; no other Z tag is in force. D1 to D10 and Q1 to Q4 are listed in section 10; T0 to T9 in section 9; S1a to S8 are the collector-split spec's slices; M1 to M14 are numbered findings of [review 2](../progress/home-events-filings-spec-review2.md).

**Terms.**
- *Feed tier* (`high_priority`, `catalyst`): the overview 5.1 grouping of a feed, stored on each row. *Event tier* (1 or 2, overview 7.1): the Home display priority. It is a code constant on the read path, not a column. D6a is still open, so Home should not filter by event tier yet.
- *Tick*: one scheduled start of the source (every 5 minutes inside the cron window).
- *Events source*: a source that needs the Fastify API (split spec 4.5): `home_filings`.
- *Request retry*: the single re-request of one feed inside a run (5.4). *Block stop*: the run stops after a 403, a 429 or an HTML block page (5.2). *Run retry*: the split spec's rule for starting a failed run again (its 4.2). At a 5-minute cadence the run retry is moot: the next tick is the retry.
- *Slice*: the first end-to-end build of one feed (T4e).

**Numbering.** Sections 4.0 to 4.7 (and 4.3a) keep their numbers because the collector-split spec cites 4.6 (events endpoints) and 4.7 (fundamentals trigger).

## 1. Scope

- Ingest **8 NSE feeds** (section 4.0), all written to the events database as `home_events`. **Decided 2026-11-10 (Z2): BSE is deferred.** **Decided 2026-11-10 (Q2): the order-win feed `nse:Online_announcements` is deferred** to a later spec (4.3a). The overview's "14 active feeds" becomes 8 now, with 5 BSE feeds and the order-win feed later.
- Store only events for the scanner universe (D3, decided; 4.3).
- Out of scope: BSE, the order-win feed (`announcements` reuse, Z12, deferred with it), news RSS, Telegram, Upstox News, the macro calendar, the LLM stage, the Home read path (ui-redesign spec), purge (Z5), the value and market-cap columns (Z3), the cross-source reconciler (4.4) and the fundamentals trigger (4.7, own spec).

## 2. Dependencies on the collector-split spec

This spec does not build the runner. It consumes what the split spec builds. What is needed, and what must be **added to the split spec** (it is another session's document, so these are requests, not edits):

| Needed | Task | Status |
|---|---|---|
| `execute_source` extraction and a `skipped` write path | S1a | exists in the split spec |
| **`run()` may return `status` in `ok`, `failed`, `skipped`; `execute_source` persists it with counts and `message`; run-once exits non-zero on `failed`** | S1a | **add to split spec, with a test** (review M1). Without it a block records `ok`. |
| Run-once container, `--source`, API-health check for events sources | S1a, S3 | exists. **Add:** how run-once learns a source is an events source (this spec: class attribute `events_source = True`, T4d). |
| `exchange_cooldown` table, one row per exchange | S2 | exists. S2 owns the backoff and cap values. |
| `GET /internal/due` omits a source whose exchange has an active cooldown | S5a | **add:** an `exchange` field per entry in `config/collector_services.json` (`home_filings` is `nse`), populated in T9. |
| Watchdog finalises a `running` row when it kills a container (`failed`, message `killed`) and max-runtime in `config/collector_runtime.json` | S4 | **add** (review M7). Value for `home_filings`: **330 s** (5.3: the worst case is 285 s plus container start of up to about 20 s). |
| The split spec cites "filings spec 4.7" for the fundamentals queue (its 4.2, the 4.6 table "weekly sweep" row, S5a and S7). 4.7 is now a stub | S5a, S7 | **add:** repoint those four citations to the future `fundamentals-trigger-spec.md`. |
| Fastify `server` containerised and reachable from collector containers | S3 | **add** (review M13). Today Fastify runs on the host and binds `127.0.0.1:8081` only (`server/src/index.ts`), so no container can reach it, and the old claim "internal routes are compose-only" was wrong. Internal routes will be token-gated, on the same port as `/api/*` (split 4.5). |
| A migration number | S2 | The split spec says S2 claims 047. S2a takes "a number when written". S5a needs a migration and names none, and S8's `filings` cron migration (its 4.6) is a fourth claimant. **This spec's registration migration takes the next number after those three are assigned** (shown as `NNN`), so T1 waits for that assignment. The events database has its own series (`db/events_migrations/001_...`). |

Build order, derived from section 9's Depends column. No task needs another first: T0 (samples), T2a, T3a, T4a, T5a. Then T2b (after T2a), T3b, T3c, T4b, T4c, T6 one at a time in that order, because they all edit `scanner/home_events.py` (created by T3a); T5b (after T5a), T5c (after T5b, T2a and S3). Then T4d (after T4c, T4a, T6, S1a, S2 and the token-path decision in 4.6). T4e and T7 need T0. T1 needs the migration number from the split spec. T9 last (needs S1a, S1b, S3, S4, S5a).

## 3. Existing code this spec reuses or must not duplicate

| Item | Where | Use |
|---|---|---|
| NSE cookie warm-up | `scanner/marketdata/factors_postgres.py` `_nse_session` (private, bare `Session`; warm-up failure is not fatal) and the `UA` header dict (`Accept: application/json, text/plain, */*`, which already allows XML) | T3a adds a public `nse_session()` and a header dict for the feeds. `_nse_session` keeps its behaviour. |
| Run base class | `scanner/collect/sources.py` `Source.run(params, now, dry_run)`, `plan()`, and the `SOURCES` dict | `HomeFilings(Source)`. `plan()` is pure: no network, no database, no sleep. `collect.py` indexes `result['fetched']` and `result['new']` on a dry run, so `plan()` must return the full result shape. |
| Source registration | `scanner/collect/settings.py` `ensure_sources()` and `_valid_param_keys` | `_valid_param_keys` returns an empty set for an unknown source, so every `home_filings` param is rejected until T4a adds the key set. The `{}` in the registration row is accepted. |
| Existing test pinning the source set | `tests/test_collect_sources.py` (the exact set of 7 names; its docstring says "5 feed sources") | Updated in T4d. |
| Throwaway-schema fixture | `tests/pgschema.py` (calls `migrate.apply()` with no arguments; `SkipTest` without Postgres) | Main-database tests only. **A skipped test is not a pass.** |
| Migration runner | `scanner/pg/migrate.py` (one `MIGRATIONS` directory constant, one `schema_migrations` table with column `filename`, one transaction per file, `--status`, a `_BOOT` statement that creates the table) and `scanner/pg/db.py` (`connect(**kw)` forwards keyword arguments to `psycopg.connect`; `dsn()` refuses a DSN that disagrees with `POSTGRES_DB` through `_check_dsn_agrees`) | Both change in T2a (4.5). |
| Down-step precedent | `db/migrations/down/045_*.down.sql`, `046_*.down.sql` | 046's header reads "NOT run by the migration runner" and "Take a pg_dump first.". 045 cites `docs/progress/rollback.md`, which does not exist. |

The order-win rule (`matches_orderbook`) and the announcements writer (`_save_announcements`) in `scanner/factors.py` are not used here, because the order-win feed is deferred (4.3a). They must not change.

`collector_settings.source` has no CHECK constraint (created in `001_core.sql`, replaced in 013, dropped in 014, dropped again with `IF EXISTS` in 041); its constraint is the foreign key to `collector_sources`. The name `home_filings` needs no CHECK change. `symbol_sector.isin` is nullable (`025_symbol_sector.sql`), hence the `IS NOT NULL` in the universe query.

## 4. Feed registry and data model

### 4.0 Feed registry and parsed item

**D1 decided 2026-11-10: XML, for long-term support.** The exact URLs and tag names are **to verify** from T0.

Fields of a registry entry (frozen dataclass `Feed`): `feed_code` (`nse:<Name>`), `url`, `event_type`, `feed_tier`, `default_enabled` (true for all eight today; kept so a feed can ship switched off), `flagged` (tier still to confirm).

| feed_code | event_type | feed_tier | default_enabled | flagged |
|---|---|---|---|---|
| nse:Financial_Results | results | high_priority | yes | no |
| nse:Integrated_Filing_Financials | results | high_priority | yes | no |
| nse:Sast_Regulation29 | insider_trade | high_priority | yes | no |
| nse:Sast_Regulation31 | insider_trade | high_priority | yes | no |
| nse:Corporate_action | corporate_action | catalyst | yes | no |
| nse:Corporate_Governance | governance | high_priority | yes | no |
| nse:Related_Party_Trans | related_party | high_priority | yes | yes (overview: tier to confirm) |
| nse:Shareholding_Pattern | shareholding | catalyst | yes | yes (overview gives no tier) |

**Decided 2026-11-10 (Q4): all eight feeds are on by default**, including the two flagged ones. A flagged feed stores its rows with the provisional feed tier (a column), and Home may filter by feed tier when it reads. A later correction is an `UPDATE` run as the database owner in a migration (the API login has `SELECT, INSERT` only), not a re-ingest. Consequence: these two are quarterly filings, so polling them every 5 minutes adds block risk for little freshness; `enabled_feeds` can switch them off without a code change. Deferred (Q2): `nse:Online_announcements` (order wins, 4.3a). Parked, never requested: `nse:Annual_Reports`. Deferred (Z2): the five `bse:` feeds.

Event types stored in `home_events` now: `results`, `insider_trade`, `governance`, `corporate_action`, `shareholding`, `related_party`. Adding a value later is a migration that replaces the CHECK.

**Parsed item** (one dict per feed item, returned inside `ParseResult`, section 6):

```
{ "source_id": str | None,   # the feed's own id, if it has one
  "source_url": str,         # link to the filing
  "symbol": str,             # stripped, uppercased
  "isin": str | None,        # from the feed if present
  "company": str | None,
  "headline": str,
  "published_at": datetime } # timezone-aware; IST source times converted with zoneinfo "Asia/Kolkata"
```

Sample and fixture policy:
- **Decided 2026-11-10: real samples are not committed.** T0 saves them under `data/home_samples/` (ignored by git), named `nse_<Name>.xml`, because a colon in a filename is illegal on Windows. Synthetic fixtures use the same naming in `tests/fixtures/home_events/` and are committed. The mapping is `feed_code.replace(":", "_")`.
- The synthetic fixtures reproduce the structure of the real sample (tag names, nesting, date format, id presence, empty fields) with invented companies and values. **They cannot be written until T0 delivers the tag-to-key table**, which T0 writes into this section.
- A parser handles five cases: an empty feed, malformed XML (`ParseError`), an HTML page served with status 200 (`ParseError`), an item with a missing required field or an unparseable date (the item is dropped and counted in `dropped`), and a normal feed.

### 4.1 Migrations (two databases; D8 decided: separate database on the same server)

- **Main database** (`market_scanner`): `db/migrations/NNN_home_filings_registration.sql`. Registration rows only.
- **Events database** (`market_scanner_events`, 4.5): `db/events_migrations/001_home_events.sql`. This file holds one table. Nothing in either file refers to a table in the other database.

Main database file:

```sql
-- Home event feed, exchange filings (registration only). Spec: docs/designs/home-events-filings-spec.md.
-- Down-step: db/migrations/down/NNN_home_filings_registration.down.sql (manual, not run by the runner).
INSERT INTO collector_sources (source) VALUES ('home_filings') ON CONFLICT (source) DO NOTHING;
INSERT INTO collector_settings (source, mode, cron, params) VALUES
  ('home_filings', 'manual', '*/5 8-20 * * 1-5', '{}')
ON CONFLICT (source) DO NOTHING;
```

**Rollout hazards (review M14, third review).** The row starts `manual`. After T4d adds `SOURCES["home_filings"]`, the existing `collect.py serve` loop would run a `scheduled` row sequentially in its own process for up to 240 s, with no API health guard and no `skipped` support. So the row is inserted as `manual`, and T9 flips it to `scheduled` **and sets the cron** (a settings update, not a migration) once the run-once container exists. T9 must set the cron because `ensure_sources()` (`settings.py:35-59`) inserts any `SOURCES` key with the placeholder cron `0 0 1 1 *` and never changes an existing row, so if T4d merges before T1 the migration's `ON CONFLICT DO NOTHING` leaves the placeholder in place.

**Cron `*/5 8-20 * * 1-5` (IST, weekdays 08:00 to 20:55). Decided 2026-11-10 (Q1), changed from `8-15`.** Revision 2 used `8-15`, which I read into "weekday-hours" (Z7). The review showed that results are filed mostly after 15:30, so a 15:55 stop delays the highest-value events and the fundamentals trigger by up to 16 hours, and the split spec runs `filings` until 20:52. `8-20` follows the split spec. Consequences: about 12 ticks an hour; with 8 default feeds that is about 96 NSE requests an hour inside the window; exchange holidays still start a run that finds nothing (split risk 8); a block pauses every NSE source through the shared cooldown; the 08:00 run after an overnight gap may bring a burst of results. Feed depth (does a feed list enough items to cover the overnight gap) is **to verify** from the T0 samples and is a precondition for production use of the slice.

Events database file (`db/events_migrations/001_home_events.sql`):

```sql
-- Home event feed table. Spec: docs/designs/home-events-filings-spec.md.
-- No GRANT: the migration runs as the app login, which owns the database (4.5), so it owns the table.
-- Down-step: db/events_migrations/down/001_home_events.down.sql (manual).
CREATE TABLE home_events (
  dedupe_key    text PRIMARY KEY,
  exchange      text NOT NULL CHECK (exchange IN ('NSE')),
  feed_code     text NOT NULL,
  source_id     text,
  source_url    text NOT NULL,
  isin          text NOT NULL,
  symbol        text NOT NULL,
  company       text,
  event_type    text NOT NULL CHECK (event_type IN
                  ('results','insider_trade','governance','corporate_action','shareholding','related_party')),
  feed_tier     text NOT NULL CHECK (feed_tier IN ('high_priority','catalyst')),
  headline      text NOT NULL,
  published_at  timestamptz NOT NULL,
  fetched_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX home_events_isin_pub_idx ON home_events (isin, published_at DESC);
CREATE INDEX home_events_pub_idx ON home_events (published_at DESC);
```

The `exchange` CHECK allows `'NSE'` only. BSE is deferred (Z2), and the BSE phase replaces the CHECK in its own migration.

Down step, events database (`db/events_migrations/down/001_home_events.down.sql`):

```sql
-- NOT run by the runner. Take a pg_dump first.
DROP TABLE IF EXISTS home_events;
DELETE FROM schema_migrations WHERE filename = '001_home_events.sql';
```

Down step, main database (`db/migrations/down/NNN_home_filings_registration.down.sql`), in foreign-key order (`collector_runs.source` and `collector_requests.source` reference `collector_settings`, which references `collector_sources`):

```sql
-- NOT run by the runner. Take a pg_dump first: this deletes run history for home_filings.
-- Revert the code first, or ensure_sources() will insert the rows again.
DELETE FROM collector_requests WHERE source = 'home_filings';
DELETE FROM collector_runs     WHERE source = 'home_filings';
DELETE FROM collector_settings WHERE source = 'home_filings';
DELETE FROM collector_sources  WHERE source = 'home_filings';
DELETE FROM schema_migrations  WHERE filename = 'NNN_home_filings_registration.sql';
```

Deferred by the cuts: `value_cr`, `pct_shares`, `mcap_cr`, `mcap_as_of` (Z3: the overview 8.2 item 6 thresholds cannot be applied until a later migration adds them, parsers extract them and a market-cap source exists; no table has `mcap_cr` today and Postgres `fund_snapshot` is not applied); the grouping columns (4.4); `match_basis` (order wins are not in this table).

### 4.2 Dedupe key

`dedupe_key(feed_code, source_id, source_url, published_at)`:
- With a feed id: `"<feed_code>:<source_id>"`.
- Without one: `"<feed_code>:" + sha256(f"{source_url}|{published_at.astimezone(UTC).isoformat()}".encode()).hexdigest()`.

`run_cycle` drops repeated keys inside one batch before posting. The API inserts with `ON CONFLICT (dedupe_key) DO NOTHING`. A run that crosses 500 rows commits in separate transactions, which is safe because inserts are idempotent. Which feeds carry an id is **to verify** (T0). An amended filing that keeps its id is ignored (first wins); one with a new id is a new row; linking them is the reconciler's job (4.4).

### 4.3 Universe and rejections

- Universe (D3 confirmed 2026-11-10): `SELECT upper(btrim(symbol)), isin FROM symbol_sector WHERE isin IS NOT NULL`, loaded once at run start by `load_universe()`. Company name comes from the feed, or null.
- Rejection reasons, one vocabulary everywhere (`parse`, `universe`):
  - `parse`: counted by `parse()` itself (missing required field, unparseable date) as `dropped`.
  - `universe`: the symbol is not in the universe.
  - An item that fails both tests is counted once, as `universe`.
- **Deferred (decided 2026-11-10): the ingest floor (`date_floor`, `ingest_floor_days`) and the future-date test (`date_future`).** Each feed returns only its recent items, so a floor has little to remove. Consequence: an item with a wrong date (far past or far future) is stored as given. The API still rejects a `published_at` without an offset (4.6). Revisit if T0 shows a feed with deep history or bad dates.
- Loss to know about: a rejected item is gone. If the universe grows, earlier events are not recoverable from this table.

### 4.3a Order-win feed (`nse:Online_announcements`): deferred (Q2, decided 2026-11-10)

The feed is not built in this spec. Z12 (write it to the existing `announcements` table) stays on record as the intended route, but the review found it unsafe to build now, and the user agreed to defer it. The findings that block it:

- `_save_announcements` never backfills `attchmnt_text`, so a row first written by this feed with empty text stays text-less, and D4 (category-only matching) becomes permanent for those rows.
- The `(isin, an_dt, "desc")` key match with the per-symbol collector's rows is unverified; a mismatch would double-count rows against the 3-per-stock cap.
- `matches_orderbook` is Python and the Home read path is Fastify, so who runs the rule, and how rows from the main and events databases are merged, is undecided (a ui-redesign spec question).

Whoever picks this up needs a sample of the feed (T0 covers it if asked), the key-match test and the reader decision. Nothing in this spec depends on it.

### 4.4 Cross-source reconciliation (required by the user 2026-11-10; build deferred)

The same event reported twice, an amended filing, or a filing plus an article must appear as one Home item. With BSE and the order-win feed deferred, there is no cross-exchange duplicate here. Two kinds remain: the two `results` feeds (`Financial_Results`, `Integrated_Filing_Financials`) may list the same filing, and an amendment with a new id is a new row; both can use up the 3-per-stock Home cap. T0 checks whether the two results feeds overlap. The reconciler is **not built now** (proposed) and has no task in section 9. When it is built it needs its own spec and review: a `home_reconcile` source talking only to the API, never deleting, adding `event_group_id`, `is_primary` and `supersedes` through its own migration with `GRANT UPDATE` on those columns; pass 1 groups by ISIN, event type and a 24-hour window with the earliest `published_at` as primary; pass 2 (news against filing) waits for the news source and the LLM stage. Until then all rows are shown, not primary rows.

### 4.5 Events database (D8 decided: separate database, same server)

What the repo does today: `scanner/pg/db.py` builds one connection from `POSTGRES_DSN` or `POSTGRES_*`. `connect(**kw)` forwards keyword arguments to `psycopg.connect`, and `dsn()` calls `_check_dsn_agrees`, which refuses a DSN that disagrees with `POSTGRES_DB`. `scanner/pg/migrate.py` has one fixed directory and one `schema_migrations` table. The `scanner` image copies `db/` at build time (`docker/scanner/Dockerfile`), so the image must be **rebuilt** before the migrate stage can see `db/events_migrations/`.

Work, split in two tasks:

**T2a (Python, SQL, tests).**
- `scanner/pg/db.py`: `dsn(dbname: str | None = None)` and `connect(dbname: str | None = None, **kw)`. When `dbname` is given it overrides the database name and `dsn()` skips `_check_dsn_agrees`. Default behaviour is unchanged.
- `scanner/pg/migrate.py`: `MIGRATION_DIRS = {"main": db/migrations, "events": db/events_migrations}`, `files(target: str = "main") -> list[Path]`, `apply(target: str = "main")`, `status(target: str = "main")`, CLI `--db {main,events}` (default `main`; `--status` works for both). The parameter is named `target`, not `db`, because the module already does `from . import db` and a string parameter named `db` would shadow it. `events` uses its own `schema_migrations` table inside the events database and the same `_BOOT`. Files are globbed non-recursively, so `down/` never runs. `pgschema.create` calls `apply()` with no arguments, so the default must not change.
- `db/events_migrations/001_home_events.sql` and its down file.
- Environment: `POSTGRES_EVENTS_DB` (default `market_scanner_events`), no secret values.
- Test isolation: `tests/pgschema.py` gains an optional argument so `apply_events_creates_table` applies the events files into a throwaway schema of the main test database (the events SQL refers to nothing outside its own table, so this is valid). `pgschema.create` keeps calling `apply()` with no arguments and its behaviour is unchanged.

**T2b (`start.ps1`, `env.template`).** Mind the PowerShell 5.1 quote-dropping behaviour when passing SQL to a native command; follow the existing `Invoke-Docker` usage.
- A stage before the migrate stage creates the database when missing, idempotently, with no manual step (decided 2026-11-10). `CREATE DATABASE` needs the admin login, so the stage runs `docker compose exec -T scanner-postgres psql -U <admin> -d postgres` with `SELECT 'CREATE DATABASE <events db> OWNER <app login>' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '<events db>') \gexec`. It reads no password and touches no `.env`. The owner is the **app login**, because on PostgreSQL 15 and later a login that does not own the database cannot create tables in `public`. A precondition check confirms the role exists. A non-zero exit is a warning, as for the migrate stage.
- The migrate stage (`start.ps1`, the "Run migrations" step, currently line 238) runs `python -m scanner.pg.migrate` and then `python -m scanner.pg.migrate --db events`. That is the only migrate call in `start.ps1`.
- `env.template`: add the name `POSTGRES_EVENTS_DB`.
- D9 "API only" is a convention: `CONNECT` is granted to PUBLIC by default, so the collector login can still connect. Whether to `REVOKE CONNECT ... FROM PUBLIC` is open and does not block a task.
- Backup of the events database: separate dump, schedule open.

Consequences: no foreign key or join across the two databases; the collector's run row (main) and its event posts (events, via the API) are not in one transaction, which is fine because posts are idempotent.

### 4.6 Events API: the only path to the events database (D9 decided 2026-11-10)

No service other than the Fastify `server` connects to the events database (the migration runner is a deploy-time tool). The collector's direct access to the main database is unchanged.

| Endpoint | Caller | Behaviour |
|---|---|---|
| `POST /internal/events/batch` | `home_filings` | Body `{"rows": [...]}`, at most 500 rows (413 above that), each with the `home_events` columns except `fetched_at`; `published_at` is ISO 8601 with offset. Bearer token required: 401 without one, 403 for a token of another role. One transaction: `INSERT ... ON CONFLICT (dedupe_key) DO NOTHING`. Returns `{inserted, duplicates, invalid}`. An invalid row (shape, enum, date) is counted in `invalid` and does not fail the batch. |
| `GET /api/events` | UI | Owned by the ui-redesign spec. The 3-per-stock cap is decided there. |
| Deferred (4.4, 4.7) | reconciler, fundamentals trigger | `GET /internal/events/ungrouped`, `PATCH /internal/events/groups`, `GET /internal/events/results-since`. |

- Auth: a bearer token per caller (name `home_events_ingest`, proposed) following `secrets-and-roles.md`. There is no Fastify bearer-token pattern in `server/src` today (the only `Bearer` uses are outbound Upstox calls), so T5b adds one. Token values never go in the repo, a doc or a log. Where the collector container reads it, and the name of the API base-URL variable (`EVENTS_API_BASE_URL`, proposed), are the split spec's S3/S4 pattern and **open**; T4d waits for that decision.
- Validation (T5a): `source_url` must be an `http` or `https` URL (it is rendered in the UI), `headline` is capped at 500 characters, and `published_at` must carry an offset. A row failing any check is counted in `invalid`.
- Server substrate: `buildApp(deps)` takes an `AppDeps` with a single-query `QueryFn`, which cannot run a transaction. `AppDeps` gains an events-database dependency (a `withTransaction` function) and a token-check dependency. The events pool must be read-capable (`GET /api/events` reads it). T5c adds an `eventsPoolConfig()` in `server/src/config.ts`: `config.ts` today returns `{connectionString: dsn}` when `POSTGRES_DSN` is set and ignores any database override, so the new function applies `POSTGRES_EVENTS_DB` over either form.
- The server must be reachable from a collector container, which needs S3 (section 2).
- API-down behaviour is the split spec's (its 4.5): an events source that finds the server unhealthy records `skipped` (`api_unavailable`). `GET /api/health` does not check the events pool today; T5c makes the health check cover it.

### 4.7 Fundamentals refresh trigger (decision kept; design moved out of this spec)

**Decided by the user, 2026-11-10:** refresh fundamentals when a results filing is seen, with an automatic catch-up for a missed trigger, instead of relying on the daily sweep alone. The revision-2 design of this section (a `fundamentals_queue` table, enqueue inside the batch transaction, done endpoint, weekly sweep, staleness check inside Fastify) is **withdrawn from this spec** because the review found it does not hold:
- the staleness check cannot run in Fastify, since `server/src` has no Mongo access and the last-refresh time is Mongo-backed;
- `ON CONFLICT DO NOTHING` plus delete-by-ISIN loses a second trigger that arrives while a refresh is in flight;
- a refresh on filing can fetch pre-result data and clear the row, leaving the next trigger about 100 days away;
- `refetch_only_on_new_result` is only whitelisted in `settings.py`; nothing reads it.

Requirement carried forward: it gets its own spec (`fundamentals-trigger-spec.md`, not yet written) with its own review. Candidate to evaluate there, the zoom-out lens's smaller alternative: keep the daily `fundamentals` run as the refresher and add one read-only `GET /internal/events/results-since`, treating a symbol as stale when a results event is newer than its stored fundamentals time. No queue table, no done endpoint and no enqueue in this spec's batch route. The split spec's 4.2, 4.6 table, S5a and S7 cite "filings spec 4.7" for this; they should point to that spec (section 2 request).

## 5. Run behaviour

### 5.1 Entry point

`HomeFilings(Source)` in `scanner/collect/sources.py`, with class attribute `events_source = True`. It calls `scanner.home_events.run_cycle(...)` and is started by the split spec's run-once container, so it does no scheduling and no window check. Signatures: `plan(params, now=None)` and `run(params, now=None, dry_run=False)`. `plan()` returns the full result shape with zeros: `{"fetched": 0, "new": 0, "from": None, "to": None, "message": "dry-run: would fetch <n> NSE feeds"}`, where `<n>` is the number of enabled feeds.

Order of a run:
1. The container has already checked API health. Validate `params` (section 7); an invalid value ends the run `failed`, message `config:<key>`, with no request.
2. Read the `nse` cooldown. Active: stop with status `skipped`, message `exchange_cooldown`, no request made.
3. Compute `deadline_at = clock() + run_deadline_s` first, then `load_universe()`. Choose the start feed: `int(now.timestamp() // 300) % n`, then walk the enabled feeds in registry order from that index, wrapping. This rotation stops a persistently slow run from never reaching the last feeds.
4. For each feed, one at a time: (a) stop if `clock() + gap_max_s + request_timeout_s > deadline_at` (`clock` is an injected callable returning the current time, so elapsed time is testable); (b) re-read the cooldown and stop if another container set it; (c) wait a random gap of `gap_min_s` to `gap_max_s`; (d) fetch; (e) classify (5.2); (f) parse (the injected `parse_fn`), filter (4.3), then post the rows via `post`.
5. At the end of a run in which no block occurred, no cooldown was seen mid-run (step 4b) and at least one feed succeeded, call `cooldown.reset("nse")`. Never reset earlier (review M2: a reset after the first success would stop the backoff from ever escalating).
6. Return `{"status", "fetched", "new", "from", "to", "message"}`. `fetched` is the parsed item count after `parse()`. `new` is the sum of `inserted` from the API. The API's `invalid` count is summed too (5.2). `from` and `to` are the earliest and latest `published_at` kept, or `None`.

**Who writes what.** `run_cycle` returns the status dict and writes the cooldown only through the injected object (block and success reset). `execute_source` (split S1a) writes the run row. The cooldown's backoff and cap values belong to S2.

### 5.2 Response handling, cooldown and status

`classify_response(status, content_type, body)` returns `"ok"`, `"blocked"`, `"retry"` or `"fail"`. `fetch_feed` maps these to `FetchResult.outcome`: `ok`, `blocked`, `transient` (a `retry` that failed again) and `fatal` (`fail`, or a `ParseError`). `status` is `None` for a timeout or connection error.

| Input | Returns | Action |
|---|---|---|
| `None` (timeout, connection error) | `retry` | One request retry (5.4), then the feed is `failed` and the loop continues |
| 408, 5xx | `retry` | same |
| 403, 429 | `blocked` | Block stop: `cooldown.block("nse", ...)`, stop the loop, run status `failed`, message `blocked:<feed_code>` |
| 200 with `html` in the content type, or a body whose first non-space bytes are `<!doctype html` or `<html` (case-insensitive) | `blocked` | same as 403 |
| 200 with an empty body | `fail` | feed failed, no retry |
| 200, any other body | `ok` | `parse()`; a `ParseError` makes the feed failed (counted, no retry, no cooldown) |
| 3xx, 401, 404, other 4xx | `fail` | feed failed, no retry (wrong URL, a withdrawn feed, or a changed contract) |

Invalid rows: if the API reports `invalid > 0` the run ends `failed`, message `invalid:<n>`. Python validates before posting, so a non-zero count means the Python enums and the TypeScript validator disagree (for example a date offset format), and it must be loud rather than an `ok` run with `new=0` forever.

Post failure: if `post` raises or returns a non-2xx, stop the loop, status `failed`, message `api_error`, no cooldown change. The data fetched for that feed is dropped until the next tick, which is safe only if feed depth holds (T0 check).

**Run status, in order:**
1. `skipped`: cooldown active at the start (5.1 step 2), or active mid-run before any feed was fetched.
2. `failed`: a block stop, an `api_error`, `invalid:<n>`, a `config:<key>` error, a feed with a non-transient failure (`fail` class or `ParseError`; the message names it, which makes a withdrawn URL visible instead of leaving an `ok` run), every attempted feed failed, or the deadline hit with zero feeds fetched (`deadline: 0 feeds fetched`).
3. `ok`: otherwise. The message names any transient failures (`failed:<feed_code>`) and `deadline: <n> feeds not fetched` when the deadline stopped the loop. A cooldown seen mid-run after at least one feed was fetched also ends `ok` with `exchange_cooldown` (the fetched data is already stored; before any fetch the run did nothing, hence `skipped`). A feed that always returns 404 makes every run `failed` until it is removed from `enabled_feeds`; that is intended, so a withdrawn URL is visible.

**One bad URL can pause all of NSE.** NSE often answers a wrong path with 403, and a 403 starts the exchange-wide cooldown (`announcements`, `corporate_actions` and `filings` pause too). So T0 must record a successful fetch for every URL, and T9 depends on T0. Whether a 403 on one feed while the others work should be a plain `fail` is open (proposed: keep it `blocked`, the conservative choice).

**Rejected counts (Z4, decided):** no `rows_rejected` column. The message carries `rejected parse=<n> universe=<n>` and `invalid=<n>`. This deviates from overview 7.4 ("stored counts are the only trace"), which needs the one-line amendment "per-run counts in the run message". The dashboard does not parse `message`.

### 5.3 Run deadline and isolation (decided by the split spec)

One container per source, so a slow `announcements` run cannot delay `home_filings`; the earlier shared-lock idea is dropped. A feed is started only when `now + gap_max_s + request_timeout_s <= deadline_at`, so with the 20-second timeout the last fetch ends by the deadline. `deadline_at` is set before `load_universe()` so the universe query counts against it. Each post has `post_timeout_s`. A feed already fetched is posted even after the deadline. The worst case is therefore `run_deadline_s` plus about three `post_timeout_s` (a feed's items can span up to 3 batches of 500), 285 s with the defaults. The watchdog max-runtime for `home_filings` is requested at 330 s (S4): 285 s plus container start (split risk 3, up to about 20 s) leaves about 25 s of margin, against about 15 s at 300 s. A run still going at the next 5-minute tick is the split spec's due rule to handle. When the watchdog kills a run anyway, it finalises the row as `failed` with message `killed` (section 2). Happy-path cost: 8 feeds at a 5 to 8 s gap is 40 to 64 s plus fetch time; with a slow NSE, 8 x (8 + 20) = 224 s, just inside the 240 s deadline. This figure has no retries: one request retry on a slow feed adds `backoff_s` plus a timeout, about 50 s, which is why the retry has its own deadline check (5.4).

### 5.4 Request policy

- Gap: uniform random `gap_min_s` to `gap_max_s` (5 to 8 s, decided, overview 7.3) before each feed's first request. Sequential requests only.
- **Request retry:** one retry per feed for a `retry` response. It waits `backoff_s` (30 s), and no random gap is added. It happens only when `now + backoff_s + request_timeout_s <= deadline_at`.
- Timeout `request_timeout_s` 20 s. `post_timeout_s` 15 s.
- Session: `nse_session()` (cookie warm-up against `https://www.nseindia.com`) with a browser-like `User-Agent`. Whether the archive host needs that cookie is **to verify** (T0). A failed warm-up is logged and not fatal, as today.
- Risk note: the NSE terms prohibit automated collection and storing (overview 4.1); the user accepted this for personal use (overview section 5). One request in flight per container; the shared cooldown covers every container.
- `redact_error(text) -> str` (T3a) strips query strings and token-like substrings before any text goes into a run message. (`_redact` in `mongo.py` masks only a Mongo URI password.)

### 5.5 Retention and purge (deferred, Z5 decided 2026-11-10)

Retention stays 3 years (overview 7.4); the purge, its endpoint, the `DELETE` grant and the `retention_days` key are deferred. D5 (confirmed: purge inside the `home_filings` run, no separate job) is the future design: delete `published_at < now - interval '1095 days'` through an API endpoint, with `now` passed by the caller, and only after at least one feed succeeded. Until then `home_events` grows without bound; at 8 feeds this is small.

## 6. Module layout and interfaces (one module, Z6 decided)

| Path | Contents | Change |
|---|---|---|
| `scanner/home_events.py` | everything below | new |
| `scanner/collect/sources.py` | `class HomeFilings(Source)`, `SOURCES["home_filings"]` | modify |
| `scanner/collect/settings.py` | `_valid_param_keys` gains `home_filings` (section 7) | modify |
| `scanner/marketdata/factors_postgres.py` | public `nse_session()`, header dict for the feeds | modify |
| `scanner/pg/db.py`, `scanner/pg/migrate.py` | 4.5 | modify |
| `tests/test_collect_sources.py` | source set includes `home_filings`; docstring fixed | modify |
| `db/migrations/NNN_...` and down; `db/events_migrations/001_...` and down | 4.1 | new |
| `server/src/homeEventsBatch.ts` (`validateBatch(body) -> {rows, invalid}`, `buildInsert(rows) -> {text, values}`), `homeEventsRoute.ts` (`registerHomeEventsRoutes(app, deps)`), `homeEventsAuth.ts` (`checkIngestToken(header, role)`, result `ok`, 401 or 403), `config.ts` (`eventsPoolConfig()`), `app.ts` (`AppDeps` gains `eventsTx` and `checkToken`), `index.ts` wiring | 4.6 | new / modify |
| `start.ps1`, `env.template` | 4.5 | modify |

Interfaces in `scanner/home_events.py`:

```python
class ParseError(Exception): ...             # the body is not usable XML for this feed (feed-level)

@dataclass(frozen=True)
class Feed: feed_code: str; url: str; event_type: str; feed_tier: str
            default_enabled: bool; flagged: bool
FEEDS: tuple[Feed, ...]                      # the eight rows of 4.0

@dataclass(frozen=True)
class ParseResult: items: list[dict]; dropped: int      # dropped = items missing a field or with a bad date

@dataclass(frozen=True)
class FetchResult: outcome: str; items: list[dict]; dropped: int; detail: str
    # outcome: "ok" | "blocked" | "transient" | "fatal" (5.2); detail is redacted, never a URL with a query

class Cooldown(Protocol):                    # S2 supplies the real one; tests inject a fake
    def active(self, exchange: str, now: datetime) -> bool: ...
    def block(self, exchange: str, now: datetime, reason: str) -> None: ...
    def reset(self, exchange: str) -> None: ...

def parse(feed_code: str, body: bytes) -> ParseResult                    # raises ParseError
def dedupe_key(feed_code: str, source_id: str | None, source_url: str, published_at: datetime) -> str
def filter_items(items: list[dict], universe: dict[str, str])
    -> tuple[list[dict], dict[str, int]]     # kept items with isin filled; counts keys: universe
def to_event_row(feed: Feed, item: dict) -> dict            # exchange = "NSE" from the "nse:" prefix; published_at ISO 8601 with offset
def classify_response(status: int | None, content_type: str, body: bytes) -> str   # "ok"|"blocked"|"retry"|"fail", table in 5.2
def redact_error(text: str) -> str
def load_universe(conn) -> dict[str, str]                   # symbol -> isin
def fetch_feed(feed: Feed, *, session, cfg: dict, parse_fn, sleep, rng, clock, deadline_at) -> FetchResult
    # session.get(url, timeout=) returns an object with .status_code, .headers (mapping) and .content (bytes); clock() -> datetime
def post_events(rows: list[dict], *, base_url: str, token: str, http, timeout_s: int) -> dict
    # batches of at most 500; http.post(url, json=, headers=, timeout=) returns an object with .status_code and .json();
    # sums {inserted, duplicates, invalid}; raises RuntimeError without echoing the token on a non-2xx
def run_cycle(params: dict, now: datetime, *, feeds: tuple[Feed, ...], parse_fn, universe: dict, session, post,
              sleep, rng, clock, cooldown: Cooldown) -> dict   # the 5.1 result dict; `now` is the run start (rotation index and the 4.3 date tests)
```

`cfg` is the merged params (section 7) with defaults filled in. `feeds` and `parse_fn` are injected so T4b and T4c are testable with fake feeds before `FEEDS` and the real parsers exist (T4e, T7); `HomeFilings` passes the module's `FEEDS` and `parse`. `cooldown.block` takes a reason string of the form `blocked:<feed_code>`. Every collaborator that touches the network, the clock, randomness, sleeping, the cooldown or a database is a parameter, so tests inject fakes. `post` is a callable `post(rows) -> {"inserted", "duplicates", "invalid"}` that `HomeFilings` builds from `post_events` (T4d).

## 7. Configuration

`collector_settings.params` for `home_filings`; `_valid_param_keys` allows exactly these. A missing key falls back to the default.

| Key | Default | Unit | Status |
|---|---|---|---|
| `gap_min_s` | 5 | seconds | decided (overview 7.3) |
| `gap_max_s` | 8 | seconds | decided (overview 7.3) |
| `request_timeout_s` | 20 | seconds | proposed |
| `post_timeout_s` | 15 | seconds | proposed |
| `backoff_s` | 30 | seconds | proposed |
| `run_deadline_s` | 240 | seconds | decided in substance (split spec); value proposed |
| `enabled_feeds` | the feeds whose `default_enabled` is true (all eight) | list of `feed_code` | decided (Q4) |

Validation, done by `run_cycle` at the start of a run (5.1 step 1): every numeric value is a positive number, `gap_min_s <= gap_max_s`, and every `enabled_feeds` entry is a `feed_code` in `FEEDS`. `_valid_param_keys` checks key names only. The API base URL and token location are environment and secret-store items (4.6), not params.

Cooldown keys, `retention_days` and `bse_map_refresh_days` are gone (owned by S2, deferred, and BSE-deferred). The ingest token and events database names are in 4.5 and 4.6. Nothing secret goes into `env.template`.

## 8. Tests and acceptance

Offline suite: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`. Server: `npm test --prefix server`. One test method per name below. Counts are the count of names.

| File | Test names | Count |
|---|---|---|
| `tests/test_home_events_pure.py` | `dedupe_key`: with_id, fallback_hash, stable_across_refetch, different_link_differs. `filter_items`: not_in_universe, isin_filled. `classify_response`: none_retry, status_403_blocked, status_429_blocked, html_200_blocked, empty_200_fail, xml_200_ok, status_500_retry, status_404_fail, status_302_fail. Mapper: event_row_keys, exchange_from_prefix. `redact_error`: strips_query_string, strips_token_like. `nse_session`: warmup_failure_not_fatal | 20 |
| `tests/test_home_events_parsers.py` | one per feed on its synthetic fixture (8); fixture_exists_for_every_feed (1, enabled at the last T7 step); empty_feed, malformed_xml_raises, html_200_raises (3); missing_field_dropped_and_counted, bad_date_dropped_and_counted (2) | 14 |
| `tests/test_home_events_run.py` | cooldown_active_skipped_zero_requests; block_on_third_feed_failed_and_cooldown_blocked; success_then_block_twice_never_resets; reset_called_once_after_block_free_run; reset_skipped_when_cooldown_seen_mid_run; status_500_retries_once_then_continues; retry_skipped_when_deadline_too_close; deadline_stops_loop_ok_with_message; deadline_zero_feeds_failed; all_feeds_fail_failed; non_transient_feed_failure_marks_failed; transient_failure_ok_with_message; rejected_counts_in_message; gap_within_bounds_seeded; rows_go_to_post; invalid_rows_mark_failed; bad_config_failed; post_failure_stops_loop_api_error_no_cooldown_change; start_feed_rotates | 19 |
| `tests/test_home_events_client.py` | batches_of_500, bearer_header, summed_counts, non_200_raises_without_token | 4 |
| `tests/test_pg_migrate_events.py` (new, no server) | files_events_dir, files_default_is_main, cli_db_argument, unknown_db_raises | 4 |
| same file, needs Postgres | apply_events_creates_table (`SkipTest` without Postgres; a skip is not a pass) | 1 |
| `tests/test_home_filings_registration.py` (uses `pgschema`) | registration_rows_exist_after_apply, mode_is_manual (`SkipTest` without Postgres; a skip is not a pass) | 2 |
| `tests/test_collect_sources.py` | source set updated; existing tests still pass; plan_makes_no_call_and_full_shape (new, T4d) | updated, +1 |
| `tests/test_collect_settings_sources.py` | `home_filings_param_keys_accepted_and_unknown_rejected` (T4a) | 1 |
| `server/src/homeEventsBatch.test.ts` (T5a, pure) | valid_row_accepted, bad_enum_rejected_and_counted, bad_date_rejected_and_counted, non_http_url_rejected, headline_too_long_rejected, sql_uses_on_conflict_do_nothing, over_500_rows_rejected | 7 |
| `server/src/homeEventsRoute.test.ts` (T5b, injected deps) | missing_token_401, wrong_role_403, valid_batch_returns_counts, oversize_413 | 4 |
| Manual, one run (T2b) | `docker compose exec -T scanner-postgres psql -U <admin> -d postgres -tAc "SELECT datname FROM pg_database WHERE datname='market_scanner_events'"` returns one row after the first `start.ps1` run and after a second run with no error; `python -m scanner.pg.migrate --db events --status` lists 001 | 1 |

Enum consistency: the three enum lists (Python `FEEDS`, SQL CHECKs, the TypeScript validator) have no test tying them together; T5a's validator and T4e's `FEEDS` are checked against 4.0 by hand at review. The Python-versus-TypeScript enum disagreement this would hide is caught at run time by `invalid_rows_mark_failed` (5.2).

## 9. Ordered tasks, acceptance and must-not-change

Tasks become `plan_add` entries only after approval. Each has an acceptance command. Tool-call limit per task: 25, except T2a, T4d, T5c and T9 at 40. "Its tests" in an acceptance column means the tests named for that task in section 8, run with `unittest -k <name>`. Tasks that edit `scanner/home_events.py` run one at a time in the order T3a, T3b, T3c, T4b, T4c, T4e, T6, T7 (T3a creates the file). **Must not change in any task:** `scanner/factors.py` (including `matches_orderbook`, `_save_announcements` and the order-win lists; the order-win feed is deferred), the existing `announcements` and `collector_*` DDL, `collect.py` (split S1a owns it), and any migration number the split spec claims.

| Task | Depends on | Does | Acceptance |
|---|---|---|---|
| T0 | a network path NSE accepts (user or a networked agent; not a local-model task) | Capture one sample per default-enabled NSE feed into `data/home_samples/nse_<Name>.xml`. Write into 4.0: each feed's URL, the tag-to-key table, the date format and timezone, whether an id exists, whether the cookie warm-up is needed, feed depth (items and span), and whether the two `results` feeds list the same filings (4.4). | Section 4.0 has a table row per feed with no "to verify" left, each URL answered with a successful fetch; one fixture hand-checked against its sample |
| T1 | split spec assigns the migration number; `pgschema` | `NNN_home_filings_registration.sql` and its down file (`manual` mode), and `tests/test_home_filings_registration.py` | `.venv/Scripts/python.exe -m unittest tests.test_home_filings_registration -q` runs against Postgres (not skipped); `python -m scanner.pg.migrate --status` lists it |
| T2a | none | `db.py`, `migrate.py`, `pgschema` optional argument, events SQL and down, `POSTGRES_EVENTS_DB` name, `tests/test_pg_migrate_events.py`. Must not change: `pgschema.create` default and `migrate.apply()` with no arguments | `.venv/Scripts/python.exe -m unittest tests.test_pg_migrate_events tests.test_pg_dsn tests.test_collect_sources -q` |
| T2b | T2a | `start.ps1` create and migrate stages, image rebuild note, `env.template` (`POSTGRES_EVENTS_DB`) | the manual check in section 8 |
| T3a | none | creates `scanner/home_events.py` with `redact_error`; adds public `nse_session()` and the header dict in `factors_postgres.py`. Must not change: `_nse_session` behaviour | `.venv/Scripts/python.exe -m unittest tests.test_home_events_pure -q` (its `redact_error` and `nse_session` tests) |
| T3b | T3a | `Feed` (no `FEEDS` yet), `dedupe_key`, `to_event_row`, `ParseResult`, `ParseError` | same module, its dedupe and mapper tests |
| T3c | T3b | `filter_items`, `classify_response`, `FetchResult`, `Cooldown` | same module, its filter and classify tests |
| T4a | none | `_valid_param_keys` for `home_filings` | `.venv/Scripts/python.exe -m unittest tests.test_collect_settings tests.test_collect_settings_sources -q` |
| T4b | T3c | `fetch_feed` with an injected session, `parse_fn` and `clock` | `tests.test_home_events_run` with `-k gap_within_bounds -k status_500_retries -k retry_skipped` |
| T4c | T4b | `run_cycle` with injected `feeds`, `parse_fn`, a fake cooldown and a fake `post` | `.venv/Scripts/python.exe -m unittest tests.test_home_events_run -q` (19 tests) |
| T4d | T4c, T4a, T6; split S1a, S2; the token-path decision (4.6) | `HomeFilings`, `events_source = True`, `SOURCES` entry, the real `Cooldown` adapter, `post` built from `post_events`, updated `tests/test_collect_sources.py` (including `plan_makes_no_call_and_full_shape`) | `.venv/Scripts/python.exe -m unittest tests.test_collect_sources tests.test_home_events_run -q` |
| T4e | T0, T3b | `FEEDS` with real URLs, first parser (`nse:Financial_Results`), its synthetic fixture | `.venv/Scripts/python.exe -m unittest tests.test_home_events_parsers -q` (that feed's tests) |
| T5a | none | `homeEventsBatch.ts` (`validateBatch`, `buildInsert`), vitest, in the style of `collectorRefresh.ts` | `npm test --prefix server -- homeEventsBatch` |
| T5b | T5a | `homeEventsAuth.ts`, `homeEventsRoute.ts` with injected `eventsTx` and `checkToken`, the `AppDeps` extension in `app.ts`. No `index.ts` change | `npm test --prefix server -- homeEventsRoute`; `npx tsc --noEmit --project server` |
| T5c | T5b, T2a; split S3 | `eventsPoolConfig()`, the events pool, health check coverage and `index.ts` wiring. `server/src/index.ts` is modified in the working tree and `server/src/kiteToken.ts` is untracked: T5c starts only after those changes are committed or stashed by the user | `npx tsc --noEmit --project server`; `npm test --prefix server`; with the server running, `GET /api/health` reports the events pool |
| T6 | T4c | `post_events` per the section 6 interface, with a stubbed `http` | `.venv/Scripts/python.exe -m unittest tests.test_home_events_client -q` |
| T7 | T0, T4e | Remaining parsers, one per task (T7a to T7g, one per feed, each with a fixture) | `tests.test_home_events_parsers` with `-k <that feed>`; the completeness test is enabled at the last parser |
| T9 | T0, T1, T2b, T4d, T5c, T7; split S1a, S1b, S3, S4, S5a | `home_filings` in `config/collector_services.json` (with `exchange: nse`) and its compose service; `config/collector_runtime.json` entry (330 s); a settings update that sets the cron `*/5 8-20 * * 1-5` and flips the mode to `scheduled` | `docker compose --profile collectors config` is valid; one run-once start (`docker compose --profile collectors run --rm home_filings`), then `SELECT status, message FROM collector_runs WHERE source = 'home_filings' ORDER BY id DESC LIMIT 1` returns status `ok` |

The fundamentals trigger (4.7) and the reconciler (4.4) have no task here. Only T0, T4e, T7 and T9 wait on samples; T1 to T3, T4a to T4d, T5 and T6 do not. (T8, the order-win feed, is deferred and has no task; T10, the fundamentals queue, is moved out.)

## 10. Decisions

| ID | Decision | Status |
|---|---|---|
| D1 | NSE transport is XML, for long-term support. | **Decided 2026-11-10.** URLs and tags from T0. |
| D2 | Run isolation is the run deadline plus one container per source; no shared lock. | **Decided** (split spec). |
| D3 | Universe is `symbol_sector` rows with an ISIN. | **Confirmed 2026-11-10.** |
| D4 | Where a feed has no attachment text, the order-win rule matches by category only. | **Confirmed 2026-11-10**; moot while the order-win feed is deferred (4.3a), kept for whoever builds it. |
| D5 | Purge runs inside `home_filings`, no separate job. | **Confirmed 2026-11-10**; build deferred (Z5). |
| D6a | Event tier 1 and 2 list. | **Open.** Code constant, not a column. |
| D6b | Trading-day calendar source is the Upstox market-holidays API. | **Decided source; endpoint and token to verify.** Moot here (Z3 deferred); kept for the later migration. |
| D7 | Cross-source reconciliation required. | **Decided as required; build deferred** (4.4). |
| D8 | Events in a separate database on the same server. | **Decided 2026-11-10.** |
| D9 | Only the Fastify server touches the events database. | **Decided 2026-11-10.** |
| D10 | One container per source, with the watchdog. | **Decided; owned by the split spec.** |
| Cooldown scope | Per exchange, shared `exchange_cooldown` table. | **Decided 2026-11-10.** |
| Fixtures | Samples not committed; synthetic fixtures committed. | **Decided 2026-11-10.** |
| Ingest floor, future-date test | Add a floor (earlier); then deferred with `date_future`. | **Deferred 2026-11-10** (4.3). |
| Cuts | Z2, Z3, Z4, Z5, Z6, Z7, Z12. | **Decided 2026-11-10.** Z7 amended by Q1 (`8-20`). Z12 (order-win feed) deferred by Q2. |
| Q1 to Q4 | Cron `8-20` kept; order-win feed deferred; fundamentals trigger to its own spec; all eight feeds on. | **Answered 2026-11-10** (below). |
| Fundamentals trigger | Filed results with catch-up. | **Decided 2026-11-10.** Design moved to its own spec (4.7). |

**Answered 2026-11-10:**
- **Q1.** Cron stays `*/5 8-20 * * 1-5`.
- **Q2.** The order-win feed is deferred to the split spec's freshness work; no T8.
- **Q3.** The fundamentals trigger moves to its own spec; no T10.
- **Q4.** All eight feeds, including `Related_Party_Trans` and `Shareholding_Pattern`, are on by default (not off as proposed).

**Answered 2026-11-10 (review 3 questions):** D8/D9 stay as decided. The ingest floor and the future-date test are deferred (4.3). The cooldown mid-run re-read, the 30 s request retry, the start-feed rotation, the per-feed deadline accounting, and keeping 4.3a, 4.4 and 4.7 in this spec: all kept. A 403 on one feed stays `blocked` (5.2). Open: whether to poll the two quarterly feeds (`Related_Party_Trans`, `Shareholding_Pattern`) less often than every 5 minutes (explained to you; default is to keep every 5 minutes).

Still open, not blocking a task here: cooldown cap (2 h in the split spec against 3 h in overview 7.3, owned by S2); overview edits (14 feeds to 8, the 7.3 off-hours polling and 7.4 "stored counts" lines, 5.1 BSE); Z3's later migration and market-cap source; the collector's token file path; the Upstox holidays endpoint and token; `REVOKE CONNECT` on the events database; events database backup schedule.

## 11. Next steps

1. You decide the open design points (the reply that carries this revision lists them: D8/D9 cost, and four smaller simplifications).
2. Update the stale parent docs (`home-events-filings.md`, overview 5.1, 7.3, 7.4, 8.1, 8.2, and the split-docs index).
3. You approve the design. Only then are `plan_add` tasks written and dispatched. Nothing is committed from this spec.
4. In parallel, not blocking approval: T0 (capture the NSE samples from a network path that works, and fill 4.0), and the split-spec session adds the S1a, S3, S4, S5a and citation items in section 2 and assigns migration numbers.
