# Home-events T4f design: Goldfish review

- Design reviewed: `docs/designs/home-events-t4f-design.md` (not edited)
- Mode: BRAINSTORM
- Date: 2026-11-12
- Totals: 143 findings from six lenses. 132 were kept: 129 confirmed and 3 unverifiable. The 3 unverifiable findings were not checked, because the verifier failed on each one (see section 5). The 132 kept findings were merged into 41 entries (5 blockers, 30 major, 6 minor). 11 were refuted and are listed in the appendix with reasons. These counts were recomputed from the verifier output; an earlier version of this header had different totals.
- Id note: finding ids are numbered per lens, so one id can appear under two lenses (for example F01 under egm-design and egm-structural). Each id below is written with its lens: design = egm-design, codebase = egm-codebase-details, zoom-out = egm-zoom-out, comprehension = egm-comprehension, readiness = egm-implementation-readiness, structural = egm-structural.

## 1. Summary

Five blocking issues must be settled before approval: llm-client lets the caller choose the address a stored provider key is sent to, the native Anthropic route has no adapter, the provider settings store has no schema, owner, migration or seed loader, a fresh upgrade stops every enrich and conclude run until someone picks a model, and the design and the filings spec give opposite orders for matching events. The six lenses produced 143 findings. Of these, 129 were confirmed and 3 could not be checked, and the 132 kept findings were merged into 41 entries. 11 were refuted and are listed in the appendix with reasons. Most major items are places where the design states a rule or a count that the code does not yet follow, including the one-row-per-ISIN equity rule, the claim that the parser keeps every row, the NSE-wins change that nothing calls in production, and the 751 index count. The task list checks each task with one unit-test command, reuses task IDs the filings spec already uses, and has no rollback, runtime check or freshness rule for the index refresh or the llm-client cutover. The minor items are stale wording, a missing O10, an uncited decision log and undefined terms, and several refutations narrow a major finding to a smaller gap rather than removing it.

## 2. Blockers

### BL-1. The caller chooses where a stored key is sent
- Lenses and ids: design F01 (blocker); zoom-out F1 (blocker).
- Problem: §4.5 has the scanner send base URL, route and key_ref with every call. llm-client then resolves the key by key_ref and sends it to that base URL. Nothing binds a key_ref to one host, and no caller authentication is stated for POST /v1/chat. The network is shared (docker-compose.yml, one project network), so any container on it can make llm-client send a saved provider key to an arbitrary host. The attacker does not get the key directly, because llm-client is the deputy that fetches it. §4.6 also lets the user add any provider by URL.
- Fix: llm-client keeps a registry of provider id, base URL and allowed key_ref, loaded from a store the scanner cannot write to. The request carries only a provider or key_ref name. Give llm-client its own service token and require it on POST /v1/chat. Add a test that a foreign base URL is refused before any secret is fetched.

### BL-2. The native Anthropic route has no class, request mapping or adapter
- Lenses and ids: comprehension CMP-01 (blocker); design F05 (major); zoom-out F3 (major); structural F12 (major).
- Problem: D9 and §4.5 define two provider classes, ollama and openai_compat, and put Anthropic in openai_compat. §4.6 and O9 add a native Messages route (POST /v1/messages, x-api-key, anthropic-version). That route has no class, no request mapping (system prompt, required max_tokens) and no response mapping, and T4 names no adapter file. §4.5 also lacks the model-list call (§4.6) and the one-call test (O15); its endpoint list has only /v1/chat and /healthz. AI_PROVIDER_NAME and AI_PROVIDER_ROUTE both decide the route, and the primary and secondary labels in O9 have no effect once O11 says a setting picks the route. A user-added provider has no rule for choosing a class, and nothing says what happens when a provider fits none.
- Fix: add a third class (for example anthropic_native) to D9 and §4.5, with request and response mapping. Add its adapter and tests to T4. Add the model-list and test endpoints with request and response shapes. State how a user-added provider picks its class and what happens when none fits. Remove the primary and secondary labels or give them an effect. Alternatively, take the native route out of this design until it is approved.

### BL-3. The provider and settings store has no schema, owner, migration, grants or seed loader
- Lenses and ids: comprehension CMP-02 (blocker); readiness IR-01 (blocker); readiness IR-21 (minor); design F06 (major); design F10 (major); structural F10 (major); zoom-out F5 (major); zoom-out F6 (major).
- Problem: §4.5 and §4.6 put provider entries, saved models, the route and the active provider in the database. No table, column or migration is named. D12 assigns 049 to 052 to other work and does not mention a provider table. Migration 053 is fund_daily (collector-split-spec-requests.md line 19), and the next free number on disk is 054, to be re-checked when written. llm-client has no database access, so the seed file config/llm_providers.json, said to be "loaded into the database on first start", has no named loader, trigger or repeatability rule. The grants are not stated: the scanner needs SELECT and the API needs write access. The design does not name the component that writes call records. The settings page, the Fastify routes, the model picker and the seed loader have no task in §7. The existing encrypted store app_secret (migration 045) is not mentioned.
- Fix: add one migration task with its down file. Use the next free number from the split owner (054 at time of writing). Name each table, its columns and the grants for the scanner role and the API role. Name the seed loader, its trigger, and an insert-if-missing rule. Name the component that writes call records. Add tasks with acceptance commands for the settings API, the UI picker and the seed load, or mark them out of scope.

### BL-4. Upgrade stops every enrich and conclude run until a model is picked
- Lenses and ids: readiness IR-02 (blocker); codebase OBS-15 (minor).
- Problem: §4.6 says that if no model is picked, the first run stops and the app shows a notification. AI_MODEL_NAME starts blank (§4.6 line 125). The current default model is qwen3:8b (scanner/llm.py line 65). No §7 task touches the settings page or seeds the current model. The stopped run writes no status, so the notification and the run record can disagree.
- Fix: before T5 is merged, either add a migration that saves the current Ollama provider and model as the active setting, or let the run fall back to the current env value for one release with a logged warning. Add the settings-page task and make it a prerequisite of T5. Record the stop as a failed run with a model_not_set status.

### BL-5. Name-first and ISIN-first matching contradict each other
- Lenses and ids: structural F01 (blocker); design F16 (major); design F17 (major); comprehension CMP-03 (major); readiness IR-18 (major).
- Problem: spec §3.2 (decided 2026-11-12) says the master is keyed by ISIN and that name lookup for events runs only after the master match. Design D3 and §4.2 rule A match events by name first and fill the ISIN from the matched pair. Events carry no ISIN (home_events.py sets isin to None in _rss_item), so the spec's order cannot run for events. Design O2 records the user's BSE rule as "exact name match against the master, then ISIN", the reverse of spec §3.2, and the spec's decision log does not contain that wording. The design never cites spec §3.2 or says it is superseded. The spec's own events path (§6 line 556 and §4.3) is also name-first, so the spec disagrees with itself.
- Fix: write the user's answer once, quoted with its date. If name-first is correct, amend spec §3.2 and align §4.2 and O2 with it. If ISIN-first is the decision, rule A cannot run for events and §4.2 needs a new design. Do not approve until this is settled.

## 3. Major

### M-01. llm-client's own access to the secrets API is not specified
- Lenses and ids: design F02; readiness IR-11; structural F13.
- Problem: §4.5 says keys are read from the secrets API "the collector pattern". In code the client sends a bearer token read from a file. The UI endpoint (ui/app/internal_secrets.py) accepts one token, maps it to "collector", and allows only one key name (SERVICE_ALLOWED). llm-client would be refused today. T4 names no token file, no compose mount and no change to the secrets API. The collector service in docker-compose.yml sets SECRETS_API_URL and SERVICE_TOKEN_FILE.
- Fix: specify llm-client's token file, compose mount and SERVICE_TOKEN_FILE. Decide whether it gets its own token or shares the collector token. Extend the internal endpoint's accepted tokens and key-name list to match. Add these files to T4 and its acceptance check, and name the missing-token message.

### M-02. No per-provider approval before scanner text is sent
- Lenses and ids: design F03.
- Problem: O7 approves hosted providers on the condition that each one is confirmed before it is enabled. §4.6 lets the user add any provider by URL. The only gate in §4.5 is that a cloud provider with no saved key does not run, which is a key check, not an approval. O8 relies on each provider having its own approval.
- Fix: add a per-provider flag, "approved to receive scanner text", default off and set only by an explicit confirmation in the UI that names the provider. llm-client refuses calls to unapproved providers. Keep the flag in the provider table (see BL-3).

### M-03. Three answers for where provider configuration lives
- Lenses and ids: design F04 (major); structural F09 (major); readiness IR-15 (major); zoom-out F4 (major); design F30 (minor).
- Problem: §4.6 says AI_PROVIDER_NAME selects the active block in config/llm_providers.json. O17 says that file is not read at run time and the database holds the live list. §4.5 says the database is the runtime source. D10 puts the provider block, including the model, in the llm-client config. AI_PROVIDER_URL "holds the base of the active provider", but O6 leaves open whether it overrides base_url in the JSON block, and its store is never named. A base URL then has three homes: AI_PROVIDER_URL, the block's base_url and the per-request value. AI_MODEL_NAME is called "the name the backend reads" yet is saved in the database.
- Fix: make the database the only runtime source for provider, route, URL and model. Keep env names only for LOCAL_LLM_URL. Decide the AI_PROVIDER_URL override and close O6. For each setting, state one store, one writer, one reader, and the default used when the row is missing.

### M-04. The Decided table still states superseded rules
- Lenses and ids: comprehension CMP-13 (major); structural F08 (major); design F27 (minor).
- Problem: Section 2 is headed "Decided", but D9 (two classes, Anthropic only as openai_compat), D10 (model in the llm-client config block) and D11 (LLM_PROVIDER) were replaced by §4.6 and O9, O12 and O17. §4.6 states the replacement in prose, but nothing in the table marks it. A builder working from §2 gets the old design. For D11 only the name changed; D9 and D10 are stale in substance.
- Fix: mark D9, D10 and D11 as superseded and point to the replacing answer, or rewrite each row to the final rule.

### M-05. The name-resolution task (spec T4f) is missing, and its named tests are not given
- Lenses and ids: design F08 (major); zoom-out F11 (major); comprehension CMP-09 (major); structural F27 (minor).
- Problem: the design is titled T4f, but §7 has no name-resolution task. Spec §9 T4f (line 630) requires named tests for §4.3 (exact match after normalisation; ambiguous and unmatched rejected as universe), fixed by this brainstorm before any dispatch. None are named. The 111 matched, 0 ambiguous, 31 unmatched result (§4.2) is pinned by no test. Spec §6 (line 556) names load_events_name_index, which does not exist in the code; the code uses load_index_for_source and fill_from_name. The name-rule tests now exist in tests/test_company_reference.py and tests/test_home_events_pure.py, so the gap is the 142-item result and the missing task row, not the rules.
- Fix: add a name-resolution task row with its tests named: exact match after normalise_name, ambiguous and unmatched rejected as universe, and a test that asserts 111 matched, 0 ambiguous and 31 unmatched on the 142-item fixtures. Decide the function name and update either the spec or the design. Name the index that feeds by_name, and pass universe as well.

### M-06. Design task IDs collide with spec task IDs
- Lenses and ids: design F09 (major); structural F14 (major); comprehension CMP-19 (minor); readiness IR-25 (minor).
- Problem: the design's T1 to T7 (six indices, precedence, membership, llm-client, call sites, tests, documents) reuse spec labels for different work. Spec T1 is the home_filings registration, T4f is name resolution, T6 is post_events and T7 is the parsers. The design also cites "filings T9" in prose without a mapping. Its tool-call limits (30, 40, 15) differ from the spec default of 25 and do not say whether they replace it.
- Fix: rename the design's tasks (for example DT1 to DT7) and add a mapping to spec IDs in §7. State whether the design's tool-call limits replace the spec default. If the title keeps the T4f label, make clear it refers to the spec task.

### M-07. The NSE-wins rule has no production caller and leaves some conflicts open
- Lenses and ids: design F10 (major); zoom-out F7 (major); comprehension CMP-04 (major); readiness IR-17 (major); structural F06 (major); structural F07 (minor); structural F25 (minor).
- Problem: D6 and O1 say NSE wins and T2 changes build_index. load_index, which reads both sources, has no caller outside tests. load_index_for_source has no production caller either, since the event wiring is deferred to T9 (spec line 379). The design says Upstox rows decide no event match today (§4.1), so T2 changes no runtime result, and §3 wrongly says load_index_for_source is "used for the event lookup". §4.3 covers only an ISIN present in both sources. build_index also drops a symbol that maps to two ISINs, so a symbol with an NSE ISIN and a different Upstox ISIN loses both rows, including the NSE row. Name conflicts are also dropped.
- Fix: name the production consumer, which is the T9 wiring, or defer T2. Say that T2 has no run-time effect until then. Add a symbol-level precedence rule: an NSE symbol and its ISIN are never removed by an Upstox row. Add tests for the Upstox-only collision and for a symbol shared across sources. Change "used for the event lookup" to "intended for the event lookup, not yet called".

### M-08. Index downloads: URL shape, pacing and content check are not carried over
- Lenses and ids: design F11 (major); readiness IR-07 (major); structural F16 (major); codebase OBS-05 (major).
- Problem: §4.4 says each index takes "its primary and fallback CSV URL" from scripts/fetch_index_constituents.py. That script has one base per source, up to three filename variants per index (MAX_VARIANTS = 3), a two-second pause and an HTML and header check. SCAN_INDEXES holds one two-URL pair per index, and fetch_index_bytes accepts any 200 response. An HTML page with status 200 on the primary host therefore ends the fetch without trying the fallback, and nothing paces the six requests. Failures keep only the exception class name, so a 403 and a 404 both read "HTTPError", and the master download has no stage label.
- Fix: write the six entries as lists of candidate URLs. State which filename is used. Port the content check and the pacing into fetch_index_bytes. Record the status code and host, without the query string, for each source tried. Label each stage in errors. Add tests for a 200 HTML response and for a 404 on the first filename.

### M-09. Six more index downloads can block the company master refresh
- Lenses and ids: design F12 (major); zoom-out F13 (major); structural F17 (major); readiness IR-09 (major).
- Problem: run_refresh fetches and parses every index before any write, and the company_reference refresh and the index replacement share one transaction. If one index fails from both sources, the whole run raises and nothing is written, including nse_csv and upstox_master. §4.4 states no failure policy and no availability cost. The keep-last-month behaviour appears only in a code docstring. The coupling already exists for the one index today, so the change raises the exposure from one index to six.
- Fix: choose and write down one policy. Either refresh each index and the master independently with last good data kept per index, or keep all-or-nothing and name the alert that fires. Add a test in which one index fails and check the master refresh result.

### M-10. The 751 and 752 counts have not been reconciled
- Lenses and ids: design F14 (major); comprehension CMP-07 (major); structural F05 (major). Zoom-out F9 (major) was refuted; see the appendix.
- Problem: §4.4 and O5 call the spec's 751 "an older figure" and give 752 as the current NIFTY TOTAL MARKET row count. Spec §4.3 (line 355) defines 751 as NIFTY Total Market plus a holdings list. The loader stores only NIFTY TOTAL MARKET, and no code path writes a holdings list into index_constituents. The 752 count is the index_constituents count the user read from the database on 2026-11-12, and 754 is the first load. A refuted finding (zoom-out F9, see the appendix) found that the 751 and 752 figures come from two copies of the same file: the main-checkout copy gives 751 after the DUMMY filter, and the worktree copy gives 752. That supports the "older" label in O5. The holdings wording in spec §4.3 is still unsupported, and the composition question is open.
- Fix: show the query and row count for NIFTY TOTAL MARKET. Explain the holdings part of the 751 definition, or state that it no longer applies. Move the 751 point in O5 from settled to open. Correct spec §4.3 once the composition is checked.

### M-11. The settled one-row-per-ISIN rule (O3) is not in the code and has no task
- Lenses and ids: design F15 (major); zoom-out F8 (major); comprehension CMP-05 (major, unverified, see section 5); readiness IR-03 (major); structural F02 (major).
- Problem: O3 says "Settled: option A, one row per ISIN, using the EQ row." equity_list_rows keys rows on (symbol, ISIN) and keeps the first row read. SERIES is stored but never compared. An ISIN with an EQ row and a BE row under different symbols keeps both, and build_index then drops the ISIN as a conflict. Under the same symbol, whichever row comes first in the file survives. No §7 task adds the rule; T2 covers only NSE precedence. The existing test asserts keep-first. §4.1 says nse_csv holds "all series".
- Fix: add the EQ-preference step to equity_list_rows as a task, with tests for both file orders including 21STCENMGM. State the expected nse_csv row count after the change and correct §4.1. Alternatively, change O3 to describe what the code does. Check whether the BE row shares its symbol with the EQ row; the source file is not in the repo, so this could not be checked here.

### M-12. O5 says the parser keeps every row, but the parser drops some
- Lenses and ids: structural F03 (major); comprehension CMP-06 (major); readiness IR-05 (minor); design F23 (minor).
- Problem: O5 says the parser keeps all 2,635 rows (checked offline), that the write path does not dedupe, and that the 2-row gap is "probably" a snapshot difference, and then "not a bug". The parser skips rows with a blank symbol, ISIN or name, and keeps only the first row per (symbol, ISIN). The 2,635 claim holds only if the offline drop counts were zero, and those counts are not recorded. The two named symbols are not shown absent from the file. The listing-date explanation is a guess that no record confirms. The parser dedupe is also load-bearing, because the insert has no conflict clause and the primary key is (source, symbol, isin).
- Fix: record per-rule counts from an offline run (blank symbol, blank ISIN, blank name, repeated pair). Correct the O5 wording. Re-download the file and diff the two symbols, or mark the gap as accepted but unexplained, with the next refresh named as the check.

### M-13. The company-name source for each feed is not stated
- Lenses and ids: design F18 (major); structural F18 (major).
- Problem: §4.2 step 1 normalises "the event's company name" without naming the field. The whole squashed title is the company for every feed except Corporate_action, which takes the text before " - Ex-Date:". So for seven feeds the match depends on whether the title equals the master name. The 111-of-142 figure cannot be reproduced from the design because no method is given.
- Fix: state the company source for each feed in §4.2, with the Ex-Date rule for Corporate_action (spec line 351). Confirm the 111 figure used the same field. Add a per-feed test that checks the company value.

### M-14. Key storage, replacement and the key_ref naming rule
- Lenses and ids: design F19 (major); readiness IR-10 (major); zoom-out F18 (minor).
- Problem: §4.5 says the key is "saved to the encrypted database" and never names the table, the write endpoint, or the replace and delete rules. The existing store is app_secret (migration 045): encrypted, decrypted only by the API, with no DELETE grant. Its name rule is lowercase letters, digits and underscores, starting with a letter. A key_ref such as "openrouter-key" would be rejected. §4.5 also says the key is "entered in the app's settings page", but the UI returns HTTP 410 for browser saves and the secrets design keeps v1 as a command-line tool.
- Fix: name app_secret and the API endpoints for save, test and replace. State the key_ref rule in the design. Say the UI never reads the value back. The no-DELETE grant already sets the deletion rule. Reconcile the settings-page wording with the browser-save restriction.

### M-15. strict_check: required fields, error text and the Anthropic test gate
- Lenses and ids: design F20 (major); comprehension CMP-20 (minor); codebase OBS-16 (minor).
- Problem: §4.5 says strict_check fails a call whose JSON reply lacks a required field, but does not list the required fields per call kind. The kinds and their schemas are in scanner/llm.py (SCHEMAS). The error does not name the missing field, and the design does not say what is logged; full replies contain scanner text. §4.5 says the Anthropic compatibility layer must be tested before production use, and §4.6 makes both Anthropic routes options, yet T4 has no test for either. The design also does not say whether a null value in a required key counts as missing.
- Fix: list the required fields per kind, citing SCHEMAS in scanner/llm.py. Define the failure as strict_check_missing_field with the field name. Log the first 200 characters only in debug mode. Add a T4 acceptance step that runs both Anthropic routes against a recorded fixture before either is used in production.

### M-16. The monthly refresh has no owner, schedule or reminder
- Lenses and ids: design F22 (major); codebase OBS-03 (major).
- Problem: D13 says the next refresh is due 2026-12-12. The refresh job runs only when someone starts it by hand. Nothing in docker-compose.yml, the collector registry or start.ps1 runs it, and no owner is named. No code emits a reminder. No run-time check reads the age of company_reference or index_constituents rows. A missed refresh leaves the event matcher on old data, and new listings show up only as universe rejections (see M-17).
- Fix: name the owner and the runner. Add a scheduled job with visible status, or a run-start check that warns when the data is older than a stated number of days. Test the threshold.

### M-17. Rejections and conflicts are dropped without a cause or a log
- Lenses and ids: codebase OBS-01 (major); codebase OBS-02 (major).
- Problem: filter_items counts every event name that does not resolve under one counter called "universe". The three causes (no match, ambiguous name, supplied ISIN that disagrees) all land there, and the run message says only "universe=N". The 31 rows and 23 names come from a one-off read-only measurement with no stored record. Index.conflicts is computed by build_index but never read by production code, so conflicts reach no log or table. The ISIN-mismatch branch is unreachable today because the feed parsers set isin to None, so it is a latent cause.
- Fix: return counts by cause (no_match, ambiguous, isin_mismatch) from filter_items and fill_from_name, and add them to the run message. Record the top unmatched normalised names per run, capped, in the run record. Log the conflict count and a capped list of conflict keys on every run. Add a test that a conflict reaches the log.

### M-18. No refresh run record is kept
- Lenses and ids: codebase OBS-04 (major).
- Problem: run_refresh returns counts to its caller and the job prints one line on success. A failure leaves only a traceback. Conflicts exist only in memory. Counts, as-of date, duration, failing stage and conflict count are not stored for any run. The O5 analysis had to diff the database against a local file to recover the timing. Each refresh deletes the source's previous rows, so earlier counts are lost.
- Fix: write one row per refresh attempt with start and end time, as-of date, counts per source and per index, conflict count, status, failing stage and exception class. The table needs a migration number at approval. Do not change the D12 numbers.

### M-19. The llm-client request and response contract is incomplete
- Lenses and ids: readiness IR-14 (major); codebase OBS-07 (major).
- Problem: §4.5 names the request as the OpenAI chat shape and gives no field list. The current Ollama path sends num_ctx, format, think and temperature, and the OpenAI branch sends max_tokens, response_format and json_schema (scanner/llm.py). The design says the Ollama options must be kept, but names no field for them. No response field is named for token counts, provider HTTP status or error class. Token extraction covers only the Ollama and OpenAI usage fields, with no mapping for the Anthropic native route. Elapsed time and the ok flag are measured by the scanner, so they are not part of the gap.
- Fix: define the request fields (route, class, provider, model, messages, options including num_ctx, format or schema, max_tokens, run_id). Define the response fields (content, provider, route, model, HTTP status, input and output tokens normalised per class with a mapping table, elapsed milliseconds, error class). Add one test per class that maps a sample usage block. Add a test that the num_ctx sent to Ollama is unchanged.

### M-20. Error handling: no taxonomy, no status pass-through, no redaction
- Lenses and ids: codebase OBS-08 (major); codebase OBS-10 (major); codebase OBS-11 (refuted as major; only a preventive gap remains, see the appendix).
- Problem: §4.5 defines one key failure, "key is missing". It does not separate the secrets API being unreachable, the secrets API returning an HTTP error, the provider rejecting the key (401 or 403), a provider timeout, and a strict_check failure. The scanner's existing secrets client already separates the first two. The scanner's context-overflow retry (scanner/llm.py) needs the provider to return HTTP 400 with "context" in the body. If llm-client returns a generic error, the retry stops silently. The design has no redaction rule for error text. The repo has redact_error (home_events.py), but the design does not require it. Provider response bodies are not passed to LLMResult.error today, but exception strings can carry URLs with query strings, and the consumer stores the value in an extraction document.
- Fix: reuse the messages in fetch_secret. Define one error code per case: model_not_set, key_missing, secrets_unavailable (with HTTP status where there is one), provider_http_<status>, provider_timeout, strict_check_missing_field:<name>, non_json_reply. Require llm-client to pass the provider status and a redacted copy of the error text. Add a T5 test that a 400 with "context" triggers exactly one retry at half length. Apply one shared redaction function to llm-client errors and to LLMResult.error. Add a test that a key-shaped string in an error text is removed. No code or message may contain a key value.

### M-21. Endpoints: the healthz contents, the list and test calls, and the list data path
- Lenses and ids: codebase OBS-09 (major); structural F11 (major); readiness IR-24 (minor).
- Problem: §4.5 names GET /healthz with no response fields and does not say whether compose uses it as the health check. scanner/llm.py health() probes /api/tags or /v1/models. After the cutover, health() would call llm-client, which exposes neither, so the probe would fail on every route unless the design says what it probes. §4.6 gives the list path as "provider list, then llm-client, then Fastify, then the UI" but does not say who supplies the base URL and key_ref on a list call. A model-list call is not a scanner run, so the per-run contract does not cover it. The O15 test call is not in the endpoint list.
- Fix: define the healthz response: active provider name, class, route, base host, model set yes or no, key resolved yes or no, secrets API reachable yes or no, time of last successful call. Say what compose's health check targets. State that health() probes healthz only. State that Fastify reads the saved provider block and passes base URL, route and key_ref to llm-client on each list call, using the §4.5 contract written out.

### M-22. Call records: route and base host are not recorded, and the writer is unclear
- Lenses and ids: codebase OBS-12 (major); comprehension CMP-24 (minor).
- Problem: §4.5 says each result records the provider name and model name. The route and the base URL host are not recorded, although the scanner sends both. Current call records (the llm_calls table) store the model only. The text says calls are recorded "the way conclude records them today, with RUN_ID", but does not name the table, the columns or the writer. The writer is the scanner process (metrics.record_call), not llm-client, which has no database access. The llm_calls stage check allows only "extract" and "conclude", so a new route needs a schema change that no task covers. record_call is a silent no-op when RUN_ID is unset, and nothing warns.
- Fix: record provider name, route, base URL host (no path or query) and model with every call and run record. Name the scanner as the writer and name the table and columns. Add a migration for the provider column and the stage change. Add a run-start warning when RUN_ID is unset for runs that must record calls. Add a test that one cloud call writes exactly one record.

### M-23. The acceptance gate is a unit-test command only, with no runtime checks
- Lenses and ids: codebase OBS-13 (major); structural F15 (major); readiness IR-19 (major).
- Problem: §7 gives the same unittest command as the acceptance for every task. The design names no test file for T3, T4 or T5, and only a directory or existing files for T1 and T6. No task names test cases. The named T4f tests (spec line 630) and a healthz test are absent. Tasks whose behaviour only a live run or a provider can show (the six-index refresh, the llm-client service, the call sites) have no runtime check. The Anthropic compatibility test in §4.5 is not a task. A passing whole-suite run does not prove the new code was exercised.
- Fix: name the new test files and test names for each task. Add runtime checks: T1 gives one refresh run record with six non-zero index counts; T4 runs docker compose config, then GET /healthz, then one test call per enabled provider; T5 writes call records from one scanner run with RUN_ID set. Name the Anthropic compatibility test as a task. Map the T4f named tests from spec line 630.

### M-24. The index membership reader, cutover and zero-row rule
- Lenses and ids: zoom-out F10 (major); comprehension CMP-10 (major); readiness IR-08 (major); structural F20 (minor).
- Problem: T3 plans to make constituent_membership read the database, but a reader already exists. scanner/constituents.py load_constituents reads index_constituents by default and has at least five callers. constituent_membership.py is a writer: it reads CSV files and upserts constituent_membership rows. §4.4 and D7 say membership "is read from the database" without naming the transform (index_constituents rows into constituent_membership rows with an as-of date) or the retention rule. D7 calls the CSV path "an offline test path", but the --constituents option of the ATH scan is an operator path. There is no rollback for the cutover, no rule for an index with zero database rows (the reader raises RuntimeError, which the design should cite), and no freshness rule.
- Fix: reuse load_constituents or cr.load_index_constituents rather than add a third reader. State the transform and the retention rule. Do not deploy T3 until all six names have rows. Keep the CSV path for one release as a documented rollback, described as an operator path. State that a zero-row index raises rather than returning an empty membership, and add a freshness rule.

### M-25. The six index names are not listed and are spelled two ways
- Lenses and ids: zoom-out F12 (major, unverified, see section 5); comprehension CMP-11 (major); readiness IR-06 (major).
- Problem: §4.4 says the indices are stored "under their index names" and lists none. SCAN_INDEXES uses the uppercase key "NIFTY TOTAL MARKET". constituent_membership.py (SLUG_TO_INDEX) and the fetch script use title case, such as "Nifty 50" and "Nifty Bank". The database read matches the name exactly. The names therefore exist in three places with no shared list, and relative_strength.py depends on the title-case names. The design also gives no column mapping from index_constituents to the reader's output.
- Fix: put the six names and filenames in one module that the job, the script and constituent_membership.py all import. Choose one casing. List the six exact names in §4.4. Add a test that each name loads back by exact match and returns non-zero rows.

### M-26. The llm-client cutover has no rollback, no health gate and no failure rule
- Lenses and ids: readiness IR-13 (major).
- Problem: §4.5 says scanner call sites go to the client URL (line 88). No setting picks the direct or the client route, no rollback is written, and T5 depends only on T4, with no health check before merge. Nothing says what happens when llm-client is down. D8 forbids direct provider connections from the scanner, so a direct fallback would be a new decision, not a gap-filler.
- Fix: either add a setting for one release that picks the direct or the client route, or write a rollback (revert the T5 commit and remove the service). Require T4 to pass GET /healthz before T5 is merged. State that an llm-client failure fails the run with a named error and does not skip silently.

### M-27. The LOCAL_LLM_URL rename has no alias, and several files are missing from the task lists
- Lenses and ids: readiness IR-12 (major).
- Problem: O6 renames LLM_URL and CONCLUDE_URL to LOCAL_LLM_URL. It gives no alias and no cutover step for existing .env files. These files use the old names and are missing from T4 and T5: start.ps1 (LLM_URL, lines 28-29 and 63-64), README.md (lines 119 and 136), and the root conclude.py (CONCLUDE_URL, and the llm.health call at line 105). The §3 citation of "llm.health (line 105)" under scanner/conclude.py is wrong, because the call is in the root conclude.py. The design also gives no LOCAL_LLM_URL value for each service, and the scanner containers' values are set by compose and by start.ps1, not by env.template.
- Fix: add start.ps1, README.md and the root conclude.py to T4 or T5. Keep the old names as read-only aliases for one release, or add a cutover step for existing .env files. Correct the §3 citation. List the LOCAL_LLM_URL value for each service in §4.5.

### M-28. Benchmarks and other call sites
- Lenses and ids: comprehension CMP-14 (major); design F25 (minor); comprehension CMP-21 (minor).
- Problem: O8 says benchmark runs use the active provider and take no provider argument, but the flags --url, --api and --model in bench_extract.py are not named as removed. bench_models.py starts a per-candidate vLLM container on 127.0.0.1:8003 and passes its own base URL. After the cutover, the active provider would override that URL silently, so the benchmark would measure the wrong model with no error. The design never mentions vLLM. extractcheck.py makes no LLM call; it imports only AGREE_TOLERANCE_PCT, yet it is listed as a call site (§3) and in T5. bench_models.py is an indirect caller through conclude, not only a config builder. The line "enrich reads LLM_URL" is wrong: enrich.py takes an --llm-url argument, and start.ps1 passes it.
- Fix: state what happens to the three flags. Decide whether the vLLM path goes through llm-client or stays a separate offline tool. Remove extractcheck.py from the call-site list, or keep it only as a dependent of AGREE_TOLERANCE_PCT. Correct the enrich and LLM_URL wording.

### M-29. The decision source has no path
- Lenses and ids: comprehension CMP-15 (major); structural F26 (minor).
- Problem: line 5 cites "the brainstorm decision log (Decisions 1 to 14 and Q1 to Q5)" with no path or link. No file under docs/ holds those decision numbers. Several rows (D1, D2, D8 to D11) cite only numbers, and several O items cite "Answer (2026-11-12)" with no user words. A reader outside the session cannot check the basis. Some rows do quote the user (D4 to D7, D12).
- Fix: give the path of the decision log, or quote each decision inline. Mark which items are the user's words and which are the design's choice, as O15 and O17 already do.

### M-30. Normalisation: the rule is incomplete and the function is not defined in the design
- Lenses and ids: comprehension CMP-08 (major); design F26 (minor); readiness IR-23 (minor); structural F19 (minor).
- Problem: §4.2 step 1 says "normalise with normalise_name" and never defines it. D1 lists only the punctuation rule. The code (scanner/company_reference.py) also uppercases, maps & to AND, maps LIMITED and LTD to LTD, collapses runs of spaces, and maps a missing name to an empty string. The spec (line 360) lists the full rule set.
- Fix: define normalise_name in §4.2 with every step and the missing-name case. Link company_reference.py lines 26 to 31 and spec line 360. Correct D1 to match.

## 4. Minor

### m-01. The model-list line marks unconfirmed items as verified
- Lenses and ids: design F29; comprehension CMP-22; zoom-out F17.
- Problem: §4.6 says the model-list endpoints were "Verified 2026-11-12", then lists unconfirmed items in the same bullet: OpenAI paging (its official page returned 403), the Gemini auth header (not checked), the Anthropic anthropic-version value, and the Together AI host still to check. No source link is given per endpoint. O14's answer "yes" is the design's own reading, which the design says is its own. Gemini appears in the list but has no provider block, and Groq, Mistral and Together AI have none either.
- Fix: split the bullet into a verified list and an unverified list, each with a source link and date. Treat an unconfirmed item as blocking for its provider until it is checked. Remove providers without a block, or add them to scope. Ask the user to confirm the O14 reading.

### m-02. Open-point numbering and stale headings
- Lenses and ids: design F24; zoom-out F16; comprehension CMP-18; structural F22.
- Problem: §5 runs from O9 to O11 with no O10 and no note of removal. O9 says the meaning of "secondary" is still open (O11), but O11 answers it. O6 mixes a settled answer with an open question. The §5 heading says every point needs the user's answer before approval, but most entries are settled.
- Fix: renumber, or record O10 as withdrawn. Update the pointer in O9. Split O6 into the settled names and the open override question. Retitle §5.

### m-03. The ISIN-agreement rule is in the spec and the code, not in the design
- Lenses and ids: comprehension CMP-17; structural F24.
- Problem: spec line 362 says a resolved item is accepted only if its ISIN agrees with any ISIN it carries. fill_from_name enforces this. filter_items keeps a feed-supplied ISIN without checking it. The design's §4.2 steps 3 and 4 do not mention the rule or where it lives. This is latent today, because the feeds set ISIN to None.
- Fix: state the rule in §4.2 step 3 and say it lives in fill_from_name. Add a test, or a check in filter_items, for a feed-supplied ISIN.

### m-04. Unmatched names: the cause is not established
- Lenses and ids: zoom-out F14; readiness IR-26.
- Problem: D4 rejects the 31 rows and 23 distinct names with no caveat. The handoff (company-reference-handoff.md, item 6) says the cause is not established, the names must not be called delisted, and each must be checked against the NSE and Upstox lists. The design does not carry that caveat or record whether the check was done. The handoff's 23 names and the design's 23 names are not shown to be the same set.
- Fix: add the caveat and a reference to handoff item 6 to D4. State that the rejection is a decision, not a finding that the names are unlisted. Record whether the per-name check was done. State whether the two sets of 23 match.

### m-05. Labels reused in code comments
- Lenses and ids: structural F21.
- Problem: company_reference.py line 117 says "decision O1: union of both sources", which O1 supersedes. Line 223 says "decision O2" for the loader role, but design O2 is about BSE. company_reference_job.py line 7 says "decision O3" for the job rule, but design O3 is about duplicate ISIN rows.
- Fix: update the comment at line 117 with the T2 change. Replace the other labels with stable references, such as handoff item numbers.

### m-06. Terms used without a definition
- Lenses and ids: comprehension CMP-23.
- Problem: "upstox_master", "Upstox", "EQUITY_L.csv", "loader role", "RUN_ID", "secrets API", "collector pattern", "Fastify" and "six lenses plus the synthesizer" appear without a definition or link. "Universe" is defined in spec §4.3 but not linked. The RUN_ID pointer needs care: the variable is read in scanner/metrics.py, and conclude.py has no RUN_ID text.
- Fix: add a short glossary, or link each term to its source: company_reference_job.py lines 1 to 15 for the loader role, spec §4.3 for universe, scanner/service_client.py for the secrets API, scanner/metrics.py for RUN_ID.

## 5. Unverified findings

Three kept findings could not be checked. For each one, the verifier failed to return a valid verdict after five attempts, so no evidence was gathered. They were neither confirmed nor refuted at review time. See the re-verification note at the end of this section.

- zoom-out F12 (major): the six index names and CSV URLs are copied in three places, and the filename rule ("primary and fallback") is undefined. Feeds M-25. **Status (2026-11-12): refuted as stated; a narrower point stands.** The six names and their CSV filenames are in one file, `scripts/fetch_index_constituents.py` lines 26 to 51. `scanner/constituent_membership.py` repeats the names only, and `scanner/company_reference_job.py` holds URLs for one index. The filename rule is defined in code (`scripts/fetch_index_constituents.py` lines 19 to 23 and 82 to 85). What stands: the six names are duplicated across two files in two casings, and design section 4.4 does not say how the script's three filename variants map onto the two-URL tuple in `SCAN_INDEXES`. M-25 rests mainly on the casing point.
- comprehension CMP-05 (major): O3 is marked settled as one row per ISIN, but the code keeps one row per symbol and ISIN pair. Feeds M-11. **Status (2026-11-12): unverifiable.** The code facts check out: the key is (symbol, ISIN) (`db/migrations/047_company_reference.sql` line 19), and the first row per pair wins with no preference for the EQ row (`scanner/company_reference.py` line 85). Whether the BE row for an ISIN shares a symbol with its EQ row cannot be measured, because `EQUITY_L.csv` is not in the repository. If the symbols match, the table keeps one row per ISIN, but it is the first row in file order, not the EQ row. If they differ, `build_index` drops both rows as an ISIN conflict, and the claim is confirmed. In both cases O3's wording does not match the code. M-11 stays open until the file is available.
- readiness IR-16 (major): it is not stated whether the AI_* settings are environment variables or database keys. Not merged into any entry; related to M-03. **Status (2026-11-12): confirmed.** `AI_PROVIDER_URL` has no named store: design section 4.6 (Base URL) does not say whether it is a database key or an environment value, and open point O6 leaves its relation to the base URL in `config/llm_providers.json` open. `AI_MODEL_NAME` is called "the key the backend reads" with its value "from the saved settings" (section 4.6), without naming the store. The provider name and route are implied to be database values, which the design does not state outright, so that part is slightly overstated. No `AI_` setting appears in `scanner/` or `env.template`.

**Re-verification note (2026-11-12).** The three findings above were re-verified in this run, and each finding line shows its status and reason. zoom-out F12: refuted as stated; a narrower point stands. comprehension CMP-05: unverifiable, because the deciding file, `EQUITY_L.csv`, is not in the repository. readiness IR-16: confirmed. Design line numbers cited in these notes refer to the design file before the 2026-11-12 decision edits; section numbers are given where possible.

Several confirmed findings rely on checks that could not be run in this review. These are open checks, not unverified findings:
- The 2,635-row count, the ESFL and SUVID-RE gap, the 21STCENMGM duplicate, and whether the BE row shares a symbol with the EQ row (EQUITY_L.csv is not in the repository; M-11, M-12).
- The 751, 752 and 754 queries and the holdings composition (M-10).
- The 111, 0 and 31 method (M-05, M-13).
- The Q1 to Q5 and Decision 1 to 14 log (M-29).
- The provider documentation (m-01). No external source was fetched.

## 6. Lens coverage

Lenses with no output: none.

- egm-design: 28 kept (28 confirmed), 3 refuted (31 total).
- egm-codebase-details: 14 kept (14 confirmed), 2 refuted (16 total).
- egm-zoom-out: 15 kept (14 confirmed, 1 unverifiable), 3 refuted (18 total).
- egm-comprehension: 23 kept (22 confirmed, 1 unverifiable), 1 refuted (24 total).
- egm-implementation-readiness: 25 kept (24 confirmed, 1 unverifiable), 1 refuted (26 total).
- egm-structural: 27 kept (27 confirmed), 1 refuted (28 total).
- All lenses: 132 kept (129 confirmed, 3 unverifiable), 11 refuted, 143 total.

## 7. Appendix: refuted findings

The verifier refuted eleven findings. Each entry gives the id, the lens, the severity as raised and the verifier's reason. Where a smaller point still stands, that point is noted and mapped to the merged entry that covers it.

- **design F07** (egm-design, major). Refuted: the claim that no task names its tests is too broad. T2 names tests/test_company_reference.py and T6 names four existing test files. Still standing: T3, T4 and T5 name no test file, T1 names only a directory, no task names test cases, and the strict_check failure, the missing-key refusal and route selection have no named test. Covered by M-23.
- **design F13** (egm-design, major). Refuted: index_constituents does have an as_of column (migration 048, line 16), and each refresh replaces one index's rows. Still standing: no written transform copies index_constituents rows into constituent_membership with an as-of date, and no retention rule is stated. Covered by M-24.
- **design F21** (egm-design, major). Refuted as a live fault: the 127.0.0.1 values in env.template are not read by containers today, because compose sets CONCLUDE_URL to host.docker.internal and enrich's URL comes from start.ps1. It is a latent trap. Still standing: no per-service LOCAL_LLM_URL value is given. Covered by M-27.
- **codebase OBS-06** (egm-codebase-details, major). Refuted: the design does not route the call record to llm-client. The scanner writes the record (conclude calls metrics.record_call). Still standing: metrics.record_call is a silent no-op when RUN_ID is unset, which is a pre-existing gap, and line 87 never names the scanner as the writer. Covered by M-22.
- **codebase OBS-11** (egm-codebase-details, major). Refuted as stated: provider error bodies do not reach LLMResult.error in the current code. The verifier calls the remaining gap preventive and not major. Covered by M-20, which now marks it that way.
- **zoom-out F2** (egm-zoom-out, major). Refuted: section 1, item 4 does list llm-client as covered, and scanner/llm.py has an OpenAI-shaped path (api="openai") that bench_extract.py and bench_models.py use. "About half the document" is overstated; the LLM-specific material is roughly a quarter of the 160 lines. Whether to split the design is a judgement call, not a defect.
- **zoom-out F9** (egm-zoom-out, major). Refuted: 751 and 752 are the same index under the same filter. The gap is a snapshot difference between two copies of the file, so the "older figure" explanation in O5 holds. The "plus holdings list" wording in spec §4.3 is unsupported, and that is a real documentation defect. Covered by M-10.
- **zoom-out F15** (egm-zoom-out, minor). Refuted: D12 does name a source ("Q4 ('i accept proposal')"). The path given in the finding does not exist. Citing docs/progress/collector-split-spec-requests.md, line 19, as well would be an optional improvement.
- **comprehension CMP-12** (egm-comprehension, major). Refuted as stated: §4.6 does place AI_MODEL_NAME and AI_PROVIDER_ROUTE in the database, and the design does not write them in environment-variable form. Still standing: the store for AI_PROVIDER_URL is unnamed, AI_PROVIDER_NAME is said to select a file that O17 says is not read at run time, and no defaults are given. Covered by M-03.
- **readiness IR-22** (egm-implementation-readiness, minor). Refuted: build_index records ambiguous names as "name:" entries in conflicts, so the 0 ambiguous figure can be derived from the output. Still standing: neither design §4.2 nor spec line 375 says how the figure was produced. Not merged into any entry; a minor wording point.
- **structural F23** (egm-structural, minor). Refuted: the must-not-change list is in the design at §6 (lines 129 to 135), and "OpneAI_API_URL" is a quoted superseded term, not a typo. Still standing: §6 does not name LLM_URL or CONCLUDE_URL, which are still live in docker-compose.yml and env.template. Covered by M-27.

Three further kept findings could not be checked (zoom-out F12, comprehension CMP-05, readiness IR-16). They are listed in section 5, not here.
