# Home-events T4f design: Goldfish review 2

- Design reviewed: `docs/designs/home-events-t4f-design.md` at commit 015dbe0 (not edited).
- Mode: REVIEW
- Date: 2026-11-12
- Totals: 117 findings from six lenses. 116 kept: 92 confirmed and 24 not checked by the verifier (all minor). 1 refuted (readiness IR-22, see appendix). 0 unverifiable. The 116 kept findings are merged into 42 entries: 9 blockers, 27 major and 6 minor. Each finding id appears under exactly one entry.
- Documents: "design" is `docs/designs/home-events-t4f-design.md`. "spec" is `docs/designs/home-events-filings-spec.md`. "blocker file" is `docs/designs/home-events-t4f-blocker-recommendations.md`. Code paths are relative to the Market-Scanner repo root.
- Id note: finding ids are numbered per lens. Lens keys: design = egm-design; codebase = egm-codebase-details; zoom-out = egm-zoom-out (written "zoom-out BL-1" to "zoom-out BL-5" so they are not confused with the old blockers); comprehension = egm-comprehension; readiness = egm-implementation-readiness; structural = egm-structural. Entry ids B-, M- and m- are assigned in this review. "Old BL-1 to BL-5" means the five blocker topics in the blocker file.
- Basis: this review merges the lens findings and verifier verdicts as given. The synthesizer did not reopen the repository files. Where an entry depends on a verifier correction, the entry says so.

## 1. Summary

The design is not ready for approval. Nine blocker entries (45 findings) must be settled first. Four of them concern llm-client and the provider path. llm-client has no service authentication in either direction. The scanner still sends the class, key reference and host on every call, with no rule that ties a key to its origin. The key write route is not designed. The provider store has no table, owner, grants or seed loader. The other five blockers are: the native Anthropic route has no mapping, endpoints or adapter; an upgraded install stops on its first run because no model is saved, and the stop writes no run status; the §3 call-site inventory contradicts the code in three places; O5 says the parser keeps every row when the parser drops some; and §3 says load_index_for_source is used for the event lookup when no production code calls it.

The 60 major findings (27 entries) are mostly places where the design states a rule, count or status that the code or another file does not support. Examples are the one-row-per-ISIN EQ rule, migration 054 claimed for two pieces of work, BSE recorded as both approved and not approved, the index download and failure rules, and §7, which has no rows for the new work, no test names and no runtime checks. The 11 minor findings (6 entries) are wording, numbering and reference errors.

Status of the old blockers: BL-1 partly resolved; BL-2 open; BL-3 partly resolved; BL-4 partly resolved; BL-5 resolved in substance, with residuals. Details are in the appendix.

One finding was refuted (IR-22). The verifier's note says a narrower point stands: the design names no collector source or cadence for the company reference refresh, and no data-age check exists. That point is not counted here, because the finding was dropped as stated. The owner can reopen it.

## 2. Blockers

### B-01. llm-client has no service authentication in either direction, and it sits on a shared network
- Lenses and ids: design DES-02 (blocker), DES-05 (major); codebase CD-01 (blocker); comprehension C-01 (blocker), C-14 (major); zoom-out BL-1 (blocker); readiness IR-01 (blocker); structural ST-01 (blocker).
- Problem: design:82 puts llm-client on the market-scanner network only. docker-compose.yml:225-227 defines that network as the one shared network for the project, and compose:128 already has another service reaching ui:8080 on it. design:83 lists POST /v1/chat and GET /healthz with no caller token. Any container on the network can therefore ask llm-client to make a call that uses a stored key. The read side has the same gap. design:87 says llm-client reads keys from the UI by key_ref. The only internal read endpoint, ui/app/internal_secrets.py, allows one service (collector) and one key name (SERVICE_ALLOWED at line 33; the service is fixed to collector at lines 60-61). llm-client has no token, token file or compose mount, so its read is refused today. The blocker file (lines 118-119) requires a separate llm network joined only by scanner, ui and llm-client, and a bearer token held only by the scanner. Neither is in the design or in §7. Verifier note: the origin is bound inside the key record for keyed providers (design:87, :89), so the foreign-origin gap is narrower than the zoom-out wording. The caller-token gap stands.
- Fix: Add to §4.5 and to T4: a separate llm network for scanner, ui and llm-client; no ports key on llm-client, with a compose test; a bearer token on POST /v1/chat held only by the scanner, with its token file and compose mount named; a service token and an allowed key-name list so llm-client can read only its own provider key names through the internal endpoint; a named missing-token error. Add a test that a call without the token is refused. State that GET /healthz returns no URL, key or provider data.

### B-02. The scanner chooses the class, key reference and host on every call, and no rule ties a key to its origin
- Lenses and ids: design DES-01 (blocker), DES-06 (major); structural ST-02 (major).
- Problem: design:89 says the scanner sends class, route, key_ref and model with every request. The accepted BL-1 option (blocker file line 103) sends only provider_id, model and route. llm-client would read class, origin and the approved flag from the registry and key record. Because the caller picks the class, a keyed request can name the ollama class. For the keyless ollama class, design:85 gives the base as http://<host>:11434 with no store for <host>, so no rule says where the host comes from or whether a key is attached. ST-02 adds that "keyed" is not defined by class. AI_PROVIDER_URL (design:100) is a scanner-side base URL with no store, and no rule stops it being sent (design:118, O6). That is the caller-chosen origin the design says it removes. No AI_ setting exists in env.template or scanner/ today (DES-06 verifier).
- Fix: Adopt the accepted contract. The request carries provider_id, model and route only. llm-client reads class, origin and approved flag from the registry and key record. Refuse the call when the provider row origin differs from the key record origin, and add the origin-mismatch test (blocker file line 136). Name the store and key for the ollama host, or state that ollama calls never carry a key. Remove AI_PROVIDER_URL from the request path, or name its store and say it is never sent to llm-client. Close O6. Define "keyed" by class.

### B-03. Key entry: the write route, its guardrails and the decision are not in the design
- Lenses and ids: design DES-03 (blocker); readiness IR-05 (blocker).
- Problem: design:87-88 says keys are entered on the settings page. The user decision (blocker file lines 37-47) lists guardrails: a custom request header, an Origin check, no plaintext echo after save, the UI bound to loopback, and the master key on the ui service only. ui/app/api.py:527-538 still returns 410 for PUT /secrets, and its docstring says the UI has no login. A grep of ui/app finds no Origin or custom-header check. Any container that reaches ui:8080 (see B-01) could write a key record. IR-05 adds that the design names no write route, no auth, no Origin rule and no app_secret key name. The blocker file (line 241) asks the same question again and recommends command-line entry, so the decision is not recorded once. Verifier note: secrets-and-roles.md line 63 was amended on 2026-11-12, so part of the decision is on file. design:88 says the key is shown masked and never in full after save, so the no-echo point is partly covered.
- Fix: Get the user's answer recorded once. If UI entry stays, name the route, its custom header and Origin check, and its test: a write without the header, or with a foreign Origin, is refused. Keep the route off the shared network (see B-01). State that no plaintext is returned after save. If entry is command-line only, say so and remove the settings-page wording at design:88.

### B-04. The provider store has no table, owner, grants, migration number or seed loader
- Lenses and ids: design DES-09 (blocker); codebase CD-03 (blocker); zoom-out BL-3 (blocker); comprehension C-03 (blocker); readiness IR-04 (blocker); structural ST-04 (blocker).
- Problem: design:99 and :102 put the provider list, saved models, the route and the active provider in the database. No table, column, grant or migration is named. config/ holds only glossary.json and retention.json, so the seed file config/llm_providers.json (design:84 and O17, design:132), said to be "loaded into the database on first start", does not exist, and no loader reads it. llm-client has no database access (design:89). The app login is POSTGRES_USER=scanner (env.template:10), while the existing grants go to market_scanner_app (045_app_secret.sql:20; 048_index_constituents.sql:25). The owner of the new tables is therefore undefined. The existing encrypted store app_secret (045) is not named. §7 has no migration, settings or key-entry task. Verifier note on O17: it does state a JSON-on-first-start mechanism, so the defect is the unnamed loader, not the absence of any mechanism.
- Fix: Name one migration with its number and down file. Name each table, its columns, its owner, and the grants for the scanner role and the API role. Resolve the POSTGRES_USER and market_scanner_app mismatch before writing the migration (blocker file line 219). Choose the seed method: inline in one migration (needs the user's sign-off, recorded in O17) or a named loader with a trigger and an insert-if-missing rule. Add tasks with acceptance commands for the migration, the settings API, the picker and the seed.

### B-05. The native Anthropic route has no class mapping, request or response mapping, endpoints or adapter
- Lenses and ids: design DES-07 (blocker); codebase CD-02 (blocker); zoom-out BL-2 (blocker); comprehension C-02 (blocker); readiness IR-03 (blocker); structural ST-03 (blocker).
- Problem: D9 (design:30) names anthropic_native. §4.5 still has ollama (design:85) and openai_compat (design:86), and places Anthropic under openai_compat. There is no request mapping: system prompt to a top-level field, required max_tokens, json_schema with strict, and no temperature on newer Claude models. There is no response or usage mapping. §4.5 lists only /v1/chat and /healthz (design:83). The model-list call (§4.6) and the one-call test (O15) have no shape. T4 (design:155) names llm_client/ with no adapter file, and no such directory exists. The max_tokens rule is missing. scanner/llm.py:297 sets OPENAI_MAX_TOKENS to 500 for all calls, and the blocker file sets 500 for extract and 1400 for conclude (blocker file lines 33, 163). The primary and secondary labels (design:97, O9) have no effect once O11 makes the route a plain setting. A user-added provider has no rule for picking a class, and no rule for when none fits (zoom-out BL-2).
- Fix: Add anthropic_native to D9 and §4.5 with its request and response mapping, and max_tokens per call kind. Add the model-list and test endpoints with request and response shapes. Name the adapter files under llm_client/adapters/ and their tests in T4, splitting T4 into adapter and test tasks. Remove primary and secondary, or give them an effect. State the class rule for a user-added provider. Alternatively, take the native route out of this design until it is approved.

### B-06. An upgraded install stops on its first run because no model is saved, and the stop writes no run status
- Lenses and ids: design DES-11 (blocker), DES-25 (minor, not checked); codebase CD-04 (blocker); zoom-out BL-4 (blocker); readiness IR-06 (blocker); comprehension C-05 (major); structural ST-07 (major).
- Problem: design:99 makes the Qwen3.5 Q6_K tag the default for fresh and upgraded installs. That matches production (start.ps1:62 and scanner/conclude.py:41), and the user confirmed it (design:130, O16; blocker file lines 50-53). The default is settled in the text. The mechanism is not. No migration or §7 task writes that tag into the saved setting of an existing install. The code default is still qwen3:8b (scanner/llm.py:65). design:99 says a blank run stops and shows a notification, but writes no failed-run record. runs.status allows only running, complete, failed and partial (001_core.sql:11), so a new model_not_set status would be rejected. §6 (design:136) forbids changing the Ollama models in use without separate approval and does not cite the BL-4 confirmation (DES-25). The blocker file still asks the upgrade question (lines 294-296 and 356). Verifier note: the "contradicts the must-not-change list" framing is weaker than stated, because O16 is the approval. The real defect is the missing seed and the two-place default.
- Fix: Record the user's answer on upgrade behaviour. Name the seed as a migration or as a task that runs before T5, with a guard on existing run history. Record a stopped run as failed with a reason note (model_not_set), since runs.status takes no new value. Make the banner read the saved setting. Cite the BL-4 confirmation in §6 with its date. Keep one default: change scanner/llm.py:65 in T5.

### B-07. The §3 call-site inventory contradicts the code in three places
- Lenses and ids: codebase CD-07 (blocker); design DES-23 (minor, not checked); comprehension C-09 (major); structural ST-10 (major), ST-13 (minor, not checked).
- Problem: design:43 says enrich reads LLM_URL. enrich.py takes --llm-url (line 1069) and reads no environment value. start.ps1 reads LLM_URL (lines 63-64) and passes it (line 328). design:44 places llm.health (line 105) under scanner/conclude.py. The call is in the root conclude.py:105. scanner/conclude.py has only requests.post (line 558). design:44 lists scanner/extractcheck.py as an LLM call site, and T5 lists it too. It imports only AGREE_TOLERANCE_PCT (lines 16 and 23) and makes no LLM call. ST-13 adds that the bench_extract.py health call is at line 44, not 43, and that the concall-vl-extraction-plan.md citation does not match.
- Fix: Correct each citation. Cite root conclude.py:105 for llm.health. Remove extractcheck.py from §3 and T5, or keep it only as a dependent of AGREE_TOLERANCE_PCT. Correct the enrich statement. Re-check every line citation against the file at approval time.

### B-08. O5 says the parser keeps all 2,635 rows; the parser drops rows and dedupes pairs
- Lenses and ids: codebase CD-06 (blocker); design DES-19 (major); readiness IR-15 (minor, not checked).
- Problem: O5 (design:112) says the parser keeps all 2,635 rows, that the write path does not dedupe, and that the 2-row gap is a snapshot difference. equity_list_rows skips rows with a blank symbol, ISIN or name (company_reference.py:82-83) and keeps only the first row per (symbol, ISIN) (line 85). The insert has no conflict clause (lines 107-112), and the primary key is (source, symbol, isin) (047_company_reference.sql:19). The parser dedupe is therefore load-bearing. The 2,635 figure holds only if every drop count was zero, and no drop counts are recorded. Verifier note: EQUITY_L.csv is not in the repository, so the count could not be checked here.
- Fix: Record per-rule drop counts from an offline parser run (blank symbol, blank ISIN, blank name, repeated pair). Correct O5 to say what the code does. State that the parser dedupe is load-bearing. Keep the 2-row gap open until the two symbols are diffed against a fresh download.

### B-09. §3 says load_index_for_source is used for the event lookup; no production code calls it
- Lenses and ids: codebase CD-05 (blocker); design DES-15 (major); comprehension C-06 (major); readiness IR-08 (major); zoom-out Z-06 (major).
- Problem: design:40 says load_index_for_source (company_reference.py:199) is "used for the event lookup with nse_csv". Its callers are tests only (tests/test_company_reference.py:197-218). home_events.py:151 is a docstring mention. run_cycle has no production caller (home_events.py:695-696 says so), and fill_from_name runs only inside run_cycle (home_events.py:495). The NSE-wins change (D6, O1, T2) therefore changes no runtime result before T9. Z-06 adds that the design says Upstox rows decide no event match today, which means T2 is inert until T9. The present tense in design:40 is wrong.
- Fix: Change design:40 to "intended for the event lookup; not called in production until T9". Say in D3, §4.1 and T2 that T2 changes no run-time result until T9. Add the production consumer to the T9 dependency, or defer T2.

## 3. Major

### M-01. The key record's freshness pointer, approved flag, origin binding and AAD are named but not specified
- Lenses and ids: design DES-04 (major); readiness IR-02 (major).
- Problem: design:87 says the key record binds its origin, and design:142 says the AAD scheme changes by "the BL-1 freshness pointer". Neither says what the pointer is, where it is held, or how llm-client refuses a stale version. The accepted fix (blocker file lines 24 and 114) names a UI-held freshness pointer against rollback. Line 120 names an approved flag inside the encrypted record, and the design has neither. Per-provider approval (old open point M-02) therefore stays open. The named BL-1 tests (blocker file lines 135-140; the verifier counted six entries, not four) are not in §7. secret_crypto.py:68-70 shows the AAD is table, name, owner and key version, so the pointer is not in the AAD as design:142 implies.
- Fix: State the pointer (owner, storage, check rule), the approved flag and its default, and what the AAD covers. Correct design:142. Add the named BL-1 tests to T4.

### M-02. key_ref has no naming rule; the proposed names fail the app_secret check, and the no-delete rule is not stated
- Lenses and ids: design DES-21 (major).
- Problem: design:87 says key_ref names the key in the encrypted database but gives no rule. 045_app_secret.sql:7 requires ^[a-z][a-z0-9_]{1,63}$, so a name such as openrouter-key is rejected. The table has no DELETE grant (045:19-20), which the design does not mention.
- Fix: Add the naming rule to §4.5 with example names. State that keys are not deleted, and that the UI never reads a value back.

### M-03. Provider settings have up to five homes, and the design gives conflicting rules for the same settings
- Lenses and ids: comprehension C-15 (major); zoom-out Z-07 (major).
- Problem: design:98 says AI_PROVIDER_NAME selects a block in config/llm_providers.json. O17 (design:132) says that file is not read at run time. design:99 says AI_MODEL_NAME is saved to the database, while O16 (design:130) says the backend uses it "if it is applied from settings". design:100 says AI_PROVIDER_URL holds the base, with no store named. The homes are the JSON file, the database provider table, the llm-client registry, app_secret and environment values. Each needs one writer and one reader, and the design names neither.
- Fix: Make the database the only runtime source for provider, route, URL and model. Keep env names only for LOCAL_LLM_URL. For each AI_* setting, state one store, one writer, one reader and the default used when the row is missing. Correct design:98 and close O6.

### M-04. Files that carry the model default or the old LLM_URL and CONCLUDE_URL names are missing from T4 and T5
- Lenses and ids: design DES-12 (major); readiness IR-16 (major); structural ST-11 (major).
- Problem: T5 (design:156) lists scanner/llm.py, scanner/conclude.py, enrich.py, extractcheck.py, bench_extract.py, bench_models.py and env.template. It omits the root conclude.py (default model at line 86, CONCLUDE_URL at lines 84-85 and 108, llm.health call at line 105) and start.ps1 (model at lines 62 and 328, LLM_URL at lines 28-29 and 63-64). README.md uses LLM_URL (lines 119 and 136). O6 renames LLM_URL and CONCLUDE_URL to LOCAL_LLM_URL with no alias and no cutover step for existing .env files. docker-compose.yml:112 sets CONCLUDE_URL. The change to the scanner/llm.py:65 default is not named in T5.
- Fix: Add start.ps1, README.md and the root conclude.py to T4 or T5, and name the scanner/llm.py:65 change. Keep the old names as read-only aliases for one release, or add a cutover step. List the LOCAL_LLM_URL value for each service in §4.5.

### M-05. Two Anthropic routes are built at once, and the compatibility-layer claim is wrong
- Lenses and ids: zoom-out Z-02 (major); design DES-08 (minor, not checked).
- Problem: design:97 says either route alone is enough. O9 (design:121) records that the user wants both. O11 (design:123) gives no automatic switch, so the second route is a manual toggle. Building both doubles the Anthropic adapters, their tests and the strict_check gate. design:91 says the compatibility layer silently drops unsupported fields. The verified correction (blocker file lines 180-181) says several fields return HTTP 400 and most are ignored. The cited URL (design:91) is not the canonical one (blocker file line 185).
- Fix: Confirm O9 for the first build. If confirmed, build the native route first and add the compatibility route after its test passes. Replace the design:91 wording with "most unsupported fields are ignored; some return an error", and cite the canonical URL. Confirm the anthropic-version value and the native response fields in the live documentation before T4 starts (blocker file line 184).

### M-06. Migration 054 is claimed for more than one piece of work
- Lenses and ids: design DES-10 (major); comprehension C-04 (major); readiness IR-09 (major); structural ST-05 (major); zoom-out Z-08 (major).
- Problem: D12 (design:33) says the next free number is 054 and that S2a takes the next free number when written. §6 (design:141) gives 054 to the BSE migration. The blocker file gives 054 to the provider store (lines 205 and 262) and to BSE (lines 77 and 90). No file numbered 054 exists. The highest file on disk is 053_fund_daily.sql, and 049 to 052 have no files. Verifier correction (C-04): db/migrations holds 001 to 048 plus 053, so the statement that only 047, 048 and 053 exist (in CD-03, ST-04 and C-04) is wrong. The gap that matters is 049 to 052.
- Fix: Give each piece of work its own number in D12 and §6 (for example 054 for the provider store and 055 for BSE). Record the claim in docs/designs/collector-split-slices.md (blocker file line 199) so that S2a cannot take it. Remove the BSE reservation until the BSE build starts. State what 049 to 052 are, or that they are unused.

### M-07. BSE is recorded as both approved and deferred
- Lenses and ids: codebase CD-09 (major); structural ST-06 (major); design DES-16 (minor, not checked).
- Problem: §4.2 (design:59) and §6 (design:141) say the BSE source was approved on 2026-11-12. O2 (design:108) says "The BSE source is not yet approved". It also says no BSE loader, table or matching is in this design, while §4.2 states the BSE rule. spec §3.2 (line 97) and the spec decision log (line 669) record approval with the build deferred. The blocker file (line 58) agrees.
- Fix: Change O2 to: source approved 2026-11-12, build deferred (spec Z2). Cite the BSE rule text (blocker file lines 79-84) once, in §4.2. Give BSE its own migration number (M-06).

### M-08. The index download rules in the fetch script are not carried into the design or the job
- Lenses and ids: design DES-22 (major); codebase CD-10 (major); readiness IR-11 (major); comprehension C-13 (major).
- Problem: §4.4 (design:76) says each index takes "its primary and fallback CSV URL" from scripts/fetch_index_constituents.py. The script has one primary and one fallback base, up to three filename variants per index (MAX_VARIANTS = 3, line 23), a pause between requests, and a content check. The fallback host is tried with only variants[0] (lines 82-85). SCAN_INDEXES (company_reference_job.py:36-41) holds one URL pair per index. fetch_index_bytes (about lines 67-74) accepts any 200 response, so an HTML page with status 200 on the primary host ends the fetch without trying the fallback. The empty parse then raises EmptySourceError (lines 113-115). Nothing paces the six requests. The verifier notes that the script line numbers drift slightly; the substance holds.
- Fix: Write each index as a list of candidate URLs, and state which filename is used. Port the content check and the pacing into fetch_index_bytes. Record the status code and host, without the query string, for each source tried. Add tests for an HTML 200 response and for a 404 on the first filename.

### M-09. Six index downloads can block the master refresh, and §4.4 has no failure policy
- Lenses and ids: codebase CD-11 (major); readiness IR-12 (major).
- Problem: run_refresh fetches and parses every source before any write (company_reference_job.py:106-115). fetch_all_indexes raises on the first failed index (lines 74 and 79). The company_reference refresh and the index replacement share one transaction (lines 118-121). One failed index therefore writes nothing, including nse_csv and upstox_master. The coupling covers one index today, and it covers six after this change. §4.4 states no policy.
- Fix: Choose one policy and write it in §4.4: independent refresh per index with last good data kept, or all-or-nothing with a named alert. Add a test in which one index fails and the master result is checked.

### M-10. The index membership reader already exists; constituent_membership.py is a writer
- Lenses and ids: codebase CD-12 (major); zoom-out Z-04 (major).
- Problem: constituent_membership.py reads CSV files and upserts constituent_membership rows (lines 39-43 and 96-102). design:77 says it reads the database. A reader already exists: scanner/constituents.py load_constituents reads index_constituents by default (lines 34-49), through cr.load_index_constituents (company_reference.py:300), and it has several callers. T3 (design:154) would add a third reader. No transform from index_constituents rows to constituent_membership rows with an as-of date is written, and no retention rule is stated.
- Fix: Reuse load_constituents or cr.load_index_constituents. State the transform, the as-of rule and the retention rule. Keep the CSV path for one release as a documented operator rollback. State that a zero-row index raises rather than returning an empty membership.

### M-11. The six index names are spelled in two cases and are not listed in the design
- Lenses and ids: codebase CD-13 (major).
- Problem: SCAN_INDEXES (company_reference_job.py:37) and DEFAULT_INDEX (constituents.py:13) use "NIFTY TOTAL MARKET". constituent_membership.py SLUG_TO_INDEX (lines 30-36) and relative_strength.py (lines 37-47) use title case, such as "Nifty 50". The reads match names exactly, so the casing decides whether relative_strength finds its rows. §4.4 says the six go "under their index names" and lists none.
- Fix: Put the six names and filenames in one module that the job, the fetch script and constituent_membership.py all import. Choose one casing. List the six exact names in §4.4. Add a test that each name loads back with non-zero rows.

### M-12. Conflict rules in build_index: symbol-level and name-level conflicts are not specified
- Lenses and ids: codebase CD-14 (major); readiness IR-14 (major).
- Problem: design §4.3 covers only an ISIN present in both sources. build_index (company_reference.py:142-144 and 148) drops any symbol that maps to two ISINs and skips every row for it (line 153). An NSE symbol whose ISIN differs from an Upstox row therefore loses its NSE row too, and the NSE-wins rule does not reach it. Name conflicts are dropped the same way (lines 158-162). T2 names one test file and no test names.
- Fix: Add the symbol-level rule: an NSE symbol and its ISIN are never removed by an Upstox row. Add the name-level rule. Name the tests: an Upstox-only collision, and a symbol shared across sources.

### M-13. The O3 "one row per ISIN, using the EQ row" rule is not in the code and has no task
- Lenses and ids: codebase CD-08 (major); design DES-18 (major); readiness IR-13 (major); structural ST-14 (minor, not checked).
- Problem: O3 (design:109) says "Settled: option A, one row per ISIN, using the EQ row." equity_list_rows (company_reference.py:73-86) keys rows on (symbol, ISIN), stores SERIES (line 84) without comparing it, and keeps the first row per pair (line 85). No EQ preference exists. An ISIN with an EQ row and a BE row under different symbols keeps both, and build_index then drops the ISIN as a conflict (lines 145-149). The existing test asserts keep-first. §4.1 (design:53) says nse_csv holds "all series". Whether the BE row shares a symbol with the EQ row cannot be checked here, because EQUITY_L.csv is not in the repository.
- Fix: Add an EQ-preference step to equity_list_rows as a task, with tests for both file orders, including 21STCENMGM, and state the expected row count. Or change O3 to describe what the code does. Correct §4.1 either way.

### M-14. normalise_name is described in D1 with one step; the code has more
- Lenses and ids: design DES-17 (major).
- Problem: D1 (design:22) says name normalisation replaces .,'()- with a space and needs no code change. normalise_name (company_reference.py:26-31) also uppercases, maps & to AND, maps LIMITED and LTD to LTD, and collapses spaces. The matched count in §4.2 depends on those steps. §4.2 step 1 uses the function without defining it.
- Fix: State every step in D1 and in §4.2 step 1, with the citation to company_reference.py:26-31.

### M-15. §7 has no rows for the new work, no test names and no runtime checks, and its IDs reuse spec IDs
- Lenses and ids: design DES-13 (major); codebase CD-15 (major); readiness IR-18 (major), IR-24 (minor, not checked).
- Problem: §7 (design:150-158) has rows T1 to T7 only. No row covers the provider migration, the settings API and picker, the key write route, the llm-client token and compose network, the secrets-and-roles amendment, or the seed. The name-resolution task (spec §9 T4f, spec line 630) is missing. Nothing pins the result on the 142-item fixture (111 matched, 0 ambiguous, 31 unmatched). Every row has the same unittest command (design:148). No task names test cases. T3 and T5 name no test file. T4 does name tests/test_llm.py (lines 72-75) and tests/test_conclude.py (line 207), so the claim that T4 names none is wrong (verifier note). No task has a runtime check for the refresh, llm-client health or the call sites. The labels T1 to T7 reuse spec labels for other work (spec T1 is the home_filings registration, T6 is post_events, T7 is the parsers). IR-24 is the minor note on that reuse.
- Fix: Add one row for each missing item, with its file list, its dependency, its named tests and a runtime check. Name the test file and test names for T1, T3 and T5. Add a name-resolution row with a count test on the 142-item fixture. Add runtime checks: T1 gives one refresh run with six non-zero index counts; T4 runs docker compose config, GET /healthz and one test call per enabled provider; T5 writes call records from one run with RUN_ID set. Rename the design tasks (for example DT1 to DT7) and map them to spec IDs.

### M-16. Call records: the table, columns, writer and route are not named, and RUN_ID is a silent no-op
- Lenses and ids: codebase CD-16 (major); readiness IR-19 (major).
- Problem: design:92 says each call is recorded "the way conclude records LLM calls today, with RUN_ID", without a table, columns or writer. The writer is the scanner (metrics.record_call, called from scanner/llm.py:476 and 497 and from conclude.py:567 and 589), not llm-client, which has no database access. record_call is a silent no-op when RUN_ID is unset (metrics.py:95-97; tests/test_metrics.py:70-79). The llm_calls stage check allows only extract and conclude (001_core.sql:68). A new stage needs a schema change, and a new provider, route or host column needs a migration. Neither is named. The route and base host are not recorded. Verifier note: a new provider or route alone does not need a stage change.
- Fix: Name the scanner as the writer, name the table and columns, and add provider, route and base host (no path or query) to each record. Add the migration for the new columns and the stage change. Add a run-start warning when RUN_ID is unset for runs that must record calls. Test that one cloud call writes exactly one record.

### M-17. strict_check: the required fields and the failure text are not specified
- Lenses and ids: codebase CD-17 (major).
- Problem: design:91 says strict_check fails a reply that lacks a required field, but lists no fields per call kind. SCHEMAS (scanner/llm.py:253) holds them, and _obj (lines 207-209) makes every property required by default. The design does not say whether null counts as missing, and does not name the error text.
- Fix: List the required fields per kind, citing SCHEMAS. Define the failure as strict_check_missing_field:<name>. State the null rule and what is logged.

### M-18. healthz contents, the health probe and the list and test calls are not defined
- Lenses and ids: codebase CD-18 (major); readiness IR-20 (major).
- Problem: §4.5 names GET /healthz with no response fields (design:83). scanner/llm.py health() probes /api/tags for ollama and /v1/models otherwise (lines 401-409). Its callers are conclude.py:105, enrich.py:398 and bench_extract.py:44. After the cutover the probe has no defined target, and compose's health check is not named. The model-list call (§4.6) and the O15 test call have no endpoint shape. §4.6 (design:103) gives the list path as "provider list, then llm-client, then Fastify, then the UI" and does not say who supplies the base URL and key_ref on a list call.
- Fix: Define the healthz fields: active provider name, class, route, base host, model set yes or no, key resolved yes or no, secrets API reachable yes or no, time of last successful call. State which probe compose and health() use, and that health() probes healthz only. Define the list and test endpoints with the same request contract as §4.5. Name the router that serves them (see M-22).

### M-19. llm-client re-specifies request shapes that scanner/llm.py already builds
- Lenses and ids: zoom-out Z-05 (major).
- Problem: scanner/llm.py already builds the Ollama-shaped and OpenAI-shaped requests, the endpoint choice and the health probe (LLMConfig and endpoint at lines 61-76, num_ctx options at line 360, max_tokens at line 366, health at lines 401-407). §4.5 (design:85-86) defines llm-client classes for the same two shapes and does not say whether the code is reused or copied. Two copies would drift.
- Fix: State the reuse. Move the pure payload and response functions into a module that both images import, or add a test that pins the two copies to the same output.

### M-20. Scope: the llm-client platform is bundled into the event-matching design, and the reason for llm-client is not stated
- Lenses and ids: zoom-out Z-01 (major); zoom-out Z-09 (minor, not checked).
- Problem: §1 frames the root problem as attaching a symbol and ISIN to each event (design:9-12). Most open points (O6 to O17) and tasks T4 to T6 cover provider choice, keys, routes and a model picker. The design does not say why llm-client is needed. The reason is that provider keys must not reach the scanner process. D8 cites Decision 10 only (Z-09).
- Fix: Move the llm-client and provider work to its own design with its own review. Keep this file to matching and index membership, and limit §7 to those tasks. Add one sentence to §1 that states the reason for llm-client.

### M-21. Provider scope: four presets in O17, model-list endpoints for more providers, and unverified items marked as verified
- Lenses and ids: zoom-out Z-03 (major); comprehension C-17 (minor, not checked).
- Problem: O17 (design:132) lists four presets: OpenAI, Anthropic, OpenRouter and Ollama. §4.6 (design:103) adds model-list endpoints for Gemini, Groq, Mistral and Together AI, which have no provider block. The Gemini auth header is unchecked. §4.6 says the model-list endpoints were "Verified 2026-11-12" but puts unconfirmed items in the same bullet: OpenAI paging (its official page returned 403), the Gemini auth header, the anthropic-version value and the Together AI host. No source link is given per endpoint. design:102 lets users add any provider by URL, so removing the extra endpoints conflicts with that line.
- Fix: Limit T4 to the four presets, or add each extra provider as a later task. Split the bullet into a verified list and an unverified list, each with a source and a date. Treat an unverified item as blocking for its provider until it is checked. Reconcile design:102 with the scope.

### M-22. Fastify is named in the data path; the deployed browser API is FastAPI
- Lenses and ids: design DES-20 (major); structural ST-09 (major); readiness IR-23 (minor, not checked).
- Problem: design:103 gives the path as provider list, llm-client, Fastify, then the UI. docker-compose.yml has no Fastify service. The Fastify code is under server/, and compose does not run it. ui/app/api.py:11 imports FastAPI, and the settings routes and PUT /secrets are in that file. The owner of the provider routes is therefore unnamed.
- Fix: Replace Fastify with the FastAPI router in ui/app/api.py and name the route file and its prefix. Or name the new service, and add it to compose and §7. State which service serves the settings routes and the model picker.

### M-23. Superseded rules remain in the "Decided" table without a mark
- Lenses and ids: comprehension C-08 (major); structural ST-12 (major); readiness IR-17 (major).
- Problem: Section 2 is headed "Decided". D11 (design:32) still says one provider is "chosen by LLM_PROVIDER", which §4.6 (design:98) replaces with AI_PROVIDER_NAME. D10 (design:31) puts the model in the llm-client config block, which §4.6 and O17 replace with the database. D9 (design:30) carries only a note on key entry, and its two-class list was replaced by the three classes in O9. A builder who reads §2 gets the old rules.
- Fix: Mark D9, D10 and D11 as superseded, each with a pointer to the replacing answer. Or rewrite each row to the final rule.

### M-24. Terms are used without a definition
- Lenses and ids: comprehension C-10 (major); comprehension C-11 (minor, not checked).
- Problem: "UI provider registry" (design:87), "freshness pointer" (design:142, the only place it appears), "loader role" (D13, design:34), "secrets API" (design:45 and :87) and RUN_ID (design:92) are not defined. Acronyms and project terms are also undefined on first use: ISIN, NSE, BSE, Upstox, upstox_master, EQUITY_L.csv, universe, num_ctx, GGUF, Q6_K, Fastify, strict_check, "the 142-item sample", "spec §4.3", "spec Z2" and "filings T9". These terms carry the key-security rules in B-01 and B-02.
- Fix: Add a glossary, or link each term to its owner and its file. For each term, state the store or endpoint and the file that implements it.

### M-25. Benchmarks and the vLLM path are not addressed in O8 or T5
- Lenses and ids: codebase CD-19 (major).
- Problem: bench_extract.py takes --url, --api and --model (lines 34-36) and builds LLMConfig from them (line 43). bench_models.py starts a vLLM container on 127.0.0.1:8003 (lines 40 and 64) and passes its own base URL (line 116). O8 (design:120) says benchmarks use the active provider and take no provider argument, but says nothing about these flags or the vLLM path. If the active provider overrides the URL, a benchmark measures a different model with no error. "vLLM" does not appear in the design.
- Fix: State what happens to the three flags. Decide whether the vLLM path goes through llm-client or stays a separate offline tool. Make a benchmark fail when its URL is overridden.

### M-26. The cutover, rollback and error rules are missing
- Lenses and ids: readiness IR-21 (major).
- Problem: No setting picks the direct or the client route. No rollback is written. T5 depends only on T4, with no health gate before merge. The only error case is "key is missing" (design:88). Provider rejection, timeout, secrets API failure and strict_check failure have no named codes. No redaction rule covers error text.
- Fix: Add a route setting for one release, or a rollback that reverts the T5 commit and removes the service. Require GET /healthz to pass before T5 merges. Define a named error code for each failure case, and one shared redaction function for error text.

### M-27. Loader role setup: the grants and the loader password variable are not in any migration or template
- Lenses and ids: readiness IR-10 (major); design DES-24 (minor, not checked).
- Problem: 047_company_reference.sql (lines 44-47) says the loader role is created outside the migration, and it grants only SELECT to the app role. The refresh needs DELETE and INSERT on company_reference (company_reference.py:223 and 229-235). The only loader grant in the migrations is on index_constituents (048_index_constituents.sql:25). The design says nothing about the admin step (§4.1, design:54). D13 (design:34) says POSTGRES_LOADER_PASSWORD_FILE is set in .env. company_reference_job.py:13 reads it, but env.template and docker-compose.yml do not contain it, so a fresh setup has no template entry. Verifier note: company-reference-handoff.md:11 says the grant exists in the database, so the gap is that it is undocumented and not migrated.
- Fix: Name the admin step and its exact GRANT statements in §4.1 or in a task. Add the loader variable, with a comment, to env.template. Add a check that the loader can write both tables before the first refresh run.

## 4. Minor

### m-01. Open question: whether a saved key moves when a provider URL changes
- Lenses and ids: design DES-14 (minor, not checked).
- Problem: design:102 lets the user change any provider URL. The blocker file (lines 127-131) asks whether a saved key moves to the new host or must be typed again. The design records no answer, and §5 does not list the question.
- Fix: Add the question to §5 as an open point, and record the answer before approval.

### m-02. Spec §6 names a function that does not exist
- Lenses and ids: zoom-out BL-5 (minor, not checked); structural ST-08 (minor, not checked).
- Problem: spec line 556 names load_events_name_index. No such function exists. The code has load_index_for_source (company_reference.py:199) and fill_from_name (line 166). The spec and the design now agree on name-first for NSE and ISIN-first for BSE (spec line 97; design:59). The design:40 wording is covered by B-09.
- Fix: Change spec line 556 to the real names, or record the rename in the spec and the design. Cite spec §3.2 in §4.2.

### m-03. BL-5 residuals: rule sources are cited, not quoted
- Lenses and ids: codebase CD-20 (minor, not checked); comprehension C-07 (minor, not checked); readiness IR-07 (minor, not checked).
- Problem: The name-first (NSE) and ISIN-first (BSE) split now appears in §4.2 and in spec §3.2, and the two agree. The design does not list BSE rules (a) to (d) (blocker file lines 79-82), and it does not quote the user's answers with their dates. The blocker file still asks for the name-first wording (line 341). The BSE status conflict in O2 is covered by M-07.
- Fix: Quote the user's name-first and BSE answers, with dates, in §4.2 and O2. Note the status of the blocker file where it is cited, because the file is labelled "Recommendations only, except where...".

### m-04. The migration 047 header comment names the wrong source file
- Lenses and ids: codebase CD-21 (minor, not checked).
- Problem: db/migrations/047_company_reference.sql (lines 1-2) calls nse_csv the "NSE Nifty Total Market constituents list". The loader reads EQUITY_L.csv (company_reference.py:70), which holds all series, and design §4.1 (line 53) says all series. A T2 implementer who reads the migration is misled.
- Fix: Correct the comment in a comment-only change inside the T2 or documents task. Name the source file in §4.1.

### m-05. References without a path: BL labels, the decision log, and review IDs used as decision references
- Lenses and ids: comprehension C-12 (minor, not checked); zoom-out Z-10 (minor, not checked).
- Problem: The BL-1 to BL-4 labels are used in §2, §4.5 and §4.6 without a path to the blocker file. The blocker file is cited once (design:59). Line 5 cites "the brainstorm decision log (Decisions 1 to 14 and Q1 to Q5)" with no path. Review IDs appear inside decision text, where they become stale once the review is closed.
- Fix: Give the path of the blocker file and the decision log at first use, or quote each decision inline with its date and the user's words. Replace each review ID with the decision it refers to.

### m-06. Numbering and stale headings
- Lenses and ids: comprehension C-16 (minor, not checked); structural ST-15 (minor, not checked).
- Problem: §2 goes from D13 to D15 with no D14. §5 goes from O9 to O11 with no O10, and O9 points to O11, which is already answered. Line 162 refers to "line 148 of the file before this edit". The §5 heading says every point needs an answer before approval, but most entries are settled.
- Fix: Mark D14 and O10 as withdrawn, or renumber. Update the O9 pointer. Remove the line-number reference. Retitle §5 to separate settled points from open ones.

## 5. Verification and unverifiable items

- UNVERIFIABLE: none. No kept finding has that verdict.
- NOT_CHECKED: 24 findings, all minor. The verifier did not check them, so they are kept as minor items and marked in their entries. They are DES-08, DES-14, DES-16, DES-23, DES-24, DES-25, CD-20, CD-21, ZO-BL-5 (zoom-out BL-5), Z-09, Z-10, C-07, C-11, C-12, C-16, C-17, IR-07, IR-15, IR-23, IR-24, ST-08, ST-13, ST-14 and ST-15.
- Checks that could not be run in this review: EQUITY_L.csv is not in the repository, so the 2,635 count, the drop counts, and whether the BE row shares a symbol with the EQ row are open (B-08, M-13). The provider and Anthropic documentation was not fetched, so the model-list and anthropic-version items are open (M-05, M-21).
- Verifier corrections applied in this review:
  - zoom-out BL-1: the origin is bound inside the key record for keyed providers (design:87, :89). The caller-token and foreign-origin gaps stand (B-01, B-02).
  - zoom-out BL-4: the default and its confirmation are in the text (design:99, :130). The defect is the missing seed and stop record (B-06).
  - design DES-04: the blocker file lists six test entries (lines 135-140), not four (M-01).
  - comprehension C-04 and the evidence in CD-03 and ST-04: db/migrations holds 001 to 048 and 053. Only 049 to 052 are missing (M-06).
  - comprehension C-03: O17 does state a JSON-on-first-start mechanism. The defect is the unnamed loader (B-04).
  - readiness IR-06: the upgrade behaviour is stated at design:130, but no guard mechanism is given (B-06).
  - codebase CD-07: enrich.py takes --llm-url and reads no environment value, so the "reads LLM_URL" statement is false (B-07).
  - structural ST-04: the verifier found the key-entry decision amended in secrets-and-roles.md line 63 on 2026-11-12, which differs from the blocker file's note that the file was not edited (B-03).
  - readiness IR-22: refuted, with a narrower point (appendix).
- Counts by lens (kept findings, confirmed, not checked): design 25 (19, 6); codebase 21 (19, 2); zoom-out 15 (12, 3); comprehension 17 (12, 5); readiness 23 kept of 24 (19, 4), with 1 refuted; structural 15 (11, 4). Total 116 kept: 92 confirmed and 24 not checked.

## Appendix: refuted findings

- **readiness IR-22** (egm-implementation-readiness, major). Title as raised: "The monthly refresh has no scheduled runner or owner." Verifier reason: the cited evidence is wrong. The job is a registered collector source (scanner/collect/sources.py:618-643 calls run_refresh, and SOURCES is at line 678). The collector is a long-running service with a cron scheduler (scanner/collect/scheduler.py, due_sources). company_reference_job.py:11-12 is a usage note, not evidence that the job runs only by hand. Narrower point that stands, not counted here: no migration seeds a cron schedule for company_reference, the design does not name the collector source or a cadence, and the design has no data-age check.

## Appendix: status of the old blockers BL-1 to BL-5

- **Old BL-1 (llm-client, key routing and caller authentication): partly resolved; still open on authentication and the request contract.** Resolved: for keyed providers, the scanner no longer sends a base URL (design:89), and the origin is bound inside the key record (design:87). Open: caller authentication on POST /v1/chat, the separate llm network, the llm-client token and its read path to the key store, the per-request payload (class and key_ref still sent), the freshness pointer, the approved flag, the foreign-origin test, and the AI_PROVIDER_URL path. Evidence: design:82-83, :87, :89; docker-compose.yml:225-227; ui/app/internal_secrets.py:33 and :60-61. Findings: B-01, B-02, M-01, DES-06, IR-02.
- **Old BL-2 (native Anthropic route): open.** D9 (design:30) names anthropic_native, but §4.5 has no block, mapping, endpoint or adapter (design:83, :85-86, :155). The primary and secondary labels remain (design:97). Evidence: design sections 2, 4.5, 4.6 and 7. Findings: B-05, M-05.
- **Old BL-3 (provider store and key entry): partly resolved; the store and the write route are open.** Resolved in part: the key-entry decision is partly recorded (secrets-and-roles.md line 63, per the ST-04 verifier), and the design says keys are entered on the settings page (design:87-88). Open: no provider table, owner, grants, migration number or seed loader (B-04); no key write route or guardrails, and PUT /secrets still returns 410 (ui/app/api.py:527-538; B-03); the migration number collision (M-06). Findings: B-03, B-04, M-06, M-02.
- **Old BL-4 (upgrade model default): partly resolved; the mechanism and the stop record are open.** Resolved in text: the Qwen3.5 Q6_K tag is the default for fresh and upgraded installs, which matches start.ps1:62 and scanner/conclude.py:41, and the user confirmed it (design:99, :130). Open: no seed for upgraded installs; no run-history guard; no failed-run record for the stop, because runs.status (001_core.sql:11) has no value for it; scanner/llm.py:65 still defaults to qwen3:8b; §6 does not cite the approval (design:136); T5 omits the root conclude.py and start.ps1 (M-04). Findings: B-06, M-04, DES-25.
- **Old BL-5 (name-first versus ISIN-first matching): resolved in substance; residuals open.** design:59 and spec §3.2 (line 97) now both say NSE is name-first and BSE is ISIN-first (C-07, ST-08, IR-07). Residuals: O2 still says the BSE source is not approved (M-07); design:40 says load_index_for_source is used for the event lookup (B-09); spec line 556 names a function that does not exist (m-02); the user's answers are not quoted (m-03). Findings: M-07, B-09, m-02, m-03.
