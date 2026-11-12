# Home events: exchange filings build spec (approved, revision 4)

- Status: approved by the user (confirmed 2026-11-11). Revision 4 of 2026-11-10, after the third review ([home-events-filings-spec-review3.md](../progress/home-events-filings-spec-review3.md), NOT READY, fixes applied here) and the second review ([home-events-filings-spec-review2.md](../progress/home-events-filings-spec-review2.md), NOT READY) and the first ([home-events-filings-spec-review.md](../progress/home-events-filings-spec-review.md)). The user answered Q1 to Q4 on 2026-11-10 (applied below: cron `8-20` kept; order-win feed deferred; fundamentals trigger moved out; flagged feeds on). Revision 4 has the third-pass fixes. The fourth review is in [home-events-filings-spec-review4.md](../progress/home-events-filings-spec-review4.md). The design is approved (confirmed by the user 2026-11-11); tasks may be dispatched from this revision.
- Owner: Vaibhav Pavtekar
- Screen: Home, shortlist and event feed (`docs/designs/ui-redesign-spec.md` sections 5.1 and 6)
- Parent docs: [home-events-filings.md](home-events-filings.md) (owned rules), [home-event-sources.md](home-event-sources.md) (overview).
- Governing spec: where this spec and [collector-split-spec.md](collector-split-spec.md) disagree on the runner, the due rule, the cooldown or a migration number, the collector-split spec governs (user, 2026-11-10).

## 0. How to read this spec

**Legend.** *Decided* = the user decided it (date given). *Proposed* = my default, usable unless you change it. *Open* = needs an answer or a sample before the task that depends on it. *Confirmed* = the user confirmed my proposal (date given). *Deferred* = decided, not built here. *Parked* = never requested. *To verify* = a fact I could not check from here. NSE feed samples were captured for T0 (§9). BSE returned HTTP 403 from here, so the BSE statements rest on the pinned reference repos' code.

**Decision tags.** The user's cuts of 2026-11-10 are cited by tag: Z2 defer BSE; Z3 drop the value and market-cap columns; Z4 drop `rows_rejected`; Z5 defer the purge; Z6 one module; Z7 weekday-hours cron; Z12 reuse the `announcements` store (decided, then deferred with the order-win feed, Q2). Z2 to Z7 and Z12 are the cuts the user accepted; no other Z tag is in force. D1 to D10 and Q1 to Q4 are listed in section 10; T0 to T9 in section 9; S1a to S8 are the collector-split spec's slices; M1 to M14 are numbered findings of [review 2](../progress/home-events-filings-spec-review2.md).

**Terms.**
- *Feed tier* (`high_priority`, `catalyst`): the overview 5.1 grouping of a feed, stored on each row. *Event tier* (1 or 2, overview 7.1): the Home display priority. It is a code constant on the read path, not a column. D6a is still open, so Home should not filter by event tier yet.
- *Tick*: one scheduled start of the source (every 5 minutes inside the cron window).
- *Events source*: a source that needs the Fastify API (split spec 4.5): `home_filings`.
- *Request retry*: the single re-request of one feed inside a run (5.4). *Block stop*: the run stops after a 403, a 429 or an HTML block page (5.2). *Run retry*: the split spec's rule for starting a failed run again (its 4.2). At a 5-minute cadence the run retry is moot: the next tick is the retry.
- *Slice*: the first end-to-end build of one feed (T4e).

**Numbering.** Sections 4.0 to 4.7 (and 4.3a) keep their numbers because the collector-split spec cites 4.6 (events endpoints) and 4.7 (fundamentals trigger).

## 1. Scope

- Ingest **8 NSE feeds** (section 4.0), all written to the events database as `home_events`. **Decided 2026-11-10 (Z2): BSE is deferred.** **Decided 2026-11-10 (Q2): the order-win feed `nse:Online_announcements` is deferred** to a later spec (4.3a). The overview's "14 feeds were planned" (its section 7.3, which cites its section 5.1) is 8 NSE feeds now; the 5 BSE feeds and the order-win feed come later.
- Store only events for the scanner universe (D3, decided; 4.3).
- Out of scope: BSE, the order-win feed (`announcements` reuse, Z12, deferred with it), news RSS, Telegram, Upstox News, the macro calendar, the LLM stage, the Home read path (ui-redesign spec), purge (Z5), the value and market-cap columns (Z3), the cross-source reconciler (4.4) and the fundamentals trigger (4.7, own spec).

## 2. Dependencies on the collector-split spec

This spec does not build the runner. It consumes what the split spec builds. What is needed, and what must be **added to the split spec** (it is another session's document, so these are requests, not edits):

| Needed | Task | Status |
|---|---|---|
| `execute_source` extraction and a `skipped` write path | S1a | exists in the split spec |
| **`run()` may return `status` in `ok`, `failed`, `skipped`; `execute_source` persists it with counts and `message`; run-once exits non-zero on `failed`** | S1a | **add to split spec, with a test** (review M1). Without it a block records `ok`. |
| Run-once container, `--source`, API-health check for events sources | S1a, S3 | exists. **Add:** how run-once learns a source is an events source (this spec: class attribute `events_source = True`, T4d). |
| `source_cooldown` table, one row per host (every source on its own host is independent) | S2 | exists. S2 owns the backoff and cap values. |
| `GET /internal/due` omits a source whose host has an active cooldown | S5a | **add:** a `host` field per entry in `config/collector_services.json` (`home_filings` is `nse`), populated in T9. |
| Watchdog finalises a `running` row when it kills a container (`failed`, message `killed`) and max-runtime in `config/collector_runtime.json` | S4 | **add** (review M7). Value for `home_filings`: **330 s** (5.3: the worst case is 285 s plus container start of up to about 20 s). |
| The split spec cites "filings spec 4.7" for the fundamentals queue (its 4.2, the 4.6 table "weekly sweep" row, S5a and S7). 4.7 is now a stub | S5a, S7 | **add:** repoint those four citations to the future `fundamentals-trigger-spec.md`. |
| Fastify `server` containerised and reachable from collector containers | S3 | **add** (review M13). Today Fastify runs on the host and binds `127.0.0.1:8081` only (`server/src/index.ts`), so no container can reach it, and the old claim "internal routes are compose-only" was wrong. Internal routes will be token-gated, on the same port as `/api/*` (split 4.5). |
| A migration number | S2 | The split spec says S2 claims 047. S2a takes "a number when written". S5a needs a migration and names none, and S8's `filings` cron migration (its 4.6) is a fourth claimant. **This spec's registration migration takes the next number after those three are assigned** (shown as `NNN`), so T1 waits for that assignment. The events database has its own series (`db/events_migrations/001_...`). |

Build order, derived from section 9's Depends column. No task needs another first: T0 (samples), T2a, T3a, T4a, T5a. Then T2b (after T2a), T3b, T3c, T4b, T4c, T6 one at a time in that order, because they all edit `scanner/home_events.py` (created by T3a); T5b (after T5a), T5c (after T5b, T2a and S3). Then T4d (after T4c, T4a, T6, S1a, S2 and the base-URL value in 4.6, split S3/S4). T4e and T7 need T0. T1 needs the migration number from the split spec. T9 last (needs S1a, S1b, S3, S4, S5a).

## 3. Existing code this spec reuses or must not duplicate

| Item | Where | Use |
|---|---|---|
| NSE cookie warm-up | `scanner/marketdata/factors_postgres.py` `_nse_session` (private, bare `Session`; warm-up failure is not fatal) and the `UA` header dict (`Accept: application/json, text/plain, */*`, which already allows XML) | T3a added a public `nse_session()` and a header dict for the feeds. `_nse_session` keeps its behaviour. |
| Run base class | `scanner/collect/sources.py` `Source.run(params, now, dry_run)`, `plan()`, and the `SOURCES` dict | `HomeFilings(Source)`. `plan()` is pure: no network, no database, no sleep. `collect.py` indexes `result['fetched']` and `result['new']` on a dry run, so `plan()` must return the full result shape. |
| Source registration | `scanner/collect/settings.py` `ensure_sources()` and `_valid_param_keys` | `_valid_param_keys` returns an empty set for an unknown source, so every `home_filings` param was rejected until T4a added the key set (built, `7c48bec`). The `{}` in the registration row is accepted. |
| Existing test pinning the source set | `tests/test_collect_sources.py` (the exact set of 7 names; its docstring says "5 feed sources") | Updated in T4d. |
| Throwaway-schema fixture | `tests/pgschema.py` (calls `migrate.apply()` with no arguments; `SkipTest` without Postgres) | Main-database tests only. **A skipped test is not a pass.** |
| Migration runner | `scanner/pg/migrate.py` (one `MIGRATIONS` directory constant, one `schema_migrations` table with column `filename`, one transaction per file, `--status`, a `_BOOT` statement that creates the table) and `scanner/pg/db.py` (`connect(**kw)` forwards keyword arguments to `psycopg.connect`; `dsn()` refuses a DSN that disagrees with `POSTGRES_DB` through `_check_dsn_agrees`) | Both changed in T2a (`ebeefe2`, 4.5). |
| Down-step precedent | `db/migrations/down/045_*.down.sql`, `046_*.down.sql` | 046's header reads "NOT run by the migration runner" and "Take a pg_dump first.". 045 cites `docs/progress/rollback.md`, which exists (added in PR #85). |

The order-win rule (`matches_orderbook`) and the announcements writer (`_save_announcements`) in `scanner/factors.py` are not used here, because the order-win feed is deferred (4.3a). They must not change.

`collector_settings.source` has no CHECK constraint (created in `001_core.sql`, replaced in 013, dropped in 014, dropped again with `IF EXISTS` in 041); its constraint is the foreign key to `collector_sources`. The name `home_filings` needs no CHECK change. `symbol_sector.isin` is nullable (`025_symbol_sector.sql`), hence the `IS NOT NULL` in the universe query.

### 3.1 External libraries (evaluated 2026-11-11; none adopted)

Method: shallow clones read in a scratch folder. Nothing was installed, imported or run, and no request was sent to NSE or BSE from the clones. Findings come from reading the code, so runtime behaviour, live endpoints and the PyPI releases are not verified. Re-check before adopting anything.

**NSE.** The feeds in 4.0 are `nsearchives` RSS. Neither library fetches them.

| Library | Commit read | Licence | What the code does | Decision |
|---|---|---|---|---|
| `BennyThadikaran/NseIndiaApi` (PyPI `nse` 5.1.1, imported as `from nse import NSE`) | `b7fd7eb73f900986d327171d571952492663b31c` | GPL-3.0 | Calls JSON endpoints under `https://www.nseindia.com/api`, such as `/corporate-announcements`, `/corporates-financial-results` and `/corporates-corporateActions`. No RSS or XML code. Synchronous `httpx`; a 3 requests-per-second limiter; up to six attempts (one initial call and five retries, `RetryConfig.total = 5`) on 429, 502, 503, 504 and timeout, connect, read and remote-protocol errors, with exponential waits of 1, 2, 4 and 8 s (capped at 8 s), each scaled by jitter, and a Retry-After header honoured when present; cookies saved to `download_folder/cookies.txt`; 15 s timeout; Firefox 118 User-Agent with a fixed Referer. | Reference only (endpoint list, retry design). GPL-3.0: read the design, do not copy code. Installing needs approval. |
| `RuchiTanmay/nselib` (PyPI `nselib` 2.5.1) | `e3b22ada842193f148dfcb2408ab1d06a44babfe` | Apache-2.0 | Calls `https://www.nseindia.com/api/corporates-financial-results` and related paths, then GETs one XBRL document per result row and parses it into a DataFrame. On the financial-results path: no pacing, no retries, no timeouts. Each call creates one new session and makes two GETs for the result list, then one plain GET per result row for the XBRL documents (2 + N GETs, N = rows returned). One failed row aborts the batch. Writes no files. | Do not adopt. |

Pasted examples, checked against the code:
- `NseIndiaApi`: the example does not run. `NseIndiaClient`, `Category` and `corporate_filings` do not exist. The call the code supports (read from the code, not run) is `with NSE(download_folder=".") as nse: nse.financial_results(segment="equities", period="quarterly", symbol="HDFCBANK")`. It returns JSON metadata and downloads no XBRL or attachment.
- `nselib`: `financial_results_for_equity(from_date, to_date, period, fo_sec, fin_period)` matches the signature. Dates are `dd-mm-YYYY`.

Pacing and backoff for this spec come from the overview's request policy, not from either library. `scanner/marketdata/factors_postgres.py` waits 3 s before each first attempt and 10 s before each retry; both are shorter than that policy. Its warm-up GET and User-Agent may be reused (section 3 table).

**BSE.** Deferred (Z2). No BSE code is built or adopted now.

| Repository | Commit read | Licence | What the code does | Decision |
|---|---|---|---|---|
| `RuchiTanmay/bseindia` (v1.1) | `dd97a8baaf49d1dda1af1d0ff8df813088fa6e5b` | Apache-2.0 | Wraps the security master (`LitsOfScripCSVDownload`, returns `security_code`, `symbol`, `isin_no`), bhavcopies, historical prices, market-cap statistics, bulk and block deals and the F&O summary. No announcements, filings, results or corporate actions. Most public functions return DataFrames; `stock_info` returns a dict, and `derivatives.market_summary()` returns a tuple of two DataFrames. No public function returns raw XML. Cookie warm-up GET to `https://www.bseindia.com/` only in `bse_urlfetch` (`libutil.py:76`). No pacing and no retries. The `libutil.py` calls set `timeout=30` (lines 76, 77, 127); the public derivatives helpers take none (only the internal `derivatives/get_func.get_market_summary` has one, default 30 s). Some calls set no timeout, for example `equity/equity_data.py:35` and `derivatives/get_func.py:58`. Writes a cache CSV into the package directory. Its logger is set to DEBUG and writes to stdout; the package itself emits only INFO and WARNING records. The README says 3.9+; `setup.py` lists 3.10 and declares no `python_requires`. `bseindia.derivatives` needs 3.10 (PEP 604 annotation at `derivatives/get_func.py:19`; read from the code, not run). The README uses the top-level `bseindia.all_listed_securities()` (`libutil.py:233`). The `equity.all_listed_securities()` form in the pasted recommendation is not that API. | Possible later reference for the security master (`bse_scrip_map`) and the warm-up pattern. Not for filings. |
| `BennyThadikaran/stock-news` | `03b2191dd7d14c36316bbf31d80abfcf87e19123` | GPL-3.0 | A terminal script. Calls the PyPI package `bse~=3.3.4` for announcements, actions and the result calendar. That package was not reviewed, so its BSE hosts are unknown. Sequential, no pacing; the first network error exits the run. Runs everything at import. Writes `src/watchlist.json` when `-f` is used. | Drop. |
| `Rushi128/BSE-India-API-PDF-Downloader` | `ff8213f3a5e1e6f915a0821e9391cb9b7ab0c52a` (HEAD commit dated 2024-03-15; remote push date not checked) | MIT | One file, `app.js`. The README names `index.js` and `npm start`, which do not exist. Requests announcements from `api.bseindia.com` `AnnSubCategoryGetData` for the current UTC date (`app.js:14`; between 00:00 and 05:30 IST this is the previous IST date), with `strCat=-1`, `strType=C`, `strSearch=P`, and empty `strScrip` and `subcategory` fixed. It pages through `pageno` until an empty page, then saves each attachment as `./pdfs/<SLONGNAME>.pdf`. `SLONGNAME` is not sanitised, so a `..` segment writes outside `./pdfs` (`app.js:39`). Fixed Chrome 84 User-Agent, no timeout, no pacing, and a page loop with no cap. | Drop. Do not run it. |

BSE status: the terms page returned HTTP 403 and was not read, so the terms gate stays open. None of the three repositories fetches the five BSE feeds named in the overview (`announcements.aspx`, `CorpActionFeed.aspx`, `FinancialResultsFeed.aspx`, `ShareholdingPattern_Feed.aspx`, `notices.xml`).

Not verified: the PyPI releases of `nse`, `nselib` and `bse` (only the cloned commits were read), the committed BSE security CSV, live endpoint behaviour, and the NSE and BSE terms. Before any BSE work: read the terms, then check the endpoints live from the collector container at the request policy's pacing.

**BSE route (deferred, Z2; planned, not built).** Call the BSE announcements endpoint `AnnSubCategoryGetData/w` directly over HTTP with our own client. Do not import `stock-news` (GPL-3.0; it pins `bse~=3.3.4`). Security master: `LitsOfScripCSVDownload` (from `bseindia`, Apache-2.0; reference only). `bse-pdf-downloader` (MIT) is reference only; its path traversal at `app.js:39` means its code is not copied. The method names beyond the user's reference are chosen in this spec. PyPI release dates for these libraries were not checked; the user accepted this on 2026-11-11.

### 3.2 Symbol master: shared code references (recorded 2026-11-12)

Decided 2026-11-12. NSE RSS items carry no ISIN, so the name is matched first through `company_reference`: one exact name key that maps to one (symbol, ISIN) pair. BSE matching is ISIN-first: the rule was accepted on 2026-11-12. The BSE source was approved on 2026-11-12; see the blocker file (`docs/designs/home-events-t4f-blocker-recommendations.md`). The BSE build stays deferred (Z2).

Method: each reference below was checked against the code. Nothing was run. External repos are read from pinned commits.

| Repository or project | Commit | Path and lines | What the code does | How we use it |
|---|---|---|---|---|
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/pit.py` 534-555 (`symbol_to_isin_as_of`) | Returns the ISIN from the newest NSE bhavcopy row for the symbol on or before the date (as_of <= date; trade_date >= since when given). None if no match. | The only dated symbol-to-ISIN read, derived from `nse_bhavcopy_row`. No stored symbol master. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/pit.py` 622-639 (`index_symbol_isins_as_of`) | Returns the set of ISINs that index constituent snapshots in the window gave for the symbol. More than one ISIN means a holder change. | Second symbol-to-ISIN read. Filing adapters use it to cross-check and detect conflicts. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/pit.py` 202-216 (`entity_isin_earliest_links_as_of`) | For each ISIN, returns the earliest EntityIsin link with as_of <= date. | Read side of the ISIN-to-entity link, with earliest-evidence semantics. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/models.py` 163-177 (`EntityLinkBasis`, `QuarantineReason`) | EntityLinkBasis has only FIRST_SEEN. QuarantineReason has whole-file reasons (DUPLICATE_ISIN at 172) and per-row reasons (INVALID_ISIN at 176). | Never-guess reason codes for ISIN identity in index-list ingest. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/models.py` 183-200 (`Entity`) | Append-only identity row with a sha256 content_hash check and model_version NULL. Lineage across ISIN changes is computed at read time from isin_change (`isin_lineage_as_of`). | The identity above ISIN. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/models.py` 203-227 (`EntityIsin`) | ISIN format CHECK, unique (isin, as_of), and a basis column. A DB trigger (migration 0003) rejects one ISIN linked to two entities. | The ISIN-keyed identity table a symbol master would sit on. The single-entity rule is enforced in the DB. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/models.py` 333-340 (`BhavcopyQuarantineReason`) | Whole-file SHAPE_CHANGED and ROW_COUNT. Per-row MALFORMED_ROW, INVALID_ISIN (339) and DUPLICATE_ROW (340). | Bhavcopy uses duplicate_row for a repeated ISIN and series, not duplicate_isin. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/models.py` 346-375 (`NseBhavcopyRow`) | Table with trade_date, isin, symbol, series and prices. The symbol resolves to the ISIN on the nearest bhavcopy on or before a date. Reparses append rows. | The table that `symbol_to_isin_as_of` reads as the dated ticker-to-ISIN source. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/db/models.py` 570-579 (`CorporateActionQuarantineReason`) | Includes INVALID_ISIN (575) and UNKNOWN_SYMBOL (576). | unknown_symbol is the never-guess outcome when the symbol read returns None. It is defined here, not on the bhavcopy enum. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/compute/isin.py` 1-33 (`is_valid_isin`, `isin_check_digit`) | Format regex, then the ISO 6166 Luhn check digit over the letter-expanded body. Called by the bhavcopy, index-list, XBRL, SHP, Upstox and corporate-actions parsers and resolvers. concall_drop calls neither directly. | The validity gate on the entity key. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_bhavcopy/parser.py` 42-49 (`EQUITY_SERIES`) | Frozen set {EQ, BE} with a curation comment (42-48). Other series are skipped, not quarantined. | Decides which bhavcopy rows become symbol-to-ISIN evidence. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_bhavcopy/parser.py` 185-227 (row loop in `parse_bhavcopy`, defined at 143) | Skips non-EQ/BE series. Quarantines malformed and invalid-ISIN rows. A repeat of an ISIN and series is quarantined as DUPLICATE_ROW; the first occurrence is kept. | Where bhavcopy symbol-to-ISIN evidence is produced. No inference from the symbol. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_indices/parser.py` 1-11 (module docstring) | Documents the layout (Company Name, Industry, Symbol, Series, ISIN Code). Company names are stored for review only and never identify a company. | States the identity rule: the ISIN column is the key. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_indices/parser.py` 51-53 (`EQUITY_SERIES`, `_INDIAN_ISIN`) | EQ/BE frozenset and an Indian-prefix ISIN regex. | Constrains which constituent rows can create ISIN identities. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_indices/parser.py` 138-152 (validation loop in `parse_constituent_list`, defined at 103) | Line 138 quarantines INVALID_ISIN and line 143 NON_EQUITY_SERIES. Lines 149-152 reject the whole list with DUPLICATE_ISIN when an ISIN repeats. | The duplicate_isin and invalid_isin never-guess rules for index-list ingest. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_indices/adapters.py` 204-218 (`_link_entities`) | Creates an entity and a FIRST_SEEN entity_isin row for each ISIN with no earlier link. Appends an earlier entity_isin row when loaded evidence predates the link. | The writer that fills the ISIN-keyed entity identity from index lists. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_xbrl/adapters.py` 80-109 (`resolve_isin`) | Takes the filing ISIN if present. Otherwise collects the bhavcopy and index-list symbol reads as of the file date. Raises on no ISIN or disagreeing ISINs. | The reference never-guess cross-read for symbol to ISIN. The BSE path should follow it. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_shp/adapters.py` 85-116 (`resolve_isin`) | The same cross-read as XBRL. BHAVCOPY_WINDOW is 10 days (48) and INDEX_LIST_WINDOW is 190 days (49). Raises on disagreement. | A second copy of the same rule. It is repeated per adapter, not shared. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/concall_drop/adapters.py` 86-112 (`resolve_isin`) | Bhavcopy and index-list symbol reads as of the document date. Rejects conflicting ISINs and unresolved symbols. | A third adapter with the same symbol-to-ISIN cross-read. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/corporate_actions/adapters.py` 84-101 (ISIN resolution loop) | Calls `symbol_to_isin_as_of` with the day before the ex-date (90). On None, quarantines the row as UNKNOWN_SYMBOL with no ISIN attached. | Shows the unknown_symbol never-guess path. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/nse_shp/parser.py` 370-380 (`_check_identifiers`) | Compares the XBRL entity identifier with the scrip-code or NSE symbol scheme. Rejects on mismatch or unknown scheme. It is the only caller-side check of scrip_code (called at line 161 only). | A filing-internal check only. The scrip code is never mapped to an ISIN. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `migrations/versions/0008_xbrl_financial_filing.py` 71 (`financial_filing.scrip_code`) | Nullable text column with no FK or lookup to entity_isin. | The scrip code is stored as plain text evidence only. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/upstox/parser.py` 55-67 (`instrument_key`, `isin_from_url`) | `instrument_key` builds NSE_EQ and the ISIN (segment at line 36). `isin_from_url` pulls the ISIN from a candles URL (`_URL_KEY` at 50) and returns None for non-matching URLs. | Upstox is keyed by ISIN directly. The round trip is a regex on the URL, not a symbol lookup. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/upstox/parser.py` 237-244 (`require_isin`) | Returns the ISIN from the request URL only if it is a valid NSE equity ISIN. Otherwise raises CandlesRejected(UNKNOWN_INSTRUMENT). | The never-guess gate on the vendor response side. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `ingest/broker_holdings_drop/parser.py` 24 (`EXCHANGES`) | A frozenset of NSE and BSE. | Broker holdings store BSE rows that share an ISIN with NSE rows. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `core/compute/holding_weights.py` 5 (module docstring) | Says the same company on NSE and on BSE is one position. | States that the ISIN, not the exchange code, identifies the security. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `migrations/versions/0003_entity_and_index_snapshots.py` 166-183 (`entity_isin_single_entity` trigger) | A plpgsql function (166) raises if the ISIN is already linked to a different entity. The BEFORE INSERT trigger is at 180-183. | A DB-level guard that keeps one ISIN on one entity. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `CLAUDE.md` 125-128 (entity key rule) | Entity key is ISIN, not ticker. ISIN changes go through an entity table driven by corporate_action, never by string matching. | The project rule that the symbol master is keyed by ISIN with dated history. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `CLAUDE.md` 137-142 (universe never-guess and symbol map rules) | Uncertain membership is never guessed. The dated symbol-to-ISIN map is still needed before rebalance dates can be added. A today's list is never used for past dates. | The point-in-time and never-guess rules. |
| Cluade Agent Swarm - Market Analyst | working tree (HEAD 4d737af; cited files identical to HEAD) | `CLAUDE.md` 438 (source row for the dated ticker-to-ISIN map) | Dated ticker-to-ISIN map sourced from NSE bhavcopy archives, trust official_archive. | The source class for the symbol master. It is the same source as the bhavcopy row table. |
| Market-Scanner | 0863338 | `scanner/company_reference.py` 70 (`EQUITY_LIST_URL`) | Constant for the NSE full equity list (EQUITY_L.csv). | The NSE equity list URL used by the company-reference job. |
| Market-Scanner | 0863338 | `scanner/company_reference.py` 73 (`equity_list_rows`) | Builds rows from EQUITY_L records keyed by (symbol, ISIN). Reads SYMBOL, NAME OF COMPANY, SERIES and ISIN NUMBER. Keeps the first row for a repeated pair. | The parser for the NSE equity list, which is keyed by ISIN. |
| Market-Scanner | 0863338 | `scanner/isin_resolver.py` 26 (`MASTER_URL`) | Upstox NSE instrument master URL (NSE.json.gz). The comment at 25-26 says it is used by the monthly job, not at run time. | The Upstox NSE master source, separate from EQUITY_L. |
| Market-Scanner | 0863338 | `scanner/company_reference_job.py` 44-51 (`fetch_csv_bytes`, uses `EQUITY_LIST_URL` at 47) | Downloads the NSE equity list with `requests.get`, timeout 30. | The download of EQUITY_L.csv for the monthly job. |
| Market-Scanner | 0863338 | `scanner/home_events.py` 110 (`to_event_row` docstring) | Docstring text says BSE is deferred (Z2), so any non-nse prefix is refused. | The code-side marker that BSE is deferred. |
| Market-Scanner | 0863338 | `docs/designs/home-events-filings-spec.md` 81 (BSE deferred statement) | "Deferred (Z2). No BSE code is built or adopted now." | The spec-side marker that BSE is deferred. |
| Market-Scanner | 0863338 | `docs/designs/home-events-filings-spec.md` 93 (BSE route) | Direct `AnnSubCategoryGetData/w` call with our own client. No stock-news import. `LitsOfScripCSVDownload` and bse-pdf-downloader are reference only. | The planned BSE route that the deferred build will follow. |
| RuchiTanmay/bseindia (v1.1) | dd97a8baaf49d1dda1af1d0ff8df813088fa6e5b | `bseindia/libutil.py` 189-197 (`_download_security_master`) | GETs `LitsOfScripCSVDownload/w` with segment=Equity. Raises NSEdataNotFound on non-200. Reads the first 9 columns. No retries or pacing. This is the only live BSE security-master fetch and the only BSE source of symbol to isin_no. | reference only |
| RuchiTanmay/bseindia (v1.1) | dd97a8baaf49d1dda1af1d0ff8df813088fa6e5b | `bseindia/libutil.py` 130-172 (`_normalize_security_frame`) | Renames Security Code, Security Id and ISIN No (147-157). Upper-cases symbol (168). Drops empty or nan rows. Dedupes on security_code only (171). ISIN is not a key and is not validated. | reference only |
| RuchiTanmay/bseindia (v1.1) | dd97a8baaf49d1dda1af1d0ff8df813088fa6e5b | `bseindia/libutil.py` 175-186 (`_read_security_cache`, `_write_security_cache`) | Cache at `bseindia/bse_security_list.csv`. The committed cache header has a lowercase isin column, which the normalizer ignores, so isin_no becomes the string 'None' (read, not run). | reference only. With the committed cache, the default path gives no usable ISIN. |
| RuchiTanmay/bseindia (v1.1) | dd97a8baaf49d1dda1af1d0ff8df813088fa6e5b | `bseindia/libutil.py` 233-271 (`all_listed_securities`, `get_scode_from_symbol`) | Returns the cache if non-empty and refresh is False. Otherwise downloads, falling back to the cache on error. Exact upper-case symbol match. On a miss, runs a live search and appends the row to the cache. README line 140: refresh=True bypasses the cache. | reference only. refresh=True is needed for live data. |
| RuchiTanmay/bseindia (v1.1) | dd97a8baaf49d1dda1af1d0ff8df813088fa6e5b | `bseindia/libutil.py` 200-230 (`_extract_search_candidates`, `_lookup_security_in_live_search`) | Calls `ListScripSmartSearch/w` and parses security_code, name and symbol from HTML. No ISIN is returned. | reference only. Rows added by live search have no isin_no. |
| BennyThadikaran/NseIndiaApi | b7fd7eb73f900986d327171d571952492663b31c | `src/nse/NSE.py` 922-945 (`NSE.equity_meta_info`) | One GetQuoteApi call with functionName=getMetaData and the upper-cased symbol. The sample response has an isin field. GPL-3.0. | reference only (endpoint only) |
| BennyThadikaran/NseIndiaApi | b7fd7eb73f900986d327171d571952492663b31c | `src/nse/NSE.py` 1068-1093 (`NSE.list_equity_stocks_by_index`) | Requests equity-stock-indices (or equity-stockIndex for two special lists) and returns JSON with a data list. The sample has no isin key. | reference only |
| BennyThadikaran/NseIndiaApi | b7fd7eb73f900986d327171d571952492663b31c | `src/nse/NSE.py` 307-359 (`NSE.equity_bhavcopy`) | Builds the bhavcopy URL, downloads it and returns the extracted CSV path. The library does not parse the file, so any ISIN column is left to the caller. | reference only |
| RuchiTanmay/nselib | e3b22ada842193f148dfcb2408ab1d06a44babfe | `nselib/capital_market/capital_market_data.py` 447-466 (`equity_list`) | Fetches EQUITY_L.csv. Raises FileNotFoundError on non-200 or parse failure. Keeps only SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING and FACE VALUE. No ISIN is kept. | reference only. Cannot serve as an ISIN-keyed master as is. |
| RuchiTanmay/nselib | e3b22ada842193f148dfcb2408ab1d06a44babfe | `nselib/capital_market/capital_market_data.py` 376-400 (`bhav_copy_equities`) | Fetches the CM bhavcopy zip and returns the CSV unfiltered (column selection commented out at 398-399). A non-200 other than 403 gives an empty DataFrame. 403 raises. | reference only. The only ISIN-bearing NSE path in this repo, per date, if the CSV carries an ISIN column. |
| RuchiTanmay/nselib | e3b22ada842193f148dfcb2408ab1d06a44babfe | `nselib/constants.py` 36-37 (`bhavcopy_new`) | Lists the new bhavcopy layout, including ISIN and SYMBOL. Not referenced elsewhere (lines 33 and 36 only). | reference only. Documents expected column names only. |
| RuchiTanmay/nselib | e3b22ada842193f148dfcb2408ab1d06a44babfe | `nselib/libutil.py` 162-182 (`nse_urlfetch`) | Opens a new session, GETs the origin for cookies, then GETs the target with those cookies. No timeout and no retry. | reference only. The request pattern for the pacing comparison in 3.1. |

GPL-3.0 code (NseIndiaApi) is never copied. These rows record endpoints and design only.

Not found in the pinned repos:
- EQUITY_L or any NSE equity-list ingest (no adapter or parser under ingest/ reads EQUITY_L; the only constituent-list ingest is ingest/nse_indices for Nifty 50 and Next 50 CSVs)
- NSE.json or any Upstox instrument master file or instrument-master download (Upstox candles are keyed directly by ISIN via instrument_key, no instrument list is fetched)
- Any BSE security-id or Upstox security-id handling (no hits for security_id outside the BSE/NSE exchange enum and scrip_code columns)
- A BSE scrip-code to ISIN mapping or lookup (scrip_code is stored as text in financial_filing and shareholding_filing and checked only against XBRL identifiers; no read maps it to ISIN)
- A standing symbol-to-ISIN table or symbol master store (none found; the dated lookup is derived from nse_bhavcopy_row by symbol_to_isin_as_of)
- unknown_symbol on the bhavcopy quarantine enum (it exists only on CorporateActionQuarantineReason at core/db/models.py:576)
- duplicate_isin on the bhavcopy path (bhavcopy uses duplicate_row; duplicate_isin appears only in QuarantineReason for whole index-list files at core/db/models.py:172 and ingest/nse_indices/parser.py:150)
- Search of the Market-Scanner sibling repo was out of scope and not performed; .claude/worktrees was excluded from the search, and docs/temporal-model.md and docs/corporate_actions_reference.md matched the search but were not read
- No NSE equity master keyed by ISIN in any of the three repos. NseIndiaApi has no equity list CSV reader (no EQUITY_L or equity-list code), and nselib equity_list() drops the ISIN column.
- No BSE security master in BennyThadikaran/NseIndiaApi or RuchiTanmay/nselib. The LitsOfScripCSVDownload and api.bseindia.com calls exist only in RuchiTanmay/bseindia.
- No reverse ISIN-to-symbol lookup in any of the three repos.
- NseIndiaApi lookup() (src/nse/NSE.py lines 265-305) returns company name, symbol and series only. Its sample (src/samples/lookup.json) has no isin key, so it is not an ISIN source.
- Not verified: live endpoint behaviour, the committed cache's runtime result (inferred from reading, not run), PyPI releases of nse, nselib and bse, and the NSE and BSE terms. Nothing from these repos was installed, imported or run.

## 4. Feed registry and data model

### 4.0 Feed registry and parsed item

**D1 decided 2026-11-10: XML, for long-term support.** The URL pattern, item structure and date formats below were verified from the T0 samples on 2026-11-11.

**Source format (verified 2026-11-11).** One file per feed at `https://nsearchives.nseindia.com/content/RSS/<Name>.xml`. Each is an RSS 2.0 channel. Every `item` has exactly four children: `title`, `link`, `description` and `pubDate`. No feed has an id, `guid`, symbol or ISIN element, no `item` child element carries attributes (the `rss` root and `atom:link` do), and no `description` contains HTML. The 142 items across the eight feeds were identical in all four runs (host and container, warm and cold): no mismatch in title, link, description or pubDate. The channel `lastBuildDate` differs between runs, so change detection must compare items, not file hashes. Warm runs GET the NSE homepage first (`https://www.nseindia.com`, which returned 403 on host and container); cold runs do not. Every feed attempt returned 200 (16 per environment). The run reports (`data/home_samples/<host or container>/report.json`) give each feed's fetch URL as `https://nsearchives.nseindia.com/content/RSS/<Name>.xml`. The warm-up GET is recorded separately, at `https://www.nseindia.com`. The SHA-256 and byte count of all 32 saved files match the feed entries. This is one day's sample, not proof for other days.

| feed_code | items | oldest to newest pubDate (IST) | age on 11-Nov-2026 (days) | pubDate format | `link` |
|---|---|---|---|---|---|
| `nse:Financial_Results` | 3 | 03-Nov-2026 09:55 to 10:29 | 8 | `DD-Mon-YYYY HH:MM:SS` | one listing page for all items |
| `nse:Integrated_Filing_Financials` | 20 | 10-Nov-2026 20:09 to 11-Nov-2026 15:08 | 0 to 1 | `DD-Mon-YYYY HH:MM:SS` | per filing (XBRL) |
| `nse:Sast_Regulation29` | 20 | 28-Oct-2026 14:58 to 03-Nov-2026 12:54 | 8 to 14 | `DD-Mon-YYYY HH:MM` | per filing (zip); 16 distinct links in 20 items |
| `nse:Sast_Regulation31` | 20 | 21-Oct-2026 14:09 to 29-Oct-2026 11:13 | 13 to 21 | `DD-Mon-YYYY HH:MM:SS` | per filing (zip) |
| `nse:Corporate_action` | 58 | 11-Nov-2026 03:11:42 (all 58) | 0 | `DD-Mon-YYYY HH:MM:SS` | one listing page for all items |
| `nse:Corporate_Governance` | 0 | none (channel only) | none | none | none |
| `nse:Related_Party_Trans` | 20 | 21-Feb-2025 15:12 to 11-Sep-2026 17:49 | 61 to 628 | `DD-MON-YYYY HH:MM:SS` (10 items) and `DD-MON-YYYY HH:MM.SS` (10 items) | per filing (XBRL) |
| `nse:Shareholding_Pattern` | 1 | 11-Nov-2026 12:21:07 | 0 | `DD-Mon-YYYY HH:MM:SS` | per filing (XBRL) |

The channel `lastBuildDate` is RFC 822 with `+0530` in most feeds, `DD-Mon-YYYY HH:MM:SS` in Corporate_action, and absent in Financial_Results. The parser does not need it.

**Mapping to the parsed item** (proposed; the item dict is below):

| Key | Source | What the sample shows | Status |
|---|---|---|---|
| `source_id` | none | no feed has an id | `None` for every feed, so the id branch of 4.2 never runs |
| `source_url` | `link` | per filing for five feeds; one shared listing page for Financial_Results and Corporate_action | the item's `<link>` element, whitespace squashed. NOT NULL. An item with no link is dropped and counted as a `parse` rejection (4.3). The listing page is not used as a fallback. |
| `company` | `title` | company name (first item of each feed checked); Corporate_action titles are `<COMPANY> - Ex-Date: DD-Mon-YYYY` (58 of 58) | the squashed title. For `Corporate_action`, the company part before ` - Ex-Date:`. |
| `headline` | `description` | feed-specific text, not prose (see the description shapes below) | the squashed `<description>` text, truncated to 500 characters. If the squashed description is empty, use the squashed title. Maximum seen in the real samples: 220 characters (Financial_Results). |
| `symbol` | none | not in any feed | `symbol` and `isin`: resolved from the company name in the item title by exact match against the NSE constituent list (§4.3). Unresolved names are dropped. |
| `isin` | none | not in any feed | `symbol` and `isin`: resolved from the company name in the item title by exact match against the NSE constituent list (§4.3). Unresolved names are dropped. |
| `published_at` | `pubDate` | naive, IST; format per feed (table above) | attach `Asia/Kolkata` |
| `title` | `title` | company name (first item of each feed checked); Corporate_action titles are `<COMPANY> - Ex-Date: DD-Mon-YYYY` (58 of 58) | the raw stripped text; squashed only where the dedupe key and the headline use it. |
| `description` | `description` | feed-specific text, not prose (see the description shapes below) | the raw stripped text; squashed only where the dedupe key and the headline use it. |

**Description shapes (checked 2026-11-11 on the host cold sample; identical in all four runs).**
- `Financial_Results` and `Corporate_action`: pipe-separated `KEY:VALUE` pairs, for example `RELATING TO:First Quarter |AUDITED/UNAUDITED:Unaudited` and `PURPOSE:INTERIM DIVIDEND - RS 11 PER SHARE` (3 of 3 and 58 of 58 items).
- `Shareholding_Pattern`: pipe-separated pairs, some with a space before the colon, for example `AS ON DATE : 29-Oct-2026 | PR_AND_PRGRP: 69.25 | PUBLIC_VAL: 30.75 | ...` (1 item).
- `Integrated_Filing_Financials`: pipe-separated tags with no `KEY:VALUE`, for example `Integrated Filing- Financials|Original|` or `Integrated Filing- Financials|Revision|` (20 of 20 items).
- `Sast_Regulation29` and `Sast_Regulation31`: one `KEY : VALUE` pair with a space before the colon and no pipe, for example `NAME(S)OF THE ACQUIRER AND ITS(PAC) : Jamnagar Utilities & Power Private Limited`. Maximum 126 characters (Sast_Regulation29) and 111 (Sast_Regulation31).
- `Related_Party_Trans`: one `KEY : VALUE` pair with no pipe, for example `PERIOD END DATE : 30-SEP-2024`. Maximum 29 characters.
- `Corporate_Governance`: no items.

**Date rule.** Parse each feed with its fixed pattern and attach `Asia/Kolkata`. `strptime` accepts the upper-case months in Related_Party_Trans. The dot variant (for example `24-MAY-2025 22:28.31`) fails `%H:%M:%S`, so the parser needs a rule for it (decision 4, 2026-11-11: replace the dot with a colon, then parse). Read as IST, no item is later than its feed's `lastBuildDate`. Read as UTC, six Integrated items (dated 11-Nov-2026, 12:14:51 to 15:08:07) and the Shareholding item (12:21:07) would be later than their feed's build time (15:20:18 and 15:10:36 IST in the host cold run; build times differ by run, and the result is the same in all four runs), while the 14 Integrated items dated 10-Nov would stay earlier. The feed times are IST.

**RPT dot variant (decided 2026-11-11).** `Related_Party_Trans` uses `DD-MON-YYYY HH:MM:SS` on some items and `DD-MON-YYYY HH:MM.SS` on others. Replace the dot with a colon before parsing. Colon-form items contain no dot, so the rule leaves them unchanged. All 20 sample items parse with this rule.

**Duplicates on the sample.** Sast_Regulation29 has three exact duplicate pairs (identical in all four fields). It also has one pair that shares `link`, `title` and `pubDate` and differs only in `description`: the two rows name different acquirers. Corporate_action's 58 items differ only in `title` and `description`. Financial_Results' three items share one title (Gammon India Limited) and one link, and differ in `description` and `pubDate`. Over the 142 sample items, the first key (`link` and `pubDate`, superseded by §4.2) gives 81 rows and loses 61 items (57 from Corporate_action, 4 from Sast_Regulation29). Keying on `link`, `title`, `description` and `pubDate` together gives 139 rows and merges only the three exact duplicates.

**Overlap between the results feeds.** Financial_Results and Integrated_Filing_Financials share no link and no title on the sample, so on that day they list different filings. The reconciler (4.4) still has to handle the case where they do overlap.

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
{ "source_id": str | None,   # none of the eight feeds has one (see Source format)
  "source_url": str,         # the feed's `link`; a shared listing page for Financial_Results and Corporate_action
  "symbol": str,             # from name resolution (§4.3), not from the feed (normalise: strip, uppercase)
  "isin": str | None,        # from name resolution (§4.3), not from the feed
  "company": str | None,
  "title": str,              # raw stripped text; squashed only where the dedupe key and the headline use it
  "description": str,        # raw stripped text; squashed only where the dedupe key and the headline use it
  "headline": str,
  "published_at": datetime } # timezone-aware; IST source times converted with zoneinfo "Asia/Kolkata"
```

Sample and fixture policy:
- **Amended 2026-11-11: the fixture for each of the eight feeds is the real T0 sample file (host/cold run), copied byte for byte. These fixtures are part of the T0 change; at HEAD (b0ab71e), seven of them are still synthetic. The samples under `data/home_samples/` are not committed.** T0 saves them under `data/home_samples/<host or container>/<cold or warm>/` (ignored by git), named `nse_<Name>.xml`, because a colon in a filename is illegal on Windows. Each environment's run report is `data/home_samples/<host or container>/report.json`. The fixtures use the same naming in `tests/fixtures/home_events/` and are committed with the T0 change. The mapping is `feed_code.replace(":", "_")`.
- All eight fixtures in `tests/fixtures/home_events/` (8 feeds, 142 items) are byte copies of the real samples in `data/home_samples/host/cold`. The link shapes are counted by feed, not by fixture: per-filing links for five feeds (Integrated_Filing_Financials, Related_Party_Trans, Sast_Regulation29, Sast_Regulation31, Shareholding_Pattern); one shared listing page for two feeds (Financial_Results, Corporate_action); no items for one feed (Corporate_Governance). The 58 items of `Corporate_action` all share one pubDate. The tag-to-key table is in this section (verified 2026-11-11). The sample's other edge cases are carried by the real sample files: three groups of exact duplicates in Sast_Regulation29, one same-link pair in Sast_Regulation29 that differs only in `description`, and dot-variant times in ten of the twenty Related_Party_Trans dates (for example `24-MAY-2025 22:28.31`).
- A parser handles five cases: an empty feed, malformed XML (`ParseError`), an HTML page served with status 200 (`ParseError`), an item with a missing required field or an unparseable date (the item is dropped and counted in `dropped`), and a normal feed.

**Decisions from the T0 samples (recorded 2026-11-11; the user answered each; the source conflicts are in 4.3 and 5.6):**
1. **Symbol and ISIN source.** Answered 2026-11-11: "from news content". Resolve from the company name in the item title (§4.3). Conflict (a) accepted by the user 2026-11-11 ("agreed"): about 35% of the sample resolves, so about 65% of items are dropped by name.
2. **Source link.** Answered 2026-11-11: the user rejected an empty URL ("No, logically how will you get this information without URL?"), then chose the link carried by each RSS item ("choose link carried by rss item"). The item `<link>` is `source_url`. No empty `source_url`. The listing page is not used.
3. **Dedupe key.** Approved 2026-11-11 ("okay"). See §4.2.
4. **RPT dot-variant dates.** Decided by the orchestrator at the user's request ("you decide the best"). See the RPT rule in §4.0.
5. **Headline.** Decided by the orchestrator ("you decide best"). Squashed description, 500-character cap, title fallback (mapping table).
6. **First-run depth.** Answered 2026-11-11: "split by per month run from last 3 year. each batch with 1 year run." Conflict (b) answered 2026-11-11 ("rss 1 year old is fine, 3 year old data is for nse, bse, rbi, fed data"): about one year of RSS depth is accepted for the filings feeds; three-year history is for NSE, BSE, RBI and Fed. See §5.6.
7. **Is 20 a cap.** Decided by the orchestrator ("you decide best"). A feed returning exactly 20 items is flagged `at_cap:<feed_code>` in the run message (§5.2). It is not treated as a cap and does not page.

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

**Cron `*/5 8-20 * * 1-5` (IST, weekdays 08:00 to 20:55). Decided 2026-11-10 (Q1), changed from `8-15`.** Revision 2 used `8-15`, which I read into "weekday-hours" (Z7). The review showed that results are filed mostly after 15:30, so a 15:55 stop delays the highest-value events and the fundamentals trigger by up to 16 hours, and the split spec runs `filings` until 20:52. `8-20` follows the split spec. Consequences: about 12 ticks an hour; with 8 default feeds that is about 96 NSE requests an hour inside the window; exchange holidays still start a run that finds nothing (split risk 8); a block pauses every NSE source through the shared cooldown; the 08:00 run after an overnight gap may bring a burst of results. Feed depth (does a feed list enough items to cover the overnight gap) was checked on one sample day (4.0). Integrated Filing Financials' 20 items span about 19 hours, longer than the 11-hour gap from 20:55 to 08:00, on that day. Four feeds return exactly 20 items, which may be a cap. Decision 7 flags such a feed as `at_cap:<feed_code>` and does not treat it as a cap. Depth remains a precondition for production use of the slice, and needs checking on more days.

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

**Adopted key (approved 2026-11-11, decision 3).**
- With a source id: `feed_code:source_id`. An empty or whitespace-only id counts as no id, and a padded id is stripped before the key is built.
- Without an id: `feed_code:` followed by the SHA-256 hex digest of the UTF-8 bytes of `json.dumps([source_url, squash(title), squash(description), utc_iso], ensure_ascii=False)`.
- `squash` collapses runs of whitespace to one space and strips both ends. `utc_iso` is `published_at.astimezone(timezone.utc).isoformat()`.
- A naive `published_at` raises ValueError.
- The key covers the item's content. The same item refetched gets the same key. A revised notice under the same link gets a new key.

**Deviation from the approved wording (accepted by the user 2026-11-11).** The approved wording joined the fields with `|`. The Financial_Results description contains `|` (`RELATING TO:First Quarter |AUDITED/UNAUDITED:Unaudited`), so a pipe join can collide: `A|B` with `C`, and `A` with `B|C`, both join to `A|B|C`. The JSON array has no such ambiguity. This is a byte-level change to the key input. The pipe-joined wording was never implemented, so no stored key depends on it. Checked 2026-11-11: no fix was needed, since both encodings give 139 distinct keys on the 142 fixture items. The user asked for a fix only if one was needed, so the JSON encoding stands.

`run_cycle` drops repeated keys inside one batch before posting. The API inserts with `ON CONFLICT (dedupe_key) DO NOTHING`. A run that crosses 500 rows commits in separate transactions, which is safe because inserts are idempotent. No feed carries an id (4.0), so only the second branch applies. An amended filing that keeps its id is ignored (first wins); one with a new id is a new row; linking them is the reconciler's job (4.4).

### 4.3 Universe and rejections

Symbol and ISIN come from the company name in the item title. For `Corporate_action`, the company name is the text before ` - Ex-Date:`.

Two universes, one per consumer. The split is the user's decision (2026-11-12).

- **Scanner universe (752):** the NIFTY Total Market plus holdings list, stored in `index_constituents` (migration 048). Read with `scanner.constituents.load_constituents()`. The default path reads the database. A CSV is read only when an explicit `override_path` is given. This universe is used by the scanner only.
- **Events, symbol, and fundamental universe (full NSE list):** the NSE equity list, stored in `company_reference` with `source = 'nse_csv'` (migration 047). The events path resolves names against this list. It does not read `symbol_sector` for its universe.

Name resolution (events path):

- Normalise both sides with `normalise_name` (`scanner/company_reference.py`): uppercase; `&` becomes `AND`; each of `.,'()-` is replaced by a space (not deleted); `LIMITED` and `LTD` become `LTD`; runs of spaces collapse to one. Stored `name_key` values use the same function. Any change to this function needs a full recompute of `name_key` in one transaction, plus a drift check (see the concepts brief, Decision 1).
- Match is exact on the normalised name against `company_reference.name_key`. A name that matches more than one (symbol, ISIN) pair is ambiguous and is rejected. A name with no match is rejected. Both count as `universe` rejections.
- A resolved item is accepted only if its ISIN agrees with any ISIN the item carries.

Universe gates: the 752 universe applies to the scanner only. The events path has no separate universe check. A name that resolves against the full NSE list is already a listed symbol, so a second check against the same list cannot reject it (decided 2026-11-12).

Rejection reasons, one vocabulary everywhere (`parse`, `universe`):

- `parse`: counted by `parse()` itself (missing required field, unparseable date) as `dropped` (`ParseResult.dropped`). The run message reports it as `rejected parse=<n>` (5.2).
- `universe`: the name did not resolve (no match, or ambiguous).

**Deferred (decided 2026-11-10): the ingest floor (`date_floor`, `ingest_floor_days`) and the future-date test (`date_future`).** The sample contradicts "recent items only": Related_Party_Trans holds items up to 628 days old (back to 21-Feb-2025), and Sast_Regulation29 and Sast_Regulation31 hold items 8 to 21 days old (4.0). Consequence: an item with a wrong date (far past or far future) is stored as given. The API still rejects a `published_at` without an offset (4.6). Decision 6 (2026-11-11) accepted about one year of RSS depth; the floor itself is still deferred and must be settled before the first run.

**Loss to know about:** a rejected item is gone. If the universe grows, earlier events are not recoverable from this table.

Sample coverage (142 real items, measured 2026-11-11, against the 751 universe): 50 matched, 0 ambiguous, 92 unmatched. Against the full NSE list (measured 2026-11-12): 111 matched, 0 ambiguous, 31 unmatched. Per feed (751 universe): Financial_Results 0 of 3; Integrated_Filing_Financials 2 of 20; Sast_Regulation29 3 of 20; Sast_Regulation31 10 of 20; Corporate_action 35 of 58; Related_Party_Trans 0 of 20; Shareholding_Pattern 0 of 1.

**Conflict (a), accepted by the user 2026-11-11 ("agreed"), now superseded for events.** Under the 751 universe, about 65% of items were dropped by name. The full NSE list lifts events coverage to 111 of 142. The 751 universe still applies to the scanner.

**Partly built, not wired.** `filter_items` (`scanner/home_events.py:145-162`) takes a `universe` dict (symbol to ISIN). The events name lookup is `load_index_for_source(conn, 'nse_csv')` in `scanner/company_reference.py`. Its `.by_name` resolves names, and its `.universe` is the dict that `filter_items` takes. No runner calls `run_cycle` with these yet. That wiring is a separate task (filings T9). The docstring at `scanner/home_events.py:151` now names this loader.

### 4.3a Order-win feed (`nse:Online_announcements`): deferred (Q2, decided 2026-11-10)

The feed is not built in this spec. Z12 (write it to the existing `announcements` table) stays on record as the intended route, but the review found it unsafe to build now, and the user agreed to defer it. The findings that block it:

- `_save_announcements` never backfills `attchmnt_text`, so a row first written by this feed with empty text stays text-less, and D4 (category-only matching) becomes permanent for those rows.
- The `(isin, an_dt, "desc")` key match with the per-symbol collector's rows is unverified; a mismatch would double-count rows against the 3-per-stock cap.
- `matches_orderbook` is Python and the Home read path is Fastify, so who runs the rule, and how rows from the main and events databases are merged, is undecided (a ui-redesign spec question).

Whoever picks this up needs a sample of the feed (T0 covers it if asked), the key-match test and the reader decision. Nothing in this spec depends on it.

### 4.4 Cross-source reconciliation (required by the user 2026-11-10; build deferred)

The same event reported twice, an amended filing, or a filing plus an article must appear as one Home item. With BSE and the order-win feed deferred, there is no cross-exchange duplicate here. Two kinds remain: the two `results` feeds (`Financial_Results`, `Integrated_Filing_Financials`) may list the same filing, and an amendment with a new id is a new row; both can use up the 3-per-stock Home cap. T0 checks whether the two results feeds overlap. The reconciler is **not built now** (proposed) and has no task in section 9. When it is built it needs its own spec and review: a `home_reconcile` source talking only to the API, never deleting, adding `event_group_id`, `is_primary` and `supersedes` through its own migration with `GRANT UPDATE` on those columns; pass 1 groups by ISIN, event type and a 24-hour window with the earliest `published_at` as primary; pass 2 (news against filing) waits for the news source and the LLM stage. Until then all rows are shown, not primary rows.

### 4.5 Events database (D8 decided: separate database, same server)

What the repo does today: `scanner/pg/db.py` builds one connection from `POSTGRES_DSN` or `POSTGRES_*`. `connect(**kw)` forwards keyword arguments to `psycopg.connect`, and `dsn()` calls `_check_dsn_agrees`, which refuses a DSN that disagrees with `POSTGRES_DB`. `scanner/pg/migrate.py` has one fixed directory and one `schema_migrations` table. The `scanner` image copies `db/` at build time (`docker/scanner/Dockerfile`), and the build stage in `start.ps1` runs on every start, so `db/events_migrations/` is in the image with no separate rebuild.

Work, split in two tasks:

**T2a (Python, SQL, tests).**
- `scanner/pg/db.py`: `dsn(dbname: str | None = None)` and `connect(dbname: str | None = None, **kw)`. When `dbname` is given it overrides the database name and `dsn()` skips `_check_dsn_agrees`. Default behaviour is unchanged.
- `scanner/pg/migrate.py`: `MIGRATION_DIRS = {"main": db/migrations, "events": db/events_migrations}`, `files(target: str = "main") -> list[Path]`, `apply(target: str = "main")`, `status(target: str = "main")`, CLI `--db {main,events}` (default `main`; `--status` works for both). The parameter is named `target`, not `db`, because the module already does `from . import db` and a string parameter named `db` would shadow it. `events` uses its own `schema_migrations` table inside the events database and the same `_BOOT`. Files are globbed non-recursively, so `down/` never runs. `pgschema.create` calls `apply()` with no arguments, so the default must not change.
- `db/events_migrations/001_home_events.sql` and its down file.
- Environment: `POSTGRES_EVENTS_DB` (default `market_scanner_events`), no secret values.
- Test isolation: `tests/pgschema.py` gains an optional argument so `apply_events_creates_table` applies the events files into a throwaway schema of the main test database (the events SQL refers to nothing outside its own table, so this is valid). `pgschema.create` keeps calling `apply()` with no arguments and its behaviour is unchanged.

**T2b (`start.ps1`, `env.template`).** Mind the PowerShell 5.1 quote-dropping behaviour when passing SQL to a native command; follow the existing `Invoke-Docker` usage.
- A stage before the migrate stage creates the database when missing, idempotently, with no manual step (decided 2026-11-10). `CREATE DATABASE` needs the admin login, so the stage runs `docker compose exec -T scanner-postgres psql -U <admin> -d postgres` with `SELECT 'CREATE DATABASE <events db> OWNER <app login>' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '<events db>') \gexec`. It reads no password and touches no `.env`. The owner is the **app login**, because on PostgreSQL 15 and later a login that does not own the database cannot create tables in `public`. A precondition check confirms the role exists. A non-zero exit is a warning, as for the migrate stage.
- The migrate stage (`start.ps1`, the "Run migrations" step, currently lines 283 and 288) runs `python -m scanner.pg.migrate` and then `python -m scanner.pg.migrate --db events`. That is the only migrate call in `start.ps1`.
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

- Auth: a bearer token per caller (name `home_events_ingest`, proposed) following `secrets-and-roles.md`. Before T5b (built, `902e90f`), there was no Fastify bearer-token pattern in `server/src` (the only `Bearer` uses were outbound Upstox calls); T5b added one in `homeEventsAuth.ts`. Token values never go in the repo, a doc or a log. **Decided 2026-11-11 (user):** external tokens are stored only in the database, encrypted (`app_secret`, S1 to S6). API communication credentials come from a secret file, never from the database or an environment value. So the `home_events_ingest` token is a secret file, `/run/app-keys/home_events_ingest_token` (the decision 15 pattern: one file per token, readable by its owner only), mounted read-only into the collector (which posts) and the API (which checks). Its path is set by config (`HOME_EVENTS_INGEST_TOKEN_FILE`, default that path), the same way `service_client.py` reads `SERVICE_TOKEN_FILE`. The base URL `EVENTS_API_BASE_URL` is non-secret config. Its value depends on the network decision (the API binds `127.0.0.1` only; split S3 and S4) and stays with the split-spec owner. T4d waits for that value and for split S1a and S2.
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
3. Compute `deadline_at = clock() + run_deadline_s` first, then the run takes no universe load. Choose the start feed: `int(now.timestamp() // 300) % n`, then walk the enabled feeds in registry order from that index, wrapping. This rotation stops a persistently slow run from never reaching the last feeds.
4. For each feed, one at a time: (a) stop if `clock() + gap_max_s + request_timeout_s > deadline_at` (`clock` is an injected callable returning the current time, so elapsed time is testable); (b) re-read the cooldown and stop if another container set it; (c) wait a random gap of `gap_min_s` to `gap_max_s`; (d) fetch; (e) classify (5.2); (f) parse (the injected `parse_fn`), filter (4.3), then post the rows via `post`.
5. At the end of a run in which no block occurred, no cooldown was seen mid-run (step 4b) and at least one feed succeeded, call `cooldown.reset("nse")`. Never reset earlier (review M2: a reset after the first success would stop the backoff from ever escalating).
6. Return `{"status", "fetched", "new", "from", "to", "message"}`. `fetched` is the parsed item count after `parse()`. `new` is the sum of `inserted` from the API. The API's `invalid` count is summed too (5.2). `from` and `to` are the earliest and latest `published_at` kept, or `None`.

**Who writes what.** `run_cycle` returns the status dict and writes the cooldown only through the injected object (block and success reset). `execute_source` (split S1a) writes the run row. The cooldown's backoff and cap values belong to S2. Decided 2026-11-11: the backoff classes are fixed in decision A2 (API hosts 3 to 15 minutes; other hosts 15 minutes to 1 hour).

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

**Rejected counts (Z4, decided):** no `rows_rejected` column. The message carries `rejected parse=<n> universe=<n> isin_conflict=<n>` and `invalid=<n>`. This deviates from overview 7.4 as first written ("stored counts are the only trace"). Overview 7.4 now carries that amendment: per-run counts are kept in the run message. The dashboard does not parse `message`.

**Feed at cap (decision 7, decided 2026-11-11).** A feed that returns exactly 20 items may be truncated. Add `at_cap:<feed_code>` to the run message for each such feed. This does not page, retry, or change the feed's status.

### 5.3 Run deadline and isolation (decided by the split spec)

One container per source, so a slow `announcements` run cannot delay `home_filings`; the earlier shared-lock idea is dropped. A feed is started only when `now + gap_max_s + request_timeout_s <= deadline_at`, so with the 20-second timeout the last fetch ends by the deadline. `deadline_at` is set before the name-index load so that query counts against it. Each post has `post_timeout_s`. A feed already fetched is posted even after the deadline. The worst case is therefore `run_deadline_s` plus about three `post_timeout_s` (a feed's items can span up to 3 batches of 500), 285 s with the defaults. The watchdog max-runtime for `home_filings` is requested at 330 s (S4): 285 s plus container start (split risk 3, up to about 20 s) leaves about 25 s of margin, against about 15 s at 300 s. A run still going at the next 5-minute tick is the split spec's due rule to handle. When the watchdog kills a run anyway, it finalises the row as `failed` with message `killed` (section 2). Happy-path cost: 8 feeds at a 5 to 8 s gap is 40 to 64 s plus fetch time; with a slow NSE, 8 x (8 + 20) = 224 s, just inside the 240 s deadline. This figure has no retries: one request retry on a slow feed adds `backoff_s` plus a timeout, about 50 s, which is why the retry has its own deadline check (5.4).

### 5.4 Request policy

- Gap: uniform random `gap_min_s` to `gap_max_s` (5 to 8 s, decided, overview 7.3) before each feed's first request. Sequential requests only.
- **Request retry:** one retry per feed for a `retry` response. It waits `backoff_s` (30 s), and no random gap is added. It happens only when `now + backoff_s + request_timeout_s <= deadline_at`.
- Timeout `request_timeout_s` 20 s. `post_timeout_s` 15 s.
- Session: `nse_session()` (cookie warm-up against `https://www.nseindia.com`) with a browser-like `User-Agent`. The archive host did not need it: the cold runs (no warm-up) returned 200 for all eight RSS feeds on 2026-11-11 (4.0). That is one day's sample. A failed warm-up is logged and not fatal, as today.
- Risk note: the NSE terms prohibit automated collection and storing (overview 4.1); the user accepted this for personal use (overview section 5). One request in flight per container; the shared cooldown covers every container.
- `redact_error(text) -> str` (T3a) strips query strings and token-like substrings before any text goes into a run message. (`_redact` in `mongo.py` masks only a Mongo URI password.)

### 5.5 Retention and purge (deferred, Z5 decided 2026-11-10)

Retention stays 3 years (overview 7.4); the purge, its endpoint, the `DELETE` grant and the `retention_days` key are deferred. D5 (confirmed: purge inside the `home_filings` run, no separate job) is the future design: delete `published_at < now - interval '1095 days'` through an API endpoint, with `now` passed by the caller, and only after at least one feed succeeded. Until then `home_events` grows without bound; at 8 feeds this is small.

### 5.6 First-run backfill (decision 6; conflict (b) answered 2026-11-11)
- The user's answer (2026-11-11), verbatim: "split by per month run from last 3 year. each batch with 1 year run." Read as monthly runs over the last three years, one year per batch.
- **Conflict (b), answered 2026-11-11** ("rss 1 year old is fine, 3 year old data is for nse, bse, rbi, fed data"). RSS depth of about one year is accepted for the filings feeds. Depth on 11 Nov 2026: `Related_Party_Trans` reaches 628 days (its items are 61 to 628 days old); the other feeds reach 21 days or less. No three-year backfill from RSS is built.
- Three-year history is wanted for NSE, BSE, RBI and Fed. The NSE and BSE backfill is not built and has no task in section 9; BSE follows Z2 (deferred).
- RBI and Fed history is placed in the macro child build (`home-events-macro-calendar.md`), not this spec. This placement is the orchestrator's reading of the answer, and the user has not yet confirmed it.
- NSE backfill source: open. The candidate is the NSE JSON endpoint `corporate-announcements` (`from_date` and `to_date` as `dd-mm-yyyy`; items carry `symbol` and `sm_isin`).
- Recommendation: JSON for backfill, RSS for live polling. Not approved. Until the user decides, no NSE three-year backfill is built, and the RSS-only plan stands.

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
FEEDS: tuple[Feed, ...]                      # built (T4e, e3b533f, merged in d6cea2d); the eight rows of 4.0

@dataclass(frozen=True)
class ParseResult: items: list[dict]; dropped: int      # dropped = items missing a field or with a bad date

@dataclass(frozen=True)
class FetchResult: outcome: str; items: list[dict]; dropped: int; detail: str
    # outcome: "ok" | "blocked" | "transient" | "fatal" (5.2); detail is redacted, never a URL with a query

class Cooldown(Protocol):                    # S2 supplies the real one; tests inject a fake
    def active(self, exchange: str, now: datetime) -> bool: ...
    def block(self, exchange: str, now: datetime, reason: str) -> None: ...
    def reset(self, exchange: str) -> None: ...

def parse(feed_code: str, body: bytes) -> ParseResult                    # built (T4e and T7); raises ParseError
def dedupe_key(feed_code: str, source_id: str | None, source_url: str, title: str, description: str, published_at: datetime) -> str
def filter_items(items: list[dict], universe: dict[str, str])
    -> tuple[list[dict], dict[str, int]]     # kept items with isin filled; counts keys: universe (symbol-keyed; name resolution not yet built, see §4.3)
def to_event_row(feed: Feed, item: dict) -> dict            # exchange = "NSE" from the "nse:" prefix; published_at ISO 8601 with offset
def classify_response(status: int | None, content_type: str, body: bytes) -> str   # "ok"|"blocked"|"retry"|"fail", table in 5.2
def redact_error(text: str) -> str
load_index_for_source(conn, 'nse_csv') and fill_from_name   # no new function; name_key -> (symbol, isin): load_index_for_source(conn, 'nse_csv').by_name; a name with two pairs is left out (conflicts); the same call's .universe is the symbol-to-ISIN dict that filter_items takes; §4.3 uses load_index_for_source and fill_from_name for events name resolution
def fetch_feed(feed: Feed, *, session, cfg: dict, parse_fn, sleep, rng, clock, deadline_at) -> FetchResult
    # session.get(url, timeout=) returns an object with .status_code, .headers (mapping) and .content (bytes); clock() -> datetime
def post_events(rows: list[dict], *, base_url: str, token: str, http, timeout_s: int) -> dict
    # batches of at most 500; http.post(url, json=, headers=, timeout=) returns an object with .status_code and .json();
    # sums {inserted, duplicates, invalid}; raises RuntimeError without echoing the token on a non-2xx
def run_cycle(params: dict, now: datetime, *, feeds: tuple[Feed, ...], parse_fn, universe: dict, session, post,
              sleep, rng, clock, cooldown: Cooldown) -> dict   # the 5.1 result dict; `now` is the run start (rotation index and the 4.3 date tests)
```
Built: T6, `post_events` in `scanner/home_events.py` at commit 089a975, tests in `tests/test_home_events_client.py` (4 tests).

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
| `tests/test_home_events_pure.py` | `dedupe_key`: with_id, fallback_hash, stable_across_refetch, different_link_differs, different_description_differs, whitespace_source_id_is_no_id. `filter_items`: not_in_universe, isin_filled. `classify_response`: none_retry, status_403_blocked, status_429_blocked, html_200_blocked, empty_200_fail, xml_200_ok, status_500_retry, status_404_fail, status_302_fail. Mapper: event_row_keys, exchange_from_prefix. `redact_error`: strips_query_string, strips_token_like. `nse_session`: warmup_failure_not_fatal | 22 (observed 2026-11-11) |
| `tests/test_home_events_parsers.py` | one per feed on its fixture (8); fixture_exists_for_every_feed (1, enabled at the last T7 step); empty_feed, malformed_xml_raises, html_200_raises (3); missing_field_dropped_and_counted, bad_date_dropped_and_counted (2); headline_capped_and_title_fallback, corporate_action_company_without_separator_uses_full_title, non_http_link_dropped_and_counted (3); feeds_registry_has_eight_rows, unknown_feed_code_raises_value_error (2) | 19 |
| `tests/test_home_events_run.py` | cooldown_active_skipped_zero_requests; block_on_third_feed_failed_and_cooldown_blocked; success_then_block_twice_never_resets; reset_called_once_after_block_free_run; reset_skipped_when_cooldown_seen_mid_run; status_500_retries_once_then_continues; retry_skipped_when_deadline_too_close; deadline_stops_loop_ok_with_message; deadline_zero_feeds_failed; all_feeds_fail_failed; non_transient_feed_failure_marks_failed; transient_failure_ok_with_message; rejected_counts_in_message; gap_within_bounds_seeded; rows_go_to_post; invalid_rows_mark_failed; bad_config_failed; post_failure_stops_loop_api_error_no_cooldown_change; start_feed_rotates; plus 21 methods added in the build (observed 2026-11-11). Fetch-level, in FetchFeedTests (10): gap_within_bounds, status_500_retries_once_then_continues, retry_skipped_when_deadline_too_close, 403_is_blocked_without_retry, html_200_is_blocked, empty_200_is_fatal, 404_is_fatal_without_retry, parse_error_is_fatal, timeout_then_second_timeout_is_transient, ok_returns_parsed_items. Run-level, in RunCycleTests and RunCycleHardeningTests (11): duplicate_keys_in_one_batch_posted_once, huge_int_param_is_config_error, finite_huge_run_deadline_is_config_error, finite_huge_gap_max_is_config_error, finite_huge_backoff_skips_retry_without_raising, invalid_rows_stop_loop_and_reset_per_spec, post_failure_on_later_feed_keeps_first_feed_counts, all_rows_rejected_gives_none_bounds, deadline_exactly_gap_plus_timeout_starts_feed, deadline_just_below_gap_plus_timeout_starts_no_feed, bool_and_nan_params_are_config_errors | 40 |
| `tests/test_home_events_client.py` | batches_of_500, bearer_header, summed_counts, non_200_raises_without_token | 4 |
| `tests/test_pg_migrate_events.py` (new, no server) | files_events_dir, files_default_is_main, cli_db_argument, cli_default_db_is_main, unknown_db_raises, events_dbname_default_and_override, parts_override_database, url_override_skips_agreement_check, default_dsn_unchanged_for_parts | 9 |
| same file, needs Postgres | apply_events_creates_table (`SkipTest` without Postgres; a skip is not a pass) | 1 |
| `tests/test_home_filings_registration.py` (uses `pgschema`) | registration_rows_exist_after_apply, mode_is_manual (`SkipTest` without Postgres; a skip is not a pass) | 2 |
| `tests/test_collect_sources.py` | source set updated; existing tests still pass; plan_makes_no_call_and_full_shape (new, T4d) | updated, +1 |
| `tests/test_collect_settings_sources.py` | `home_filings_param_keys_accepted_and_unknown_rejected` (T4a) | 1 |
| `server/src/homeEventsBatch.test.ts` (T5a, pure) | valid_row_accepted, bad_enum_rejected_and_counted, bad_date_rejected_and_counted, non_http_url_rejected, headline_too_long_rejected, sql_uses_on_conflict_do_nothing, over_500_rows_rejected | 7 |
| `server/src/homeEventsRoute.test.ts` (T5b, injected deps) | missing_token_401, wrong_role_403, valid_batch_returns_counts, oversize_413 | 4 |
| Manual, one run (T2b) | `docker compose exec -T scanner-postgres psql -U <admin> -d postgres -tAc "SELECT datname FROM pg_database WHERE datname='market_scanner_events'"` returns one row after the first `start.ps1` run and after a second run with no error; `python -m scanner.pg.migrate --db events --status` lists 001 | 1 |

Enum consistency: the three enum lists (Python `FEEDS`, SQL CHECKs, the TypeScript validator) have no test tying them together; T5a's validator and T4e's `FEEDS` are checked against 4.0 by hand at review. The Python-versus-TypeScript enum disagreement this would hide is caught at run time by `invalid_rows_mark_failed` (5.2).

## 9. Ordered tasks, acceptance and must-not-change

**Built status (checked against git, 2026-11-11).** T2a `ebeefe2`; T2b `92395c3`; T3a `f8f0cef`; T3b `4afb40a` (the 2026-11-11 amendment, where the key and mapper take `title` and `description`, is in the T0 commit on `feat/home-filings-t0`); T3c `2bd0a93`; T4a `7c48bec`; T4b `162ea54` (CHANGELOG `3855a67`); T4c `109b5a4` (run_cycle; latest `0d55e24`; merged `3add364`); T5a `b34938e`; T5b `902e90f`; T6 `089a975`; T4e `e3b533f` (merged `d6cea2d`, PR 96); T7a `5173837`, T7b `a50b105`, T7c `6c01220`, T7d `491e7bb`, T7e `12998c6`, T7f `7b5bf5f`, T7g `2b297a0`, polish `9a4a425` (merged `57cf569`, PR 97). Not built: T1, T4d, T5c, T9. Name resolution (4.3) is not built, so parsed items have a null symbol and ISIN and `filter_items` rejects them as `universe`. T0 status (2026-11-11): samples captured in `data/home_samples/<host or container>/<cold or warm>/` (the directory is not committed; all eight feeds are copied into the fixtures, section 4.0); the run reports confirm the fetch URLs and statuses in 4.0. Eight fixtures are in `tests/fixtures/home_events/`: 142 items, 81 old keys, 139 new keys. The fixtures are byte-identical to their samples (cmp, 2026-11-11; 142 items). The T0 acceptance check is met on the sample side (2026-11-11, see the T0 row in §9). All eight feeds carry the real sample files (decision B, 2026-11-11; item 11 below). The name-based filter (§4.3) is design only.

**Open after the T0 review (not fixed in this commit).** (1) The headline 500-character cap and the title fallback are not in `to_event_row` (parser side; T4e or T7). Until they are added, a headline over 500 characters makes the server reject that row (`MAX_HEADLINE_LENGTH` in `server/src/homeEventsBatch.ts`); the row is counted as `invalid` and the run ends `failed` with `invalid:<n>`. Addressed in T4e (parser side, `_rss_item`). (2) `source_url` is not checked for http or https in Python. `server/src/homeEventsBatch.ts` rejects a non-http(s) URL, so that row is counted as `invalid` and the run ends `failed` with `invalid:<n>`. Addressed in T4e (parser side, `_rss_item`). (3) `at_cap` is not built (T4c follow-up). (4) A naive `published_at` raises an uncaught `ValueError` inside `run_cycle` (T4c). (5) After a post failure, the fetched and new counts can disagree. (6) `redact_error` removes the whole query string of any http(s) URL, so an `access_token=` inside a URL is removed. A bare `access_token=<value>` outside a URL is redacted only when the value is a token-like run of 30 or more characters. URL userinfo (`user:password@host`) is not stripped by any pattern; only a long token-like password is caught, by chance. (7) `filter_items` keeps whitespace in `isin`. (8) The mapper test checks four values only. (9) No fixture is matched by name, and no test reads the fixtures. (10) The NSE three-year backfill source (JSON endpoint) is not approved. (11) Resolved 2026-11-11, option B: all eight fixtures are real samples. The body of commit 534ec55 calls the samples reference data only; that wording is superseded by this item, and the commit is not amended.

Tasks become `plan_add` entries only after approval. Each has an acceptance command. Tool-call limit per task: 25, except T2a, T4d, T5c and T9 at 40. "Its tests" in an acceptance column means the tests named for that task in section 8, run with `unittest -k <name>`. Tasks that edit `scanner/home_events.py` run one at a time in the order T3a, T3b, T3c, T4b, T4c, T4e, T4f, T6, T7 (T3a creates the file). **Must not change in any task:** `scanner/factors.py` (including `matches_orderbook`, `_save_announcements` and the order-win lists; the order-win feed is deferred), the existing `announcements` and `collector_*` DDL, `collect.py` (split S1a owns it), and any migration number the split spec claims.

| Task | Depends on | Does | Acceptance |
|---|---|---|---|
| T0 | none (built. Acceptance met on the sample side 2026-11-11: the Financial_Results fixture is byte-identical to its sample, and the spec 4.0 values and the dedupe key were re-derived independently and match. The parser-output comparison against these values is part of T4e's acceptance. Samples captured, commits 534ec55 and b0ab71e on `feat/home-filings-t0`) | Capture one sample per default-enabled NSE feed into `data/home_samples/<host or container>/<cold or warm>/nse_<Name>.xml`. Write into 4.0: each feed's URL, the tag-to-key table, the date format and timezone, whether an id exists, whether the cookie warm-up is needed, feed depth (items and span), and whether the two `results` feeds list the same filings (4.4). | Section 4.0 has a table row per feed with no "to verify" left, each URL answered with a successful fetch; one fixture hand-checked against its sample |
| T1 | split spec assigns the migration number; `pgschema` | `NNN_home_filings_registration.sql` and its down file (`manual` mode), and `tests/test_home_filings_registration.py` | `.venv/Scripts/python.exe -m unittest tests.test_home_filings_registration -q` runs against Postgres (not skipped); `python -m scanner.pg.migrate --status` lists it |
| T2a | none | `db.py`, `migrate.py`, `pgschema` optional argument, events SQL and down, `POSTGRES_EVENTS_DB` name, `tests/test_pg_migrate_events.py`. Must not change: `pgschema.create` default and `migrate.apply()` with no arguments | `.venv/Scripts/python.exe -m unittest tests.test_pg_migrate_events tests.test_pg_dsn tests.test_collect_sources -q` |
| T2b | T2a | `start.ps1` create and migrate stages, image rebuild note, `env.template` (`POSTGRES_EVENTS_DB`) | the manual check in section 8 |
| T3a | none | creates `scanner/home_events.py` with `redact_error`; adds public `nse_session()` and the header dict in `factors_postgres.py`. Must not change: `_nse_session` behaviour | `.venv/Scripts/python.exe -m unittest tests.test_home_events_pure -q` (its `redact_error` and `nse_session` tests) |
| T3b | T3a | `Feed` (no `FEEDS` yet), `dedupe_key`, `to_event_row`, `ParseResult`, `ParseError` | same module, its dedupe and mapper tests |
| T3c | T3b | `filter_items`, `classify_response`, `FetchResult`, `Cooldown` | same module, its filter and classify tests |
| T4a | none | `_valid_param_keys` for `home_filings` | `.venv/Scripts/python.exe -m unittest tests.test_collect_settings tests.test_collect_settings_sources -q` |
| T4b | T3c | `fetch_feed` with an injected session, `parse_fn` and `clock` | `tests.test_home_events_run` with `-k gap_within_bounds -k status_500_retries -k retry_skipped` |
| T4c | T4b | `run_cycle` with injected `feeds`, `parse_fn`, a fake cooldown and a fake `post` | `.venv/Scripts/python.exe -m unittest tests.test_home_events_run -q` (40 tests) |
| T4d | T4c, T4a, T6; split S1a, S2; the base-URL value (4.6, split S3/S4) | `HomeFilings`, `events_source = True`, `SOURCES` entry, the real `Cooldown` adapter, `post` built from `post_events`, updated `tests/test_collect_sources.py` (including `plan_makes_no_call_and_full_shape`) | `.venv/Scripts/python.exe -m unittest tests.test_collect_sources tests.test_home_events_run -q` |
| T4e | T0, T3b | `FEEDS` with real URLs, first parser (`nse:Financial_Results`), its fixture (real NSE sample) | `.venv/Scripts/python.exe -m unittest tests.test_home_events_parsers -q` (that feed's tests) |
| T4f | T3c, T4e | Name resolution (§4.3): the normalisation rules, `load_index_for_source(conn, 'nse_csv')` and `fill_from_name()` (reads `company_reference` with `source = 'nse_csv'`, as §4.3 describes; the `symbol_sector` query is no longer used for events), and resolution of each parsed item to a symbol and ISIN so `filter_items` can accept it. Ambiguous or unmatched names stay `universe` | Named tests for §4.3 (exact match after normalisation; ambiguous and unmatched rejected as `universe`), fixed by the egm brainstorm before any dispatch; `.venv/Scripts/python.exe -m unittest tests.test_home_events_pure -q` |
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
| Cooldown scope | Per host, shared `source_cooldown` table, one row per host. Webscrape hosts (`nse`, `bse`, `rbi`, other scraped hosts) take the longer class (start 15 minutes, cap 1 hour); API hosts (`upstox`, `fred`) take the shorter class (start 3 minutes, cap 15 minutes). | **Decided 2026-11-11 (user): host-keyed; webscrape longer, API shorter. Supersedes the 2026-11-10 per-exchange row.** |
| Fixtures | All eight feeds' fixtures are real T0 sample files (in the T0 change; seven are synthetic at HEAD b0ab71e). | **Decided 2026-11-10; amended 2026-11-11.** |
| Ingest floor, future-date test | Add a floor (earlier); then deferred with `date_future`. | **Deferred 2026-11-10** (4.3). |
| Cuts | Z2, Z3, Z4, Z5, Z6, Z7, Z12. | **Decided 2026-11-10.** Z7 amended by Q1 (`8-20`). Z12 (order-win feed) deferred by Q2. |
| Q1 to Q4 | Cron `8-20` kept; order-win feed deferred; fundamentals trigger to its own spec; all eight feeds on. | **Answered 2026-11-10** (below). |
| Fundamentals trigger | Filed results with catch-up. | **Decided 2026-11-10.** Design moved to its own spec (4.7). |
| 2026-11-11 (1) | Symbol and ISIN from news content: name resolution against the constituent CSV. | **Answered 2026-11-11.** Coverage conflict (a) accepted by the user 2026-11-11 ("agreed"). |
| 2026-11-11 (2) | `source_url` is the item link. No empty `source_url`. The listing page is not used. | **Answered 2026-11-11** (user: "choose link carried by rss item"). |
| 2026-11-11 (3) | Dedupe key as §4.2 (approved). The JSON encoding is an accepted byte-level deviation (4.2). | **Approved 2026-11-11** ("okay"); the deviation was checked and accepted ("if it need fix, fix it, else consider this as acceptable"). |
| 2026-11-11 (4) | RPT dot variant: dot to colon before parsing. | **Decided 2026-11-11** (orchestrator decision). |
| 2026-11-11 (5) | Headline: squashed description, 500-character cap, title fallback. | **Decided 2026-11-11** (orchestrator decision). |
| 2026-11-11 (6) | First run: three years, monthly windows, yearly batches. NSE backfill source open (5.6). | **Answered 2026-11-11.** Conflict (b) answered (5.6): about one year of RSS accepted; three-year history for NSE, BSE, RBI and Fed. |
| 2026-11-11 (7) | 20 items: `at_cap` flag, not a cap. | **Decided 2026-11-11** (orchestrator decision). Design only; not built. |
| 2026-11-11 (8) | BSE route: direct `AnnSubCategoryGetData/w`; no `stock-news` import. | **Deferred** (Z2). |
| 2026-11-12 | BSE matching is ISIN-first (accepted). BSE scrip codes do not match NSE symbols, so they are not used. BSE as a source: approved 2026-11-12. BSE build deferred (Z2). | **Decided** for the NSE name-first rule. BSE rule: **accepted**. BSE source: **approved 2026-11-12**. |

**Answered 2026-11-10:**
- **Q1.** Cron stays `*/5 8-20 * * 1-5`.
- **Q2.** The order-win feed is deferred to the split spec's freshness work; no T8.
- **Q3.** The fundamentals trigger moves to its own spec; no T10.
- **Q4.** All eight feeds, including `Related_Party_Trans` and `Shareholding_Pattern`, are on by default (not off as proposed).

**Answered 2026-11-10 (review 3 questions):** D8/D9 stay as decided. The ingest floor and the future-date test are deferred (4.3). The cooldown mid-run re-read, the 30 s request retry, the start-feed rotation, the per-feed deadline accounting, and keeping 4.3a, 4.4 and 4.7 in this spec: all kept. A 403 on one feed stays `blocked` (5.2). Open: whether to poll the two quarterly feeds (`Related_Party_Trans`, `Shareholding_Pattern`) less often than every 5 minutes (explained to you; default is to keep every 5 minutes).

Still open, not blocking a task here: cooldown cap values (split spec S2 still says 2 h, overview 7.3 says 1 h for other hosts; decision A2 sets 15 minutes for API hosts and 1 hour for other hosts; S2 owns the update); overview edits (14 feeds to 8, the 7.3 off-hours polling and 7.4 "stored counts" lines, 5.1 BSE); Z3's later migration and market-cap source; the Upstox holidays endpoint and token; `REVOKE CONNECT` on the events database; events database backup schedule. Resolved 2026-11-11 and no longer open: the cooldown scope (host-keyed `source_cooldown`, sections 2 and 10) and the ingest token path (4.6).

## 11. Next steps

1. Answered 2026-11-11: decisions (1) to (8) in §10. The D8/D9 cost and four smaller simplifications from the revision reply are not recorded in this spec.
2. Update the stale parent docs (`home-events-filings.md`, overview 5.1, 7.3, 7.4, 8.1, 8.2, and the split-docs index).
3. Design approved 2026-11-11 (confirmed by the user). `plan_add` tasks follow from this approved revision.
4. The NSE samples for T0 are captured (§9). The T0 acceptance check is met on the sample side (2026-11-11, see the T0 row in §9); the parser-output comparison is part of T4e's acceptance. Owned by the split-spec session: the S1a, S3, S4, S5a and citation items in section 2, and migration numbers.
