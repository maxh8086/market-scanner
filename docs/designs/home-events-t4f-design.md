# Home-events T4f: company key, index membership and llm-client

Status: REVISED 2026-11-12 after Goldfish review 2 (docs/designs/home-events-t4f-goldfish-review-2.md). Group A (A1-A4) and group B (B1-B8) approved by the user on 2026-11-13. The design as a whole was approved by the user on 2026-11-13. The chat decisions in sections 5.1 and 5.2 were confirmed by the user on 2026-11-13. No task has been dispatched.

Approval groups. Group A (matching and index membership, tasks MT1 to MT6, section 7) can be approved first. Group B (llm-client, tasks LC0 to LC7) was approved on 2026-11-13, after the decisions B1 to B8 in section 5.2 were answered. Group B tasks never start before LC0.

Review trail: 42 entries in review 2 are answered in section 0. The old blockers BL-1 to BL-5 are in section 0 as well. Paths: blocker file docs/designs/home-events-t4f-blocker-recommendations.md; review file docs/designs/home-events-t4f-goldfish-review-2.md; spec docs/designs/home-events-filings-spec.md; handoff docs/designs/company-reference-handoff.md.

---

## 0. Review 2 resolutions

| Entry | Topic | Resolution | Status |
|---|---|---|---|
| B-01 | llm-client auth and network | llm-client joins a separate network "llm" with scanner, ui and llm-client only. llm-client publishes no ports. POST /v1/chat needs a bearer token from a file mounted into scanner and llm-client only. llm-client reads provider rows and keys from ui's internal endpoint with its own service token; ui allows only llm_client and only key names llm_key_<provider_id>, where provider_id matches ^[a-z][a-z0-9_]{0,40}$ (so the name fits M-02). GET /healthz returns no URL, key or provider data. | Task LC2; Recommendation, needs approval (B 2) |
| B-02 | Request contract | The scanner sends provider_id, model, route, messages, json_schema, max_tokens and options only. llm-client reads class, origin and approved flag from the provider row, and the key from the key record. A keyed class is openai_compat or anthropic_native. ollama is unkeyed. If the provider origin differs from the key record origin, the call is refused with origin_mismatch. AI_PROVIDER_URL is removed from the request path. | Resolved in text; Task LC2 |
| B-03 | Key entry | Decided by user in BL-3: key entry in the UI, masked, encrypted. Write route defined in Task LC3: POST /api/llm/keys. It needs header X-Market-Scanner-UI and an Origin equal to the configured UI origin. No plaintext after save. PUT /secrets stays 410. Residual risk: a container on the shared network can send both the header and the Origin. | Decided by user (2026-11-12); Open, user only (B 3) for the residual risk |
| B-04 | Provider store | Migration 054 (Task LC1) creates llm_provider and ai_setting, seeds four presets inline (openai, anthropic, openrouter, ollama), and grants access to the roles LC0 confirms. config/llm_providers.json does not exist in the repo, so there is nothing to delete; O17 is superseded. | Task LC1; Recommendation, needs approval (B 1) |
| B-05 | Native Anthropic route | anthropic_native is a class in D9 and section 4.5. Request and response mapping, endpoints and adapter files are in Task LC4. Route setting AI_PROVIDER_ROUTE picks native or compat for the anthropic provider (section 4.6). The exact structured-output field name and the anthropic-version value are confirmed from the live docs as a gate before LC4 is built. | Resolved in text; gate in Task LC4 |
| B-06 | Upgrade seed and stop | Migration 054 inserts active model = Qwen3.5 Q6_K tag with ON CONFLICT DO NOTHING, so an existing saved model is never overwritten. A stopped run (no model saved) is written as runs status failed with note model_not_set, through the record-run script with --fail and --reason (Task LC5). The banner reads the saved setting. scanner/llm.py default is changed to the same tag in Task LC6. Section 6 cites the BL-4 approval. | Decided by user (BL-4, 2026-11-12) for the default; mechanism Task LC1 and LC5 |
| B-07 | Section 3 call-site citations | Corrected in section 3: llm.health is called from root conclude.py line 105, not scanner/conclude.py; enrich.py takes --llm-url and reads no environment value; scanner/extractcheck.py makes no LLM call and is removed from the task list. | Resolved in text |
| B-08 | O5 parser row count | O5 now says what the code does: equity_list_rows drops rows with a blank symbol, ISIN or name, and keeps the first row per (symbol, ISIN). That dedupe is load-bearing because the table has no conflict clause. The 2,635 figure is not re-proved. Drop counts per rule are recorded by Task MT3 from an offline run on a user-supplied EQUITY_L.csv (the file is not in the repo). | Resolved in text; counts open until MT3 runs |
| B-09 | load_index_for_source not in production | Section 3 says load_index_for_source is intended for the event lookup and is not called in production until filings task T9. D3, section 4.1 and MT2 say MT2 changes no run-time result until T9. | Resolved in text |
| M-01 | Freshness pointer, approved flag, AAD | Pointer = llm_provider.key_version. ui writes it on each key save and increments it. The key AAD is unchanged; it already covers table, name, owner and key version. llm-client refuses a key whose version is not the pointer (key_stale_version). Approved flag = llm_provider.approved (not in the key record, because ollama has no key record; this differs from blocker line 120). BL-1 test names are copied from the blocker file into LC2. | Resolved in text; deviation needs approval (B 5) |
| M-02 | key_ref naming and delete | provider_id matches ^[a-z][a-z0-9_]{0,40}$ (no hyphens, no uppercase, no dots). A key name is llm_key_ plus the provider_id, for example llm_key_openai (at most 49 characters, which fits ^[a-z][a-z0-9_]{1,63}$). The ui allowlist uses the same rule: llm_key_[a-z][a-z0-9_]{0,40}, full match. Keys are never deleted (no DELETE grant). A key is replaced by a new version. The UI never returns a key value. | Resolved in text |
| M-03 | Settings homes | The database is the only runtime store for the active provider, model and route (ai_setting rows). Environment names are kept only for LOCAL_LLM_URL. The names AI_PROVIDER_NAME, AI_MODEL_NAME and AI_PROVIDER_ROUTE are keys in ai_setting, not environment variables. | Resolved in text (follows O12, O14, O16); env removal part of B 5 approval scope |
| M-04 | Files carrying old names | Task LC6 lists every file: scanner/llm.py, root conclude.py, scanner/conclude.py, enrich.py (flag only), bench_extract.py, bench_models.py, start.ps1, README.md, docker-compose.yml, env.template, and the model default lines. Old names LLM_URL and CONCLUDE_URL are removed in one commit with no aliases. | Task LC6; Recommendation (no aliases), needs approval (B 1 scope) |
| M-05 | Two Anthropic routes | Both routes are kept (O9). The native route is built first (Task LC4). The compat route (same origin, /v1/ path, openai_compat adapter) is added after the native test passes. Primary and secondary labels are removed; AI_PROVIDER_ROUTE picks the route (O11). The wording on unsupported fields reads: "most unsupported fields are ignored; some return an error", citing the canonical Anthropic OpenAI-SDK page named in the blocker file. | Decided by user (O9, O11); order is a recommendation, needs approval (B 8) |
| M-06 | Migration numbers | 054 = llm provider store (LC1). 055 = llm_calls provider columns (LC5). BSE takes no number now. 049 to 052 stay with the filings slices as listed in the split spec; this design claims none of them. Task MT6 records the claims in docs/designs/collector-split-slices.md (the file exists). | Recommendation, needs approval (B 1) |
| M-07 | BSE status | O2 says: BSE source approved 2026-11-12; build deferred (spec Z2); no migration reserved. The BSE rule is quoted once in section 4.2. | Resolved in text |
| M-08 | Index download rules | Task MT1 gives each index a list of candidate URLs (primary and fallback host, up to three filename variants). A response must parse as CSV with a header row; an HTML page with status 200 is refused and the next candidate is tried. Pacing between requests is ported. Each attempt records its status code and host, never the query string. Tests named in MT1. | Task MT1 |
| M-09 | Failure policy for six constituent indices plus NIFTY TOTAL MARKET | Recommendation: each index refreshes on its own. A failed index keeps its last good rows. The master refresh (nse_csv and upstox_master) still commits. The failure is written to the run message and the job exit status. Today one failed index stops the whole refresh (section 3). | Recommendation, needs approval (A 1) |
| M-10 | Existing reader | Membership reads through scanner/constituents.load_constituents, which reads index_constituents through cr.load_index_constituents. No new reader. Transform: each index_constituents row becomes one constituent_membership row, with as_of set to the load date of those rows. A zero-row index raises. The rule that the membership file deletes nothing is kept. The CSV reader stays as an operator rollback, selected by a function argument, not an environment value. | Task MT4; Resolved in text |
| M-11 | Index name casing | The six names in scripts/fetch_index_constituents.py are title case ("Nifty 50" and so on), not uppercase. Only NIFTY TOTAL MARKET is uppercase today (company_reference_job.py and constituents.py). Uppercase (the choice in A 2) means changing the six names in one new module, scanner/index_sources.py (created in MT1, commit c713a65), and in the three readers constituent_membership.py, relative_strength.py and index_candles.py. A test checks that each name loads back with non-zero rows. | Task MT1 and MT4; Recommendation, needs approval (A 2) |
| M-12 | Conflict rules | Section 4.3 gives rules R1 to R3 and names their tests in MT2. | Task MT2; Resolved in text |
| M-13 | One row per ISIN | Decided by user (O3 answer, 2026-11-12): one row per ISIN, using the EQ row. A BE or BZ row is kept only when its ISIN has no EQ row. Task MT3 adds this to equity_list_rows with tests for both file orders. | Decided by user; Task MT3 |
| M-14 | normalise_name steps | D1 and section 4.2 list every step of normalise_name in the order it runs at scanner/company_reference.py lines 26-31. | Resolved in text |
| M-15 | Task table | Section 7 has a row for every task (MT1 to MT6 and LC0 to LC7). Each row names files, dependency, test names, must-not-change list, acceptance command, runtime check (where one exists) and tool-call limit. The old T1 to T7 labels are retired because they reuse spec labels. | Resolved in text |
| M-16 | Call records | The scanner writes call records through metrics.record_call, with RUN_ID set. Migration 055 adds provider_id, route and base_host (host only, no path or query) to llm_calls. The stage CHECK is unchanged. A run that starts with RUN_ID unset logs a warning. Test: one cloud call writes exactly one record. | Task LC5; Recommendation, needs approval (B 1) |
| M-17 | strict_check | The request carries the JSON schema. llm-client checks every required property of that schema. A null value counts as missing. The error is strict_check_missing_field:<name>. Only the field name is logged, never the reply text. | Task LC4; Resolved in text |
| M-18 | healthz and probes | healthz returns: active provider id, class, route, base host, model set yes or no, key resolved yes or no (keyed classes only), secrets API reachable yes or no, time of last successful call. The scanner health() probes healthz only. The model-list and test endpoints are served by ui (see M-22) with the same request contract as section 4.5. | Task LC3 and LC5; Resolved in text |
| M-19 | Duplicate request shapes | The payload and response builders for ollama and openai_compat move out of scanner/llm.py into llm-client adapters. The scanner keeps only its OpenAI-shaped request to llm-client. Tests that pin payloads move with the builders (Task LC4). | Task LC4; Resolved in text |
| M-20 | Scope | Recommendation: keep llm-client in this file, with two approval groups (A and B). The alternative is a separate design file with its own review. The user chooses (B 7). | Open, user only (B 7) |
| M-21 | Provider scope | Four presets: openai (openai_compat), anthropic (anthropic_native, with the compat route as a setting), openrouter (openai_compat), ollama (ollama). Other providers are added by the user by URL and class; the model is typed unless a list endpoint is verified. Verified list endpoints: Anthropic GET /v1/models (cursor-paged: limit up to 1000, after_id, has_more); OpenRouter GET /api/v1/models (limit and offset); Ollama /api/tags (already used by the current health probe) (the endpoint list is not written in the repo; the user confirmed the wording on 2026-11-13). Unverified, and blocking for any provider that uses them: OpenAI paging, Gemini auth header, Together host, anthropic-version value. Gemini, Groq, Mistral and Together are not presets in this design. | Resolved in text; unverified items are gates in LC3 and LC4 |
| M-22 | API framework and the data path | Fastify is not used. The settings and model-picker routes are a FastAPI router in new file ui/app/llm_settings.py with prefix /api/llm, included from ui/app/main.py (include_router lines 43-44). Data path: browser to ui to llm-client to provider. The browser never calls llm-client or a provider. | Task LC3; Resolved in text |
| M-23 | Superseded rules | Section 2 marks D9 (revised), D10 (superseded), D11 (superseded), each with a pointer to its replacement. | Resolved in text |
| M-24 | Terms | Section 9 is a glossary. Every term named in the review is defined there with its store or file. | Resolved in text |
| M-25 | Benchmarks | Task LC6: a benchmark uses the active provider only (O8). bench_extract.py --url and --api are refused with an error; --model is kept. bench_models.py keeps its direct vLLM path as an offline tool outside llm-client, labelled as such. | Task LC6; vLLM path needs approval (B 6) |
| M-26 | Cutover, rollback, errors | No route switch. Gate: healthz passes (Task LC2) before LC6 is merged. Rollback: revert the LC6 commit and stop the llm-client service. Error codes are listed in section 4.5. One redaction function removes keys, Authorization headers and query strings, and truncates provider bodies to 200 characters. | Task LC2, LC6; Resolved in text |
| M-27 | Loader role | Task MT5: the admin step has the exact GRANT statements taken from the SQL the refresh runs (copied from step 1). The grants for index_constituents already exist in migration 048; the grants for company_reference do not exist in any migration (section 3). env.template gets POSTGRES_LOADER_USER and POSTGRES_LOADER_PASSWORD_FILE with comments and no values. A read-only script (scripts/check_loader_grants.py) checks has_table_privilege for INSERT, DELETE and SELECT on company_reference and index_constituents. The compose mount of the loader password file is PROPOSED, NOT APPLIED, until A 3 is answered. | Task MT5; Recommendation, needs approval (A 3) |
| m-01 | Key moves when URL changes | Changing a provider origin marks its key stale, so llm-client refuses calls until the user names the new host and re-saves the key. The key does not move on its own. | Open, user only (B 4) |
| m-02 | Spec line 556 names a missing function | Confirmed: load_events_name_index (filings spec line 556) does not exist in the code. Task MT6 changes the spec line to load_index_for_source and fill_from_name. | Task MT6 |
| m-03 | Quotes of user answers | Section 5 quotes each answer with its date, as the blocker file gives it. | Resolved in text |
| m-04 | Migration 047 header comment | Decided: db/migrations/047_company_reference.sql is not edited. Its text stays byte-identical to the applied version (commit 1fe66a3), because migrate.py refuses an applied file whose sha256 changed. Line 2 still says "NSE Nifty Total Market constituents list"; this design is the record that the source is EQUITY_L.csv. Any comment change to 047 needs a new migration, and none is planned. | Resolved; no task |
| m-05 | Blocker references without a path | Section 0 gives the file path for each BL label. | Resolved in text |
| m-06 | Numbering and stale headings | D14 and O10 are withdrawn with a note (the numbers stay empty). O9 points to O11 and O11 is answered. The line-number reference is removed. Section 5 is split into settled points (5.1) and decisions needed (5.2). | Resolved in text |

Old blockers. BL-1: resolved in design by LC2 and LC3 (origin binding and freshness pointer), with a residual on the write route (B 3). BL-2: resolved, Option B, tests named in LC6. BL-3: decided by user, UI entry with guardrails; residual in B 3. BL-4: default decided by user; mechanism in LC1 and LC5. BL-5: resolved; NSE name-first and BSE ISIN-first (section 4.2).

---

## 1. What this design covers

Home events (filings and news from NSE feeds) carry a company name and no symbol or ISIN. The scanner must attach a symbol and ISIN to each event, or reject it. This design covers:

1. How the company master table (`company_reference`) is built and which source wins.
2. How an event name is matched to the master, and what happens when it does not match.
3. How index membership is loaded from the database (`constituent_membership`).
4. llm-client, the only route for every LLM call from the scanner. Reason: provider API keys must not reach the scanner process.

It does not cover the wiring of the events runner (`run_cycle` with the name lookup, and a production caller). That is filings task T9 in the spec.

---

## 2. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Name normalisation: the steps of normalise_name at scanner/company_reference.py lines 26-31, in order (section 4.2, step 1), with no code change. | Decided (Q1, Decision 1) |
| D2 | NSE CSV and Upstox master are loaded into the database first: EQUITY_L.csv into nse_csv and the Upstox master into upstox_master. | Decided (Decision 2) |
| D3 | Events are matched by company name against the master, using nse_csv only. Exactly one (symbol, ISIN) pair is a match. Zero or several pairs are rejected. Nothing is guessed. | Decided (Decisions 5, 14) |
| D4 | Unmatched events are rejected (31 of the 142 sample rows, 23 distinct names). No source is added for them. | Decided (Q3, Decisions 3, 14) |
| D5 | The LLM fallback for event matching is dropped for now. It may return only if a master source covers these names. | Decided (Decision 14) |
| D6 | NSE wins on source conflicts. Implemented by MT2. | Decided by user (2026-11-12, "nse"; user's chat answer 2026-11-12; not written in the spec or blocker file; wording confirmed by the user 2026-11-13; see section 5.1) |
| D7 | The six indices are loaded into index_constituents by the monthly job, and constituent_membership is read from the database. The CSV reader is kept as an operator rollback. | Decided (Decision 4, "yes") |
| D8 | Every LLM call from the scanner goes through llm-client. The scanner never connects to Ollama, OpenRouter, Anthropic or ChatGPT directly. | Decided (Decision 10) |
| D9 | llm-client classes: ollama, openai_compat, anthropic_native. Revised: anthropic_native added by BL-2 (Option B) and O9. Key entry is set by BL-3 (section 4.5). docs/designs/secrets-and-roles.md decision 9 has not been amended yet (blocker BL-3 says "NOT EDITED"); the user must amend it. | Decided (Decision 11, revised by BL-2 and BL-3) |
| D10 | Superseded. Provider settings are rows in the database (llm_provider, ai_setting), not a config block. See 4.6. | Superseded by 4.6 (O17) |
| D11 | Superseded. One active provider, chosen by ai_setting key AI_PROVIDER_NAME. This replaces the planned LLM_PROVIDER name, which does not appear in the code today. No call site picks a provider. | Superseded by 4.6 (O12) |
| D12 | Migration numbers: 049 to 052 stay with the filings slices (listed in the split spec; no file yet). 053 is fund_daily (file exists). 054 is the llm provider store (LC1). 055 is llm_calls provider columns (LC5). BSE takes no number. | Recommendation, needs approval (B 1) |
| D13 | Monthly refresh: the loader role's password is in a secret file; POSTGRES_LOADER_PASSWORD_FILE names it (Task MT5). Next refresh due 2026-12-12. The compose mount needs A 3. | Decided (Q5); mount needs A 3 |
| D14 | Withdrawn. The number stays empty. | Withdrawn |
| D15 | Order: MT1 six indices; MT2 NSE precedence; MT3 EQ row rule; MT4 membership read; MT5 loader grants; MT6 documents; then group B: LC0 to LC7. | Decided (Q2; user's chat answer 2026-11-12; not written in the repo; wording confirmed by the user 2026-11-13) |
| D16 | Upstox-only rows that share a symbol or an ISIN (no NSE row for that key) | Keep the current behaviour: both colliding rows are left out of the universe and recorded as a symbol: or isin: conflict. Matches HEAD. | Decided (user's chat answer 2026-11-13) |

---

## 3. Facts

Verified 2026-11-12 by Grep and targeted Read in this revision. Re-check at approval. Where the code differs from the review 2 wording, the code is written here and the difference is listed.

**Name key and matching (scanner/company_reference.py)**

- normalise_name (lines 26-31) runs these steps in order: uppercase the whole name; replace "&" with " AND "; replace each of . , ' ( ) - with a space (regex `[.,'()\-]`, line 22); replace the whole word LIMITED or LTD with LTD (regex `\b(LIMITED|LTD)\b`, line 23); collapse runs of spaces and trim the ends.
- Source names: SOURCE_CSV = "nse_csv" (line 18), SOURCE_MASTER = "upstox_master" (line 19). EQUITY_LIST_URL is at line 70.
- equity_list_rows skips rows with a blank symbol or ISIN, keeps one row per ISIN, and prefers an EQ row over BE/BZ rows whatever the file order (implemented in MT3 by _equity_list_select). A repeated (symbol, ISIN) keeps its first row.
- master_rows is at line 89.
- build_index (lines 128-163): a symbol with two ISINs, or an ISIN with two symbols, is recorded as a conflict and left out of the universe. A name that maps to two pairs is recorded as a conflict and left out of by_name. NSE precedence is not implemented (MT2).
- fill_from_name (line 166): fills symbol and ISIN only when the name resolves to exactly one pair. An item whose own ISIN disagrees with the resolved one stays unresolved.
- load_index_for_source (line 199): read only, reads company_reference WHERE source = the given source. It has no production caller. The only callers are tests (tests/test_company_reference.py, lines 199, 208, 218). The only mention of load_index_for_source in scanner/home_events.py is the docstring at line 151.
- EmptySourceError is a RuntimeError subclass (line 214). refresh is at line 218.

**Writes and grants**

- company_reference: DELETE at line 107 and INSERT at line 108 (used by refresh). The docstring at lines 222-223 says the loader role needs DELETE and INSERT on company_reference.
- index_constituents: DELETE at line 246 (_DELETE_INDEX), INSERT at lines 247-251 (_INSERT_INDEX), SELECT at lines 252-255 (_SELECT_INDEX). replace_index_constituents (lines 284-297) refuses an empty list with EmptySourceError.
- load_index_constituents (line 300) raises RuntimeError when the index has no rows (per its docstring, line 303).
- Migration 047 (db/migrations/047_company_reference.sql) grants SELECT on company_reference and company_reference_by_isin to market_scanner_app (lines 46-47). Lines 44-45 say the loader role is created outside the migration. No migration grants the loader INSERT or DELETE on company_reference.
- Migration 048 (db/migrations/048_index_constituents.sql) grants SELECT on index_constituents to market_scanner_app (line 24) and SELECT, INSERT, DELETE on index_constituents to market_scanner_loader (line 25). So the index grants already exist. The company_reference grants for the loader are the gap MT5 must close.

**Monthly job (scanner/company_reference_job.py)**

- The module docstring (lines 1-14) says the job stores EQUITY_L.csv, the Upstox master and each index in SCAN_INDEXES, in one transaction, and that the run path never calls this module.
- SCAN_INDEXES (lines 36-41) holds one entry: "NIFTY TOTAL MARKET", with a primary URL on nsearchives.nseindia.com and a fallback URL on www.niftyindices.com (both point at ind_niftytotalmarket_list.csv).
- fetch_csv_bytes (line 44), fetch_master_bytes (line 54).
- fetch_index_bytes (lines 61-74): raises at line 65 (index not in SCAN_INDEXES) and line 74 (every source failed). It accepts any 200 response (lines 69-71) and does not check that the body is CSV.
- fetch_all_indexes (lines 77-79) has no raise of its own. A failed fetch_index_bytes call propagates. So one failed index stops the whole refresh today. The review wording "raise points about 74, 79" is corrected here to lines 65 and 74.
- parse_index_bytes (line 87), constituent_rows in company_reference.py.
- run_refresh (lines 92-122): fetches and parses everything first. A missing index raises RuntimeError (line 111). An empty index raises cr.EmptySourceError (line 115). Both sources and all indexes are written in one transaction (line 118).
- LOADER_USER_DEFAULT = "market_scanner_loader" (line 125). POSTGRES_LOADER_PASSWORD_FILE is read at lines 134-140 and is required. POSTGRES_LOADER_USER is read at line 150 with the default above.
- POSTGRES_LOADER_PASSWORD_FILE and POSTGRES_LOADER_USER do not appear in env.template, docker-compose.yml or start.ps1. In Python they appear in the reader scanner/company_reference_job.py (lines 13-14, 130, 134-140, 150), in a docstring at scanner/collect/sources.py (line 619), in tests/test_collect_company_reference.py (lines 67, 74) and in tests/test_company_reference.py (lines 456-498).

**Index fetch script (scripts/fetch_index_constituents.py)**

- PRIMARY_BASE (line 19) is https://nsearchives.nseindia.com/content/indices/. FALLBACK_BASE (line 20) is https://www.niftyindices.com/IndexConstituent/. PAUSE_SECONDS = 2.0 (line 22). MAX_VARIANTS = 3 (line 23).
- The index names are uppercase keys in INDEX_SOURCES in scanner/index_sources.py (M-11, approved 2026-11-13). Six constituent indices plus NIFTY TOTAL MARKET; each has its filename variants.
- _valid (lines 56-60) refuses a body that starts with "<" and a header without "Symbol" and "ISIN". _get (lines 63-79) is paced and returns None on HTTP or network errors.
- fetch_one (lines 82-93) tries the primary host with up to MAX_VARIANTS filenames, then the fallback host with variants[0] only (line 85).
- The review wording "fetch_index_bytes in fetch_index_constituents.py" is corrected: the fetch script has _valid and _get. fetch_index_bytes is in company_reference_job.py (see above). The fetch script already refuses HTML; the job does not.

**Constituent membership and readers**

- constituent_membership.py: SLUG_TO_INDEX (lines 30-37) maps six slugs to title-case names. UPSERT_SQL (lines 39-43) is an upsert on (index_name, isin, as_of). parse_csv (lines 50-73) requires the headers Symbol and ISIN Code and raises BadCsv on a repeated ISIN or zero rows. The file reads nifty_*.csv (line 81). executemany is at line 107 in one transaction. The module docstring (lines 8-9) says nothing is deleted. That is the retention rule in place.
- constituents.py: DEFAULT_INDEX = "NIFTY TOTAL MARKET" (line 13). load_constituents (lines 34-50) reads the override CSV when given; otherwise it reads the database through cr.load_index_constituents (line 49).
- relative_strength.py: BANK_INDEX = "Nifty Bank" (line 40). TIER_INDEXES (lines 43-49) lists five title-case names.
- index_candles.py: INDEX_KEYS (lines 36-87) uses mixed case. Examples: "Nifty 50" (line 37), "NIFTY SMLCAP 250" (line 42), "Nifty Microcap 250" (line 45). It has no entry for NIFTY TOTAL MARKET (it has "NIFTY 750 TOTAL MKT" at line 54).
- Name casing conclusion: the readers use title case today, not uppercase as review 2 says. The A 2 choice changes them.

**Events (scanner/home_events.py)**

- filter_items at line 145. count_isin_conflicts at line 171. run_cycle at line 408, with the by_name parameter at line 421; its docstring is at lines 429-430. The fill_from_name call is at line 495. The isin_conflicts counter is at lines 451, 494. The run message at line 547 is "rejected parse=<n> universe=<n> isin_conflict=<n>".
- The events feeds carry no symbol and no ISIN: _rss_item (line 614) sets both to None (lines 649-650).
- Only tests call run_cycle (tests/test_home_events_run.py; the blocker file cites lines 362, 374, 533). No production caller exists (comment at lines 694-696).
- scanner/extractcheck.py imports only llm.AGREE_TOLERANCE_PCT and makes no LLM call.

**LLM call sites (corrected)**

- scanner/llm.py: default model is "qwen3:8b" (line 65). SCHEMAS at line 253. OPENAI_MAX_TOKENS = 500 at line 297, used for extract. health() at lines 401-423. The extract requests.post is at line 461.
- scanner/conclude.py: DEFAULT_MODEL is already "hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K" (line 41). Its conclude() default max_tokens is 1400 (line 517). requests.post at line 558. metrics.record_call at lines 567 and 589. It does not call llm.health.
- root conclude.py: the --url default reads CONCLUDE_URL, or localhost:11434 (lines 84-85); the --model default is conclude.DEFAULT_MODEL (line 86); llm.health is called at line 105; the message at line 108 names CONCLUDE_URL.
- enrich.py: --llm-url is at line 1069 with default llm.LLMConfig.base_url. The usage text at lines 402-403 names LLM_URL. No environment read was found in the file.
- bench_extract.py: --url (line 34, default 127.0.0.1:8001), --api (line 35), --model (line 36), health (line 44).
- bench_models.py: PORT = 8003 (line 40); the container publish is 127.0.0.1:8003 (line 64); health probe at line 93; base URL at line 116.
- start.ps1: LLM_URL is read at line 64 (default host.docker.internal:11434), described at lines 28-29 and 63. $ModelName is the Qwen3.5 Q6_K tag (line 62) and is passed as --llm-model at line 328.
- README.md: LLM_URL at lines 119 (default text says host.docker.internal:8000, which differs from start.ps1) and 136.
- docker-compose.yml: CONCLUDE_URL at line 112. The header comment at line 9 names LLM_URL and CONCLUDE_URL. The networks block (lines 225-227) is the project's own default network named market-scanner. It is not a shared network, and the file says no external network is needed.
- env.template: POSTGRES_USER=scanner at line 10; LLM_URL at line 47 (127.0.0.1:11434); CONCLUDE_URL at line 48.
- LLM_PROVIDER, AI_PROVIDER_* and LOCAL_LLM_URL do not appear in env.template, docker-compose.yml, start.ps1 or the Python files. They are planned names.

**Secrets and UI (ui/app and scanner)**

- ui/app/api.py: line 11 imports APIRouter, HTTPException and Query from fastapi. PUT /secrets is at line 527 and returns 410 (line 536; docstring line 532).
- ui/app/internal_secrets.py: DEFAULT_TOKEN_FILE = "/run/app-keys/collector_token" (line 32). SERVICE_ALLOWED (line 33) allows only collector, and only upstox_analytics_token. The service is fixed to collector at lines 60-61.
- scanner/secret_crypto.py exists (Glob). record_run.py exists at the repo root (not in scripts/).
- metrics.record_call is at line 77. It reads RUN_ID at line 95 and returns with no write at line 97 when RUN_ID is unset.

**Migrations on disk**

- Present: 001_core, 010, 011 (two files share the number 011: 011_left_range_bucket and 011_fetch_metadata_pull_log), 012, 013, 014, 020 to 027, 039 to 048, 053_fund_daily. EGM.md is also in the folder. Several numbers in 001 to 048 have no file (for example 002 to 009, 015 to 019, 028 to 038). The review wording "001 to 048" is corrected to this list.
- Absent: 049 to 052 and 054. 055 is not reserved in any file.
- A down/ folder exists with 045, 046, 047 and 048 down files.
- 001_core.sql: runs.status CHECK at line 11 allows running, complete, failed and partial. runs.notes text column is at line 22. llm_calls.stage CHECK at line 68 allows extract and conclude.
- 045_app_secret.sql: the name rule is on the column called name (line 7: CHECK name ~ '^[a-z][a-z0-9_]{1,63}$'). The review wording "key_name" is corrected to name. Grants at line 20: SELECT, INSERT, UPDATE to market_scanner_app. Line 19 says there is no DELETE grant.
- 047_company_reference.sql: line 2 describes nse_csv as "NSE Nifty Total Market constituents list". That text is stale (the source is EQUITY_L.csv). The file is not edited, because its checksum is recorded as applied (m-04).

**Filings spec (docs/designs/home-events-filings-spec.md)**

- "751" appears in spec section 4.3 at lines 355, 364, 375 and 377. Lines 375 and 377 are historical measurements against the 751-company universe and stay 751. Lines 355 and 364 are the scanner universe label; MT6 may change them to the operator-confirmed count (752) once the database check is recorded.
- load_events_name_index at line 556 does not exist in code (m-02).
- The BSE source returned HTTP 403 from the author's environment (spec line 89). The BSE rule is in the decision log at line 669 and in section 4.3 at line 97.

**Counts and samples**

- The count facts below come from the spec and the blocker file. The operator checked the database on 2026-11-13: nse_csv 2633 rows, upstox_master 2757 rows, index_constituents NIFTY TOTAL MARKET 752 rows. EQUITY_L.csv is not in the repo, so its raw row count stays unconfirmed:
  - nse_csv 2,633 rows, confirmed in the database on 2026-11-13. This is the stored count after the equity_list_rows dedupe, not the raw CSV row count.
  - index_constituents for NIFTY TOTAL MARKET: 752 rows, confirmed in the database on 2026-11-13.
  - upstox_master: 2757 rows, confirmed in the database on 2026-11-13.
  - EQUITY_L.csv has about 2,635 data rows (unconfirmed, file not in repo). The two rows in the file and not in the database are ESFL (INE0ITO01014) and SUVID-RE (INE018420013) (still unconfirmed).
- The 142-item sample figures (111 matched, 0 ambiguous, 31 not concluded, 23 distinct names) are recorded in the blocker file (line 61) and the filings spec (line 375). The spec also records an earlier measurement of the same 142 items against the 751 universe, taken on 2026-11-11: 50 matched, 0 ambiguous, 92 unmatched (spec line 375). The 111 and 31 figures are the 2026-11-12 measurement against the full NSE list. The 2026-11-11 figure must not be mixed with the 2026-11-12 figure. They were not re-run here. The statement that article-text search rescued none is from the blocker file (line 314). The spec reports 0 ambiguous in every measurement (spec line 375). The only "1 ambiguous" is blocker line 71, a different measurement (762 name-first matches against nse_csv); it is not the 142-item sample.

---

## 4. Design

### 4.1 Master table

- company_reference holds rows from nse_csv (EQUITY_L.csv, after MT3 one row per ISIN) and upstox_master.
- Refresh replaces both sources in one transaction, as today. A source that parses to zero rows refuses the refresh (EmptySourceError).
- Event lookup reads nse_csv only (D3).
- Admin step for the loader role (MT5): the exact GRANT statements are listed by MT5, copied from the SQL the refresh runs. The role is created outside migrations (as 047 says). Index grants already exist (048). The check script in MT5 verifies the grants before the first refresh.

### 4.2 Event matching (rule A, name-first for NSE)

1. Normalise the event's company name with normalise_name. The steps, in order (company_reference.py lines 28-31):
   - (i) uppercase the whole name;
   - (ii) replace "&" with " AND ";
   - (iii) replace each of . , ' ( ) - with a space;
   - (iv) replace the whole word LIMITED or LTD with LTD;
   - (v) collapse runs of spaces and trim the ends.
2. Look up the normalised name in the nse_csv index (fill_from_name).
3. One (symbol, ISIN) pair: fill symbol and ISIN.
4. Zero or several pairs: leave the symbol empty; filter_items rejects the item as "universe".
5. A name match whose ISIN disagrees with the item's ISIN is rejected and counted as isin_conflict (count_isin_conflicts, home_events.py line 171). Run message format: rejected parse=<n> universe=<n> isin_conflict=<n>.

Measured results are in section 3 (reported figures, not re-run here).

BSE (ISIN-first): the source was approved 2026-11-12; the build is deferred (spec Z2). The BSE rules, copied from the blocker file (lines 79-84), are:

- (a) BSE item with an ISIN: resolve by ISIN against the BSE master, then cross-check nse_csv.
- (b) Scrip code: map through the BSE master to an ISIN, never to an NSE symbol.
- (c) Name only: accept only one exact name key whose pair is unique. Ambiguous means refuse.
- (d) Any disagreement means refuse.

Standing rule (user, 2026-11-12): whenever a brainstorm starts for the deferred BSE implementation, its reference points from this entry are recorded in that brainstorm's design file first.

Quoted answers are in section 5.1.

### 4.3 Source precedence (MT2)

- R1. ISIN in both sources: the NSE symbol and name are used. Upstox is used only where NSE has no row for that ISIN.
- R2. Symbol level: an NSE symbol and its ISIN are never removed by an Upstox row, even when the same symbol maps to a different ISIN in Upstox.
- R3. Name level: name lookup reads nse_csv only (D3), so an Upstox row cannot make an NSE name ambiguous.
- Tests (MT2) (planned names; not yet written): test_upstox_row_with_same_isin_loses_to_nse; test_upstox_only_collision_keeps_nse_row; test_symbol_shared_across_sources_keeps_nse_pair; test_name_lookup_ignores_upstox.
- No run-time result changes until filings T9 (B-09).

### 4.4 Index membership (MT1, MT4)

- Six constituent indices plus NIFTY TOTAL MARKET, which is kept in the index source list (seven names in INDEX_SOURCES; six go into constituent_membership). The names and file variants are planned to be copied from scripts/fetch_index_constituents.py into scanner/index_sources.py (created in MT1, commit c713a65). That single module (created in MT1) is planned to serve the job, the fetch script and the readers. The names are title case today; the A 2 choice (uppercase, M-11) would change them. The six exact names are listed here after MT1 is written.
- Each index has a list of candidate URLs: primary and fallback host, with up to three filename variants.
- A response is accepted only if it parses as CSV with a header row. An HTML page with status 200 is refused and the next candidate is tried. The fetch script already does this (_valid). The job's fetch_index_bytes does not yet; MT1 adds the check there.
- Requests are paced as the fetch script does now (2.0 seconds).
- Each attempt records status code and host (no query string).
- Failure policy (recommendation, A 1): each index refreshes on its own. A failed index keeps its last good rows. The master refresh still commits. The failure is in the run message and the job exit status. Today a failed index stops the whole refresh (section 3).
- Membership read (MT4): today constituent_membership.py reads data/constituents/nifty_*.csv through load_all and parse_csv (lines 76-90 and 118 of that file). The planned MT4 change routes the read through scanner/constituents.load_constituents (planned; not yet changed), which reads index_constituents through cr.load_index_constituents. Transform: one index_constituents row to one constituent_membership row, as_of = the load date of those rows. A zero-row index raises. Retention: the membership file deletes nothing, and that is kept. The CSV reader is kept as operator rollback, selected by a function argument. Existing tests are in tests/test_constituent_membership.py and tests/test_constituents_cache.py.
- Universe count: index_constituents holds 752 rows for NIFTY TOTAL MARKET (confirmed in the database on 2026-11-13; see section 3). The spec's §4.3 labels at lines 355 and 364 (751) may change to the confirmed count when MT6 runs. The measurement lines 375 and 377 stay 751 as historical.

### 4.5 llm-client (Group B; tasks LC0 to LC7)

- Role: the only route for scanner LLM calls (D8). Provider keys never reach the scanner process.
- Network: a new compose network named llm joins scanner, ui and llm-client. llm-client has no ports entry in compose. Outbound internet access stays on, because llm-client must reach the providers.
- Auth in: POST /v1/chat needs a bearer token read from a file (for example under /run/app-keys, the existing pattern), mounted into scanner and llm-client only. Missing or wrong token: 401 with token_missing or token_invalid. This differs from the blocker wording ("that only scanner holds", blocker line 119), because llm-client must check the token (B 2).
- Auth out: llm-client calls ui's internal endpoint with its own service token file, mounted into llm-client and ui only. ui allows llm_client and only key names matching llm_key_ (the internal endpoint and its allowlist are in ui/app/internal_secrets.py; the current allowlist is collector only and must be extended in LC2).
- Request body: provider_id, model, route ("native" or "compat"), messages, json_schema (optional), max_tokens, options (for example num_ctx for ollama).
- options: accepted and reserved; not forwarded until the ollama adapter lands (LC4).
- llm-client reads the provider row (class, origin, approved) and the key (for keyed classes) from ui. It checks, in order: approved (else provider_not_approved); key present (else key_missing); key version equals the provider's key_version pointer (else key_stale_version); provider origin equals the key record origin (else origin_mismatch); route allowed for the class (else route_mismatch).
- Classes:
  - ollama (unkeyed; origin is the provider row origin, for example http://host.docker.internal:11434).
  - openai_compat (keyed; POST {scheme}://{host}[:port]/v1/chat/completions with Bearer key; the origin path is ignored (decision a)).
  - anthropic_native (keyed; POST {origin}/v1/messages with x-api-key and anthropic-version headers). The anthropic compat route uses the openai_compat adapter with origin https://api.anthropic.com/v1/ (the path is ignored, so the URL is https://api.anthropic.com/v1/chat/completions), the same key.
- Keys: entered in the UI, masked, stored encrypted in app_secret (BL-3; the blocker says the UI is bound to 127.0.0.1, uses a custom request header plus an Origin check, echoes no plaintext after save, and keeps the master key on the ui service only). key_ref = llm_key_<provider_id>. The AAD is unchanged. The freshness pointer is llm_provider.key_version, incremented by ui on each save (BL-1 Option 2).
- Approved flag: llm_provider.approved, default false except ollama (O7: hosted providers are approved by the user one at a time). The blocker (line 120) puts the flag inside the encrypted record; this design puts it on the row (B 5).
- Error codes: token_missing [401], token_invalid [401], origin_mismatch [409], origin_not_https [409; keyed classes only], provider_not_approved [409], key_missing [409], key_stale_version [409], route_mismatch [409], model_not_set [422], provider_rejected:<status> [502], provider_timeout [504], provider_unreachable [502], secrets_unavailable [503], strict_check_missing_field:<name> [502] (contract for LC0 to LC7; adapter_not_built, 501, is interim and lives only in the LC row until the ollama and anthropic_native adapters land). One redaction function (LC2) removes keys, Authorization headers and query strings, and truncates provider bodies to 200 characters before any log or response.
- Request validation (422): provider_id pattern, non-blank model (model_not_set), non-empty messages, max_tokens 1 to 32768, route native or compat, no extra fields.
- Healthz: see M-18 in section 0.
- Model list: from the list endpoint in the provider row (see 4.6). The compat route has no list: the user types the model name; the UI runs one test call before saving it (O15).
- Schema check: strict_check (M-17).
- max_tokens: 500 for extract (scanner/llm.py line 297; blocker line 33) and 1400 for conclude (scanner/conclude.py line 517). The scanner passes the value in each request.
- Gate for LC4: confirm the native structured-output field name and the anthropic-version value from the live Anthropic docs; record the source URL and date in this design before LC4 starts. The compat route sends json_schema with strict true (decision c), as response_format {"type":"json_schema","json_schema":{"name":"...","schema":...,"strict":true}}. The blocker says the compat page accepts only json_schema with strict: true (its statement, not re-checked here).

### 4.6 Provider and model settings (database only)

- llm_provider: one row per provider (provider_id, display name, class, origin, list endpoint, approved, key_ref, key_version, updated_at). Four presets seeded by migration 054 (planned; migration 054 does not exist yet): openai, anthropic, openrouter, ollama.
- ai_setting: keys AI_PROVIDER_NAME (active provider id; default ollama), AI_MODEL_NAME (default: the Qwen3.5 Q6_K tag hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K; BL-4), AI_PROVIDER_ROUTE (default native; used only by anthropic).
- The scanner reads AI_PROVIDER_NAME, AI_MODEL_NAME and AI_PROVIDER_ROUTE at the start of each run and sends provider_id, model and route with every request.
- Clearing AI_MODEL_NAME: the run stops before any call; a runs row is written with status failed and note model_not_set (LC5); the banner shows a notice with a link to the model settings page.
- Settings page: all values are dropdowns or fields in the UI, saved to the database (O12, O16). Users add a provider by URL, a class and a name; the approved flag is off until the user turns it on.
- Only LOCAL_LLM_URL is an environment value (scanner to llm-client).
- No config/llm_providers.json. The presets are seed rows in migration 054 (O17 superseded).

---

## 5. Decisions

### 5.1 Settled (each answer with its date)

Quotes are from the blocker file (docs/designs/home-events-t4f-blocker-recommendations.md), which records the answers under the heading "Decisions recorded 2026-11-12" (line 18). Answers that are not in the blocker file are not written in the repo. They were marked for confirmation, and the user confirmed their wording on 2026-11-13.

- O1 Source precedence: "yes" (2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13). Implemented by MT2.
- O2 BSE: blocker line 65 (heading): "BL-5 BSE mapping: rule accepted 2026-11-12 (ISIN-first); BSE source approved 2026-11-12". Blocker line 90: "BSE source approved by the user 2026-11-12". Spec line 81: "Deferred (Z2). No BSE code is built or adopted now." The blocker says the user gave no separate wording for the BSE rule (line 322 and line 343), so the rule text in 4.2 is the record. The BSE matching rule was accepted: "BSE matching rule accepted 2026-11-12: ISIN-first, using rules (a) to (d) ..." (blocker line 58).
- O3 Duplicate ISIN rows: option A, one row per ISIN, using the EQ row (2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13). Implemented by MT3.
- O4 Name conflicts (FUTURE ENTERPRISES LTD, GACM TECHNOLOGIES LTD, JAIN IRRIGATION SYSTEMS LTD): each pair is two securities; both kept; name lookup returns nothing for these names by design (Rule A).
- O5 Count gaps: equity_list_rows (scanner/company_reference.py lines 73-86) drops rows with a blank symbol, ISIN or name, and keeps the first row per (symbol, ISIN) pair. That dedupe is load-bearing because the table has no conflict clause. The 2,635 row figure is unconfirmed, because EQUITY_L.csv is not in the repo. The handoff (docs/designs/company-reference-handoff.md, line 21) and tests/test_collect_company_reference.py record 2,633 nse_csv rows, not 2,635. The 2-row gap (ESFL, SUVID-RE) is a snapshot difference (unconfirmed; section 3); the next refresh picks it up. Drop counts from MT3 remain to be recorded.
- O6 Names: LOCAL_LLM_URL replaces LLM_URL and CONCLUDE_URL (2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13). AI_PROVIDER_URL is retired as an environment value; the base URL is the provider's origin in llm_provider. This name change needs approval (B 5). AI_PROVIDER_URL does not appear in the code today.
- O7 Hosted providers approved: "there is no sensitive information, information is already available on public domain" (2026-11-12; the quoted text is not in the repo; wording confirmed by the user 2026-11-13). Each provider still needs its own approved flag.
- O8 Benchmarks use the active provider only (option A, 2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13). LC6 implements; see M-25.
- O9 Both Anthropic routes needed (2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13; blocker BL-2 cites it as "O9 ('both routes are needed')").
- O11 Route chosen by a setting: AI_PROVIDER_ROUTE. No automatic switch (2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13).
- O12 Names agreed: AI_PROVIDER_NAME, AI_MODEL_NAME, AI_PROVIDER_ROUTE (2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13).
- O13 Pick the model from the provider's list (2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13).
- O14 Picked model saved in the database and used by every run ("yes", 2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13).
- O15 Compat route: the user types the model name and a test call runs before saving (decided by Claude; user delegated the call, 2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13).
- O16 Qwen3.5 Q6_K tag is the default for fresh and upgraded installs. Blocker BL-4 (line 53): "Confirmed by the user 2026-11-12: this is the default for fresh installs and for upgraded installs." Upgraded installs with run history keep running with no prompt.
- O17 Presets: four seed rows in migration 054; no JSON file (decided by Claude; user delegated, "make the app as user-friendly as possible", 2026-11-12, not written in the repo; wording confirmed by the user 2026-11-13). Supersedes the earlier file plan.
- BL-1 (blocker line 22, "Decisions recorded 2026-11-12" heading): "BL-1: accepted, Option 2". The freshness pointer covers rollback (blocker line 25).
- BL-2 (line 27): "BL-2: accepted, Option B".
- BL-3 (line 35): "BL-3: user decision, overrides Option A". Line 37: "Keys are entered in the UI, shown masked, and stored encrypted in the database. This overrides Option A's command-line-only key entry."
- BL-4 (line 50): "BL-4: user recommendation, confirmed 2026-11-12". Line 53: "Confirmed by the user 2026-11-12: this is the default for fresh installs and for upgraded installs."
- BL-5 (line 56): "BL-5: name-first for NSE RSS items (accepted)". Line 58: "BSE matching rule accepted 2026-11-12: ISIN-first, using rules (a) to (d) ...". The blocker does not record the one-word answer "nse". "nse" is not written in the spec or blocker file; it is the user's chat answer on 2026-11-12; wording confirmed by the user 2026-11-13.
- D6 NSE wins ("nse" is not written in the spec or blocker file; it is the user's chat answer on 2026-11-12; wording confirmed by the user 2026-11-13).

### 5.2 Decisions needed before approval (each with my recommendation)

Group A:

- A 1-A 4: Approved by the user 2026-11-13 as group A, including the failure policy (M-09), index-name casing, the compose loader mount, and the 2026-12-12 refresh requirement (A3).

- A 1. M-09 failure policy: independent per index; a failed index keeps its last good rows; master refresh still commits. Recommended.
- A 2. Index name casing: uppercase (matches the existing NIFTY TOTAL MARKET row name) or title case as the fetch script uses today. Recommended: uppercase. This changes the six names and three readers (M-11).
- A 3. Compose mount of the loader password file into scanner (MT5). Needed before the 2026-12-12 refresh. Recommended: apply in MT5. It stays unapplied until you answer.
- A 4. Approve group A (MT1 to MT6) as a whole.

Group B:

- B 1-B 8: Approved by the user 2026-11-13 as group B, covering migration numbers, the bearer token file, the residual risk of the key-write route, the rule for moving keys (m-01), the approved flag and retiring AI_PROVIDER_URL, the bench_models vLLM path, llm-client scope, and the Anthropic native route coming before the compatibility route.

- B 1. Migration numbers: 054 llm provider store; 055 llm_calls columns; BSE takes no number; 049 (S2), 050 (S5a), 051 (S8) and 052 (filings T1) are assigned in docs/progress/collector-split-spec-requests.md (row S2, line 19; user accepted the proposal 2026-11-12). 051 (S8, filings cron) and 052 (filings T1) are filings numbers; 049 (S2) and 050 (S5a) are collector-split numbers. No migration file for 049 to 052 exists yet. Recommended.
- B 2. Bearer token file mounted into scanner and llm-client. This differs from the blocker wording ("that only scanner holds", blocker line 119), because llm-client must check it. Recommended.
- B 3. Key write route residual risk: a container on the shared network can send both the custom header and an Origin. Options: accept the header and Origin guardrails (recommended), or allow key entry only from a host command line.
- B 4. m-01: a changed provider origin marks the key stale; the key moves only after the user names the new host. Recommended.
- B 5. approved flag on the provider row (not inside the encrypted key record, as blocker line 120 says); and the O6 name change for AI_PROVIDER_URL. Recommended.
- B 6. bench_models.py keeps its direct vLLM path as an offline tool outside llm-client. Recommended.
- B 7. M-20: keep llm-client in this file with its own approval group (recommended), or split it into a separate design file with its own Goldfish review.
- B 8. Anthropic: native route built first; compat route after native passes. Recommended.

### 5.3 Facts that cannot be settled here

- Count of EQUITY_L.csv rows and the drop counts per rule (needs the file; MT3 step).
- Whether a BE row shares a symbol with its EQ row (MT3).
- OpenAI list paging; anthropic-version value; native structured-output field name (LC4 gate). Gemini header and Together host (not presets; blocking only if added). The list endpoints in M-21 are stated in the spec and were not checked against live docs in this revision.
- The 2-row gap (ESFL, SUVID-RE) at the next refresh (due 2026-12-12).
- The database counts in section 3 (not queried in this revision).

---

## 6. Must not change without a separate approval

- The Ollama models in use and num_ctx. The default tag change in LC6 is approved by BL-4 (2026-11-12) and is the only model change allowed.
- The migration numbers in D12.
- db/events_migrations/ is not used for main-database work.
- The schema of company_reference and index_constituents (no change in group A).
- The events runner wiring (filings T9).
- The CSV reader of constituent_membership as the rollback path.
- The secret AAD scheme: unchanged; the freshness pointer is a column in llm_provider.
- The 410 response of PUT /secrets.

---

## 7. Tasks (not dispatched)

Acceptance command for every task: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`, plus the runtime check where one is stated.

### Group A

| ID | Files | Depends on | Test names (in the test file named) | Must not change | Runtime check | Tool-call limit |
|---|---|---|---|---|---|---|
| MT1 | scanner/index_sources.py (new); scanner/company_reference_job.py (fetch_index_bytes gets the CSV check); scripts/fetch_index_constituents.py (imports index_sources); tests/test_company_reference_job.py (new) | approval A 4 and A 1, A 2 | test_six_index_names_defined_once; test_html_200_is_not_accepted; test_first_filename_404_tries_next_variant; test_failed_index_keeps_last_good_rows; test_master_refresh_commits_when_one_index_fails | NIFTY TOTAL MARKET URLs and its parse; EmptySourceError rule | after approval, one refresh run by the operator: SELECT index_name, COUNT(*) FROM index_constituents GROUP BY index_name shows seven non-zero counts | 30 |
| MT2 | scanner/company_reference.py (build_index); tests/test_company_reference.py; no change to db/migrations/047_company_reference.sql (m-04) | MT1 | test_upstox_row_with_same_isin_loses_to_nse; test_upstox_only_collision_keeps_nse_row; test_symbol_shared_across_sources_keeps_nse_pair; test_name_lookup_ignores_upstox | normalise_name; fill_from_name for single-source names; SQL of 047 | none (no run-time change until T9) | 30 |
| MT3 | scanner/company_reference.py (equity_list_rows; new function equity_list_drop_counts); tests/test_company_reference.py | MT2 | test_eq_row_wins_in_both_file_orders; test_be_only_isin_kept; test_isin_with_eq_and_be_rows_keeps_eq; test_drop_counts_by_rule | the first-row rule for same (symbol, ISIN) pairs within one series | operator runs equity_list_drop_counts on EQUITY_L.csv (path given by the user); the counts are written into section 3 | 30 |
| MT4 | scanner/constituent_membership.py; scanner/relative_strength.py (name strings); scanner/index_candles.py (name strings); tests/test_constituent_membership.py (existing file; new tests added) | MT1 | test_membership_reads_database_rows; test_zero_rows_raises; test_csv_reader_kept_as_rollback; test_each_index_name_round_trips | scanner/constituents.load_constituents signature; the no-delete rule | one membership build for six indices: non-zero rows each | 30 |
| MT5 | env.template (loader variables, comments, no values); scripts/check_loader_grants.py (new, read-only); tests/test_check_loader_grants.py (new); docker-compose.yml loader mount ONLY after A 3 | MT1 (for order) | test_check_loader_grants_reports_missing; test_check_loader_grants_passes_when_granted | no secret values anywhere; no password read by the script except via the existing file variable | run check_loader_grants before the 2026-12-12 refresh | 25 |
| MT6 | docs/designs/home-events-filings-spec.md (§4.3 lines 355 and 364: change "751" to "752" (the count confirmed in the database on 2026-11-13); lines 375 and 377 are historical and stay 751; line 556 and line 630 both name load_events_name_index, which does not exist, so each changes to load_index_for_source and fill_from_name); docs/designs/company-reference-handoff.md (items 4 and 6); docs/designs/collector-split-slices.md (add claims 054 and 055 for group B; the file does not contain them yet; BSE none; the file exists) | MT1 to MT5 | no test; grep checks: no "load_events_name_index" in the spec (lines 556 and 630 changed); "751" at lines 355 and 364 changed to "752" (the count confirmed in the database on 2026-11-13); lines 375 and 377 unchanged | the spec's other sections | grep check only | 15 |

Group A notes:
- MT5 detail: company_reference has no loader grant in any migration (section 3). The admin step must grant INSERT and DELETE on company_reference to the loader role. index_constituents already has them (048 line 25).

### Group B (LC0 first; B 1 to B 8 approved 2026-11-13; no group B task starts until the design is approved as a whole)

| ID | Files | Depends on | Test names | Must not change | Runtime check | Tool-call limit |
|---|---|---|---|---|---|---|
| LC0 | none (gate) | B 1 to B 8 approved 2026-11-13 | none | none | check POSTGRES_USER in docker-compose.yml and which role each service connects as (compose and env.template only; do not read .env) | 10 |
| LC1 | db/migrations/054_llm_provider_store.sql (new); db/migrations/down/054_llm_provider_store.down.sql (new); tests/test_migration_054.py (new) | LC0 | test_054_creates_both_tables; test_054_seeds_four_presets; test_054_active_model_insert_does_not_overwrite; test_054_down_drops_tables | no change to 047 to 053 | apply on the dev database and read back the rows | 30 |
| LC2 | docker/llm-client/Dockerfile (new); llm_client/__init__.py, app.py (POST /v1/chat, GET /healthz), registry.py (ui internal reads with service token), auth.py (bearer check), errors.py (codes), redact.py (one redaction function) (all new); docker-compose.yml (service llm-client; network llm; no ports; healthcheck; scanner and ui join llm; token file mounts); ui/app/internal_secrets.py (allow llm_client, key names llm_key_, provider read); tests (below) | LC1 | see the table below | the Ollama models and num_ctx | docker compose config shows no ports on llm-client and the llm network; GET /healthz returns 200 from the scanner container | 40 |
| LC3 | ui/app/llm_settings.py (new router, prefix /api/llm); ui/app/main.py (include_router lines 43-44) | LC2 | test_key_write_without_header_refused; test_key_write_foreign_origin_refused; test_key_response_has_no_plaintext; test_key_name_rule; test_provider_add_requires_header | PUT /secrets stays 410 | UI test call to the local ollama provider returns a reply (after approval) | 40 |
| LC4 | llm_client/adapters/ollama.py, openai_compat.py, anthropic_native.py (new); llm_client/schema_check.py (new); tests/test_llm_client_adapters.py (new); pinned payload tests moved from tests/test_llm_payload.py (the file exists) | LC3 and the gate: live Anthropic docs checked (source and date recorded in this design) | test_anthropic_system_is_top_level; test_anthropic_max_tokens_from_request; test_anthropic_no_temperature; test_strict_check_missing_field_named; test_null_counts_as_missing; test_ollama_payload_matches_pinned_output; test_openai_compat_payload_matches_pinned_output; test_anthropic_compat_route_uses_openai_adapter | none in scanner/llm.py yet (LC6) | none | 40 |
| LC5 | llm_client/app.py (healthz fields); scanner/llm.py (health probes /healthz only); scanner/metrics.py (warning when RUN_ID is unset at run start); db/migrations/055_llm_calls_provider.sql (new) and down file; record_run.py at the repo root (add --fail and --reason); tests/test_llm_healthz.py, tests/test_run_fail.py (new) | LC4 | test_healthz_fields; test_health_probes_healthz_only; test_one_cloud_call_writes_one_record; test_run_fail_writes_failed_row_with_reason; test_run_start_warns_when_run_id_unset | stage CHECK unchanged | a run with the model cleared stops and shows model_not_set | 35 |
| LC6 | scanner/llm.py (public signatures kept; payload builders removed; posts to LOCAL_LLM_URL; default model constant = Qwen tag, line 65 changed from qwen3:8b); scanner/conclude.py (line 558 to client); root conclude.py (lines 84-86, 105, 108); enrich.py (help text at lines 402-403 only; the flag is already --llm-url); bench_extract.py (refuse --url and --api; keep --model); bench_models.py (vLLM path kept, labelled offline); start.ps1 (LLM_URL to LOCAL_LLM_URL; model lines 62 and 328 removed); README.md (119, 136); docker-compose.yml (line 112); env.template (47-48); tests/test_llm.py (lines 72-75: BL-2 edits), tests/test_conclude.py (line 207: BL-2 edit), tests/test_conclude_request.py | LC5; LC2 healthz passed | test_bench_refuses_url_override; test_default_model_is_qwen_tag; the BL-2 edits | scanner/llm.py public function signatures; scanner/extractcheck.py (no change) | scanner run with LOCAL_LLM_URL set: one call through llm-client, one record | 50 |
| LC7 | docs/designs/concall-vl-extraction-plan.md (line 14: route through llm-client; the file exists); design file §5 status updates | LC6 | none; grep checks | other sections of the plan | grep check | 15 |

Rollback for LC6: revert the LC6 commit and stop the llm-client service. Old names are removed in the same commit (no aliases).

LC2 test files. These are proposed test file names. None exists yet. Test function names are chosen during implementation. The six proposed files, with what each checks:
- tests/test_llm_client_auth.py: a call without a bearer token gets 401; a wrong token gets 401; /healthz returns no URLs or keys.
- tests/test_llm_client_origin.py: a request with a base_url field is rejected; the key is not sent when the record origin differs (no outbound call, no key in logs or responses); the origin check ignores the path.
- tests/test_llm_client_registry.py: an unapproved provider is refused; a missing key record fails with a message that names the provider.
- tests/test_llm_client_freshness.py (new file): a stale record version is refused after a rollback.
- tests/test_service_secrets.py: extend the 403 test to the llm-client token; the llm-client token cannot read the Upstox token.
- tests/test_compose_llm_network.py: parses docker-compose.yml and checks that llm-client has no ports key and joins only the llm network.

LC1 table details:
- llm_provider(provider_id text primary key; display_name text; class text not null check in ('ollama','openai_compat','anthropic_native'); origin text not null; list_endpoint text; approved boolean not null default false; key_ref text; key_version integer not null default 0; updated_at timestamptz).
- ai_setting(key text primary key; value text; updated_at timestamptz).
- Seed presets with ON CONFLICT DO NOTHING: ollama approved true; openai, anthropic, openrouter approved false.
- ai_setting seed (all ON CONFLICT DO NOTHING): AI_PROVIDER_NAME = ollama; AI_MODEL_NAME = hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K; AI_PROVIDER_ROUTE = native.
- Grants to the roles LC0 confirms. The blocker (BL-3, Option A) says the app login owns the tables; the grants to the loader role are a separate step, if LC0 needs them.

LC3 routes:
- GET /api/llm/providers (no key value; masked last four characters only).
- POST /api/llm/providers (add by name, class, origin, list endpoint).
- PUT /api/llm/settings (AI_PROVIDER_NAME, AI_MODEL_NAME, AI_PROVIDER_ROUTE, approved flags).
- POST /api/llm/keys (header X-Market-Scanner-UI required; Origin equal to the configured UI origin; saves the key with AAD; increments key_version; key marked stale if origin changed).
- GET /api/llm/providers/{id}/models (list via llm-client; paged per provider).
- POST /api/llm/providers/{id}/test (one test call).

---

## 8. Process

- Approval: group A (A 1 to A 4) and group B (B 1 to B 8) are separate gates. No task is dispatched before its gate.
- Each task: one Haiku subagent does the edit; Sonnet or Opus runs the acceptance command and the runtime check; the task is done only with a git SHA or a finished task ID.
- A second Goldfish review is recommended on this revision before dispatch (the user decides).
- Commits carry the human author only, with no co-author trailer.

---

## 9. Glossary

- company_reference: table; rows from nse_csv and upstox_master (migration 047; SELECT for the app, write for the loader role).
- nse_csv and upstox_master: sources in company_reference (source CHECK at 047 line 11).
- EQUITY_L.csv: NSE equity list file, all series; not in the repo; URL at company_reference.py line 70.
- ISIN: international security id (a 12-character code per security).
- NSE, BSE, Upstox: exchanges and feed; BSE is deferred (Z2).
- universe: the event is rejected when no symbol is found ("universe" in the run message).
- normalise_name: name normalising function, company_reference.py lines 26-31.
- index_constituents: table of index members (migration 048).
- constituent_membership: table written from index membership (migration 021); read by relative strength.
- llm-client: the container for all LLM calls.
- llm_provider and ai_setting: migration 054 tables (planned).
- app_secret: encrypted key store (migration 045; column name is the key name).
- key_version: freshness pointer, llm_provider (planned column).
- RUN_ID: environment value that links call records to a run (scanner/metrics.py line 95).
- Q6_K and GGUF: quantised model file format and level.
- strict_check: planned (M-17). It does not exist in scanner/llm.py or scanner/conclude.py yet; the blocker says the strict fix is still needed (blocker line 168).
- num_ctx: context window size for ollama.
- spec Z2: the BSE deferred item in the filings spec (line 26).
- filings T9: the events runner wiring task in the filings spec.
- the 142-item sample: the test sample of event names (measured 2026-11-11 against the 751 universe; the full NSE list measurement of 2026-11-12 gives 111 matched and 31 unmatched; reported figures in section 3).
