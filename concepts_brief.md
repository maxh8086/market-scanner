# T4f: Name-based symbol and ISIN resolution for home_events NSE RSS items

* **Author:** Claude (Haiku 5.5), drafted for Vaibhav Pavtekar
* **Date:** 2026-11-12
* **Status:** Revised after the six-lens review. **Not ready to register tasks.** No code dispatched.

## Overview

NSE RSS items carry a company name in the title but no symbol and no ISIN. The parser (`scanner/home_events.py`, `_rss_item`) sets both to `None`, and `filter_items` (lines 143 to 166) then rejects every item as `universe`. T4f adds the step that turns the company name into a symbol and ISIN, then checks the result against the store's universe.

The parser already sets `item["company"]`. For `Corporate_action` it is the text before ` - Ex-Date:`. For the other feeds it is the whole squashed title. The parser is not changed.

### Glossary (used in this brief)

* **Universe:** the set of symbols in `symbol_sector` with an ISIN (D3). It is the scope check. Not the same as the `universe` counter or the `filter_items` argument of the same name.
* **Name index:** a dict built from the constituents CSV, mapping normalised company name to `(symbol, isin)`, or `None` when ambiguous.
* **Company:** `item["company"]`. For six of the seven feeds it is the whole title, not a company name. The name "company name" in this brief means this field.

### Verified facts (checked 2026-11-12)

* `load_universe` is named in the `filter_items` docstring (line 149) and spec 4.3. It is defined nowhere in `scanner/`. A different `load_universe` exists in `scripts/pull_upstox_5y.py`, with another meaning.
* `scanner/symbol_sector.py` already reads the constituents CSV. `parse_csv` (lines 52 to 88) validates it, and the upsert (lines 38 to 43) sets `symbol_sector.isin` and `as_of` from the same CSV. So `symbol_sector.isin` is a copy of the CSV, not an independent source.
* `scanner/constituents.py` has `CACHE_PATH = Path("data/...")`, which is cwd-relative. `docker-compose.yml` mounts `./data:/app/data` for an existing collector service (line 131). The `home_filings` service does not exist until T9.
* The working checkout's CSV has 756 lines: a header and 755 rows. `GAMMON` is not in it. The fixture names in the sample are not in the CSV, so the 50 sample matches cannot all come from name spelling.
* Spec 5.1 step 3 sets `deadline_at` and then calls `load_universe()`. `run_cycle` (line 389) takes `universe` as an argument and has no connection.
* **The T4f row does not exist.** Spec section 9 has T0 to T7 and T9. The name is not in any branch or worktree.

## Blockers

**B1. Deadline contract conflict.** The run order (spec 5.1) puts the universe load after the deadline. The brief had `HomeFilings.run` load the universe and pass it to `run_cycle`, which changes the order. `docs/progress/home-events-filings-spec-review4.md` (lines 49 to 51) raised the same conflict. Options:
  * (i) Inject a loader callable into `run_cycle`, so the load happens inside it after `deadline_at` is set. Changes the section 6 signature.
  * (ii) Keep `HomeFilings.run` as the owner of both steps, set the deadline first, then call the load, and pass the deadline in. Changes section 5.1 wording.
  * Recommendation: (ii). It keeps `run_cycle` free of database and file access, which the T4c fake-based tests depend on.

**B2. The main premise is unmeasured.** The brief said whole-title names often are not company names, and that this explains 0 of 3 Financial_Results and 0 of 20 Related_Party_Trans. The fixtures show clean names ("Gammon India Limited", "Shree Ram Proteins Limited", "Ballarpur Industries Limited"). The sample also matches 15 of 82 items across six whole-title feeds (spec 4.3). The likelier cause for the unmatched items is scope: the company is not in the Nifty Total Market list. Before any normalisation rule is added, classify the 92 unmatched sample items into:
  * (a) NSE-listed but outside the CSV;
  * (b) in the CSV under a different spelling;
  * (c) not listed, or delisted.
  Check each candidate symbol against `symbol_sector`. Normalisation is justified only if (b) is large. This is a read-only measurement on the 142-item sample, and it can be done before any build.

  **Measured (2026-11-12, read-only, scratchpad scripts, no repo change).** 142 items parsed; 50 matched the CSV by the settled normalised rule; 92 unmatched.
  * Loose check (also drops THE, COMPANY to CO, PHARMACEUTICALS to PHARMA, PVT): 2 of the 92 match the CSV under a spelling variant. They are "The Great Eastern Shipping Company Limited" (GESHIP, Corporate_action) and "Ajanta Pharma Limited" (AJANTPHARM, Sast_Regulation31). The settled rule rejects both. Adding those words would change a settled decision, so it needs your approval.
  * Class (a), 43 items: the normalised name is an exact name in the Upstox NSE_EQ/EQ master (2,757 rows) but not in the CSV. Name matching against the CSV cannot reach these.
  * Class (b) against the master: 0 by the loose check. The only spelling gap is against the CSV, as shown above.
  * Class (c), 49 items: no exact name in the NSE_EQ/EQ master. Examples: "Gammon India Limited", "Ballarpur Industries Limited", "Gaja Alternative Asset Management Limited". Whether these are delisted, renamed or simply absent from the master is not yet known. Symbol_sector and stock_snapshots were not checked (no DB access attempted).

  Per feed (unmatched, a / c): Corporate_action 23 (17 / 6); Integrated_Filing_Financials 18 (7 / 11); Related_Party_Trans 20 (5 / 15); Sast_Regulation29 17 (7 / 10); Sast_Regulation31 10 (7 / 3); Financial_Results 3 (0 / 3); Shareholding_Pattern 1 (0 / 1). Corporate_Governance 0.

  Reading: the sample does not support normalisation as the main lever. Scope explains the 43 class (a) items. The other 49 are not in the master by name and need the symbol_sector and DB check before they can be called delisted or outside the universe.

**B3. Wrong matches are permanent.** `dedupe_key` excludes symbol and ISIN (spec 4.2). A wrong resolution is stored once, and every refetch hits `ON CONFLICT DO NOTHING`. The API role has no DELETE (spec 5.5). Before T9 switches the feed to `scheduled`: run one feed, review the resolved rows by hand, and write an owner-run correction runbook (`pg_dump` first). This belongs in the T9 gate.

## Majors

* **M1. The ISIN authority rationale is unsupported.** The brief said the store ISIN is the one to trust because ISINs change. But `symbol_sector.isin` is written from the same CSV (verified above). `isin_resolver` writes `isin_history` and `symbol_alias`, not `symbol_sector`. So the store ISIN is a same-source copy and may be stale. Either take the ISIN from `isin_resolver.resolve` or `isin_history`, or drop the rationale and treat the universe check only as a scope gate. Evidence to change the view: a write path from `isin_resolver` to `symbol_sector.isin`, or a comparison of store ISINs with the current Upstox master for symbols that changed ISIN.
* **M2. ISIN precedence is contradictory.** Open Q1 fills ISIN from the universe. Risk 4 says "a resolved item whose parser-set `isin` is kept", but the parser never sets ISIN (spec 4.0 says no feed carries one). Replace that test with: the name path takes the universe ISIN.
* **M3. An empty universe is silent.** If `symbol_sector` is empty, every ISIN is NULL, or the collector role lacks SELECT, every item is rejected as `universe` and `run_cycle` still returns `ok`. Fail the run with a named message (`names:universe_empty`) and test it. `load_universe`'s `WHERE isin IS NOT NULL` drops symbols with no count; report that count.
* **M4. One counter hides three causes.** No match, ambiguous match and out-of-scope all go into `counts["universe"]`. Split them into `name_miss`, `name_ambiguous` and `out_of_scope` in `filter_items`, and keep `universe=` in the run message as their sum.
* **M5. The fixture contradicts the storage rule.** Open Q3 says do not commit the CSV, then commits about 30 real rows. Use synthetic rows instead: invented names, symbols and ISINs that exercise each normalisation rule, plus DUMMY rows and duplicate names. Put them outside `tests/fixtures/home_events/`, which holds real feed samples.
* **M6. The CSV dependency is a single point of failure.** The path is cwd-relative (`constituents.py:13`). Sibling readers (`symbol_sector.py:28`, `isin_resolver.py:31`) are repo-anchored. A missing file fails every feed on every tick. Inject an explicit path from config, name the refresh owner and command, and put the path, mtime, age, row count and hash in the run message.
* **M7. Reinvention.** `symbol_sector.parse_csv` already reads and validates this CSV. It returns no name column, so extend it rather than adding `read_cached_constituents`, which would duplicate it. There is no name normaliser in the repo, so `normalise_name` is new.
* **M8. Alternatives not weighed.** Before choosing the CSV join, weigh:
  * (a) a `company_name` column on `symbol_sector`, filled by the existing loader. Needs one migration; the migration number is contested in spec section 2.
  * (b) `stock_snapshots.company`, the only name column already in the store (`docs/progress/home-events-decisions-needed.md` line 353). Coverage not checked.
  * (c) the Upstox NSE master cached by `isin_resolver`. It has no name field today.
  * (d) the NSE JSON endpoint, which carries symbol and `sm_isin` (spec 5.6). It reverses D1, and its host returned 403 on T0.
  * (e) per-filing link shapes that carry the symbol (`nsearchives .../corporate/<SYMBOL>_...`). This could remove name matching for some feeds. Not verified: `data/home_samples/` is absent from this checkout.
* **M9. Task count and build order.** T4f-1 touches only `constituents.py` and its test file, so the shared-file reason for ordering it first is wrong. Serialise only `home_events.py` edits. T4f-3 can be avoided: a wrapper around `parse_fn` in `HomeFilings` sets `item["symbol"]` to the resolved symbol or `None`, and `filter_items` already counts `None` as `universe`. That leaves the 40 T4c tests untouched. `load_universe` belongs to T4d, which needs it regardless. T4f-5 is T4d wiring. The realistic unit is one pure resolver plus a wrapper.
* **M10. Spec drift.** The amendments the spec needs before build: a T4f row in section 9; the serial `home_events.py` order in section 9; section 2 build order; the section 4.0 ISIN line; section 4.3 ("symbol and ISIN are checked against the universe"); section 5.2 new message tokens (`names:constituents_missing`, `names:stale=<days>`) and the failure status; section 6 signatures for `filter_items`, `run_cycle` and the loader; section 8 test names; the section 6 module table (`constituents.py` is missing).
* **M11. Undefined and overloaded terms.** `resolve_name` has no signature. "names" means a parameter, a message prefix and prose. "universe" means three things (see the glossary). `build_name_index` takes tuples "after `_clean`", but `_clean` returns a DataFrame. The return type and missing-file behaviour of the reader are unspecified.
* **M12. Normalisation rules.** Stripping `-` merges TATAMOTORS and TATA MOTORS under one reading; replacing it with a space gives another key. Specify whole-token matching for LIMITED and LTD (so UNLIMITED is unchanged). Address PVT. Measure same-name collisions across the full CSV, not only the sample. Dedupe on `(symbol, isin)` before the ambiguity check, because the Series column can give one company two rows. Drop any rule the B2 measurement does not justify.
* **M13. Database and grant.** The brief does not say which database. `symbol_sector` is in the main DB; the events DB is separate (spec 4.5, D8, D9). The only grant found is to `market_scanner_app` (migration 026). The collector role is unverified. The fake-cursor test cannot catch a wrong connection or a missing privilege, so add one Postgres-backed check. Rename the new loader (for example `load_store_universe`) to avoid the clash with `scripts/pull_upstox_5y.py`.
* **M14. Acceptance gaps.** The acceptance commands run whole modules and can pass with no new tests. Name the four Risk 4 cases and give expected counts. Add an end-to-end regression on the 142-item set: expected 50 matched, 0 ambiguous (spec 4.3 line 289), split by the M4 classes. The limit of 40 on T4f-5 is not in the spec for this task.
* **M15. Copy divergence.** The 755 and 754 checkout copies differ in real rows. "The container copy is the authority" is asserted, and the container mount is still open (M6). Diff the two copies on the sample names. Do not treat them as interchangeable in acceptance tests.
* **M16. Observability.** "Visible" is unsourced: spec 5.2 says the dashboard does not parse the message, so the stale note is visible only to someone who reads it. Name a reader, or say it is not surfaced. Add a DEBUG log of the normalised key and chosen symbol (not the raw title) for wrong-match diagnosis, and keep raw titles so rejected items can be replayed.

## Nits

* The 30-day staleness threshold has no rationale. "Freshness does not matter" conflicts with the stale flag.
* "Settled" references cite no decision ID in spec section 10.
* The `.venv` acceptance path assumes a setup step the brief does not describe.
* Line numbers have no commit reference, and this brief is uncommitted.
* Mark T4f-2 to T4f-4 as not registered until T4d is approved, to avoid dead code.

## Weakest point

The CSV-as-name-source join. B2 is now measured: 43 of 92 unmatched items are listed on NSE but outside the CSV, so the CSV cannot reach them. The store ISIN claim (M1) is still unverified (no DB check yet).

## Evidence that would change the design

1. The B2 classification of the 92 unmatched items. If most are (b), normalisation is the lever. If most are (a), compare the Upstox master, `stock_snapshots.company` and the NSE JSON endpoint.
2. Per-feed containment: the share of whole-title items whose title contains a normalised constituent name.
3. A documented write path from `isin_resolver` to `symbol_sector.isin`, or an `as_of` comparison showing drift.
4. Counts of same-normalised-name and same-`(symbol, isin)` collisions across the full CSV.
5. The collector DB role's SELECT grant on `symbol_sector`.
6. `stock_snapshots.company` coverage of the universe.
7. Per-filing link shapes in the T0 samples (not available in this checkout).

## Revised decisions to approve

| # | Question | Revised recommendation |
|---|---|---|
| 1 | Name source and join | Undecided. Choose between the CSV name index (current), a `company_name` column (M8a), or `stock_snapshots.company` (M8b). Run B2 first. |
| 2 | Network and failure mode | No network in a run. Missing file fails the run; stale file used with the path and age in the message. Refresh is an owner command outside the run. Owner still to name (M6). |
| 3 | Which copy, `data/` | `data/` stays ignored. Synthetic fixture (M5). Diff the two checkout copies before relying on either (M15). |
| 4 | Signature | Pure `normalise_name`, `build_name_index`, `resolve`. `filter_items` keeps `names=None`, or uses the wrapper in M9. Split counters (M4). |
| 5 | `load_universe` | Keep the name, but in `HomeFilings` (T4d) and renamed to avoid the clash (M13). Fix the deadline order first (B1). |

## Reference tables in the DB (approved 2026-11-12, not applied)

Approved by the user: the `company_reference` table, the `company_reference_by_isin` view, the six lookup indexes, DB-only reads at run time, and the monthly refresh. Still open, and needed before the task breakdown is registered:
* O1. **Decided 2026-11-12: widen to the master.** The resolver's universe is the union of the stored CSV and master rows in `company_reference`, not `symbol_sector` alone. This changes the settled D3 rule ("resolved symbol must be in `symbol_sector`"). Consequences: the 43 class (a) items become resolvable; the universe check queries `company_reference` by (symbol, ISIN); a symbol present in both sources must carry the same ISIN, and a disagreement is counted as `universe` and listed for review.
* O2. Loader role: a separate role with DELETE for the monthly reload, or a different reload method under the collector role.
* O2. **Decided 2026-11-12: separate loader role.** A new DB role gets INSERT, UPDATE and DELETE on `company_reference` only. The collector role is unchanged (spec 5.5 holds).
* O3. **Decided 2026-11-12: collector job.** The monthly refresh runs inside the existing collector schedule, and its failure alert uses the collector's alert path.

All open decisions are now answered. Task registration and the call-site migration have not started.

Requirement (user, 2026-11-12): the DB holds a table or view with reference rows from both the Upstox NSE master and the NSE CSV, keyed by ISIN, symbol and company name. Lookups must work on each combination of those keys.

**Profile of the two sources (read-only, 2026-11-12):**
* CSV: 755 rows, no blank ISIN, no duplicate symbol, no duplicate (symbol, ISIN).
* Master (NSE_EQ/EQ): 2,757 rows, no blank ISIN, no duplicate symbol, no duplicate ISIN.
* ISIN overlap: 743. CSV-only: 12. Master-only: 2,014.
* Precedent: `symbol_sector` (migration 025) already stores CSV ISINs and industries. `isin_history` and `symbol_alias` (migration 012) already store master-derived pairs. The new tables would add a name key that neither has.

**Proposed table `company_reference`** (new migration 047, not yet written):

```sql
CREATE TABLE company_reference (
  source        text NOT NULL CHECK (source IN ('nse_csv', 'upstox_master')),
  symbol        text NOT NULL,            -- upper(btrim(...)), same rule as symbol_sector
  isin          text NOT NULL,            -- upper(btrim(...))
  company_name  text NOT NULL,            -- as published by the source
  name_key      text NOT NULL,            -- computed by the Python normaliser, not in SQL
  series        text,
  as_of         date NOT NULL,
  loaded_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source, symbol, isin)
);
CREATE INDEX company_reference_isin_idx        ON company_reference (isin);
CREATE INDEX company_reference_symbol_idx      ON company_reference (symbol);
CREATE INDEX company_reference_name_key_idx    ON company_reference (name_key);
CREATE INDEX company_reference_symbol_isin_idx ON company_reference (symbol, isin);
CREATE INDEX company_reference_isin_name_idx   ON company_reference (isin, name_key);
CREATE INDEX company_reference_name_symbol_idx ON company_reference (name_key, symbol);
```

* `name_key` is computed by one Python function (the settled normaliser), so SQL never re-implements it. The Python function is the single source of truth.
* One row per (source, symbol, ISIN). The source column keeps the two copies apart, so a later disagreement is visible rather than overwritten.

**Proposed view `company_reference_by_isin`** (joins the two sources on ISIN):

```sql
CREATE VIEW company_reference_by_isin AS
SELECT coalesce(c.isin, m.isin) AS isin,
       c.symbol AS csv_symbol,     c.company_name AS csv_name,    c.name_key AS csv_name_key,
       m.symbol AS master_symbol,  m.company_name AS master_name, m.name_key AS master_name_key,
       (c.symbol = m.symbol)       AS symbol_agrees,
       (c.name_key = m.name_key)   AS name_agrees
FROM (SELECT * FROM company_reference WHERE source = 'nse_csv') c
FULL JOIN (SELECT * FROM company_reference WHERE source = 'upstox_master') m
       ON c.isin = m.isin;
```

**Lookup combinations the table must serve:**

| Lookup | Use | Index |
|---|---|---|
| name_key alone | The only key an RSS item carries. The resolver's name step. Must return one (symbol, ISIN) across both sources after dedupe, else reject as `universe`. | name_key |
| name_key + symbol | Confirm a name hit when the item has a symbol. Not all items do. | name_key_symbol |
| ISIN alone | Fetch name and symbol from either source. Cross-check. | isin |
| ISIN + name_key | Check that a name and an ISIN agree. | isin_name |
| symbol alone | Symbol to ISIN and name, for the universe check and the `symbol_sector` join. | symbol |
| symbol + ISIN | Exact row check, for example the final universe check. | symbol_isin |

**Facts that limit the design (must be decided before the build):**

1. **RSS items carry no ISIN and no symbol.** `_rss_item` sets both to `None` (spec 4.3). The name is the only input. The ISIN and symbol combinations serve cross-checks and the universe check, not the initial match.
2. **The universe check excludes master-only companies.** The settled rule (D3) requires the resolved symbol to be in `symbol_sector`. That table holds CSV rows only. So a name that matches a master-only company (class a, 43 of 92) still fails the universe check, even with this table in place. Widening the universe to the master is a separate decision.
3. **Data use (user rule, 2026-11-12).** No NSE or Upstox data is used directly, except the live feed. All reference data is stored in the DB and reused. Refresh runs once a month. Consequences for the design:
   * The run path reads only the DB. `load_constituents` (CSV download, `data/` cache, 30-day age) and `isin_resolver.try_load_master` (reads `data/upstox_nse_master.json.gz`) must not be read at run time. Both move to a monthly refresh job that writes `company_reference`.
   * Each refresh sets `as_of` and `loaded_at`. A run warns when the newest `as_of` is more than 31 days old. It does not fetch.
   * The `data/` files become an intermediate step inside the refresh job, not a runtime input. They stay git-ignored.
   * The refresh job needs a schedule owner (cron or the collector), a retry, and a rule for a failed month: keep last month's rows, and alert.
   * Restated 2026-11-12 (user, repeated): no symbol or ISIN data from NSE or Upstox is used directly, except the live feed. Every symbol and ISIN used by a run, a scan, or a universe check comes from the stored tables.

   **Existing direct uses that break this rule (found by grep, not yet changed):**
   * `ath_scan.py:143` calls `load_constituents` (CSV download or `data/` cache). `ath_scan.py:167` calls `isin_resolver.try_load_master` (reads `data/upstox_nse_master.json.gz`).
   * `enrich.py:112` calls `load_constituents`.
   * `scanner/collect/sources.py:144, 211, 255` call `load_constituents`. These are collector paths.
   * `scanner/symbol_sector.py:28` reads `data/ind_niftytotalmarket_list.csv` (the cache written by `constituents.py`). It is the source of `symbol_sector`'s ISIN and industry values.
   * `scripts/pull_upstox_5y.py:174, 195, 210` call `load_constituents` and `try_load_master(refresh=True)`, which hits Upstox.
   * `scanner/constituents.py` downloads the CSV from NSE at run time (30-day cache). `scanner/isin_resolver.py` fetches the master at run time.
   * Not symbol or ISIN data, so outside this rule but worth a decision: `scanner/crosscheck.py:89-97` fetches NSE bhavdata directly.
   * `scripts/fetch_index_constituents.py` fetches NSE index lists. It may be the refresh job's source, if it writes to the DB.

   Migrating these is a separate, sizeable change. It needs your go-ahead to start, and it should follow approval of the `company_reference` design.
4. **Refresh and grants.** A full reload per source needs DELETE on `company_reference`. Spec 5.5 says the collector role has no DELETE. Either use a separate loader role, or confirm that a reload can run under the existing role. Grants should follow the pattern of migration 026.

## Draft task breakdown (not registered; depends on the approvals above)

Each task would need a named test list, not a whole-module command (M14). Work on `scanner/home_events.py` is serial.

1. **Measure (read-only):** B2 classification done (see B2). Still open: M12 collision counts across the full CSV, and the symbol_sector / stock_snapshots check for the 49 class (c) items. No code change.
2. **Spec amendments:** the M10 list, including a T4f row in section 9 and the B1 deadline order.
3. **Pure resolver:** normalisation, name index and resolve, with synthetic-row tests and the M4 counters. Files: `scanner/home_events.py`, `tests/test_home_events_pure.py`, `tests/fixtures/home_events_synthetic/` (new).
4. **Loader and guard:** store universe loader and the M3 empty-universe guard, with the M13 Postgres check. Depends on T4d.
5. **Wiring:** the `HomeFilings` wrapper, after T4d. Acceptance: named tests in `tests/test_collect_sources.py` and `tests/test_home_events_run.py`, plus the 142-item end-to-end check.
6. **T9 gate:** B3 manual review and correction runbook.

## Review status

The six lenses and synthesizer ran in parallel. The synthesizer also ran one extra lens, `egm-style`, which was not in the requested six. Its findings are merged above and marked where they came from in the review. Findings were not re-reviewed after the revision.
