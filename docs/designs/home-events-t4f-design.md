# Home-events T4f: company key, index membership and the LLM client

Status: DRAFT for Goldfish review. Not approved. No task has been dispatched and no code has been changed for this design.
Date written: 2026-11-12.
Source of decisions: the brainstorm decision log (Decisions 1 to 14 and Q1 to Q5, all 2026-11-12). The user's words are quoted where they matter.

## 1. What this design covers

Home events (filings and news from NSE feeds) carry a company name and no symbol or ISIN. The scanner needs to attach a symbol and ISIN to each event, or reject it. This design sets:

1. How the company master table (`company_reference`) is built and which source wins.
2. How an event is matched to the master, and what happens when it does not match.
3. How index membership (`constituent_membership`) is loaded from the database.
4. A separate `llm-client` container that is the only route for every LLM call from the scanner.

It does not cover the wiring of the events runner (`run_cycle` with the name lookup). That is filings task T9 in the spec.

## 2. Decided

| # | Decision | Source |
|---|---|---|
| D1 | Name normalisation replaces each of `.,'()-` with a space. No change to the code. | Q1, Decision 1 |
| D2 | NSE CSVs go into the database first. The monthly job loads `EQUITY_L.csv` into `nse_csv` and the Upstox master into `upstox_master`. | Decision 2 |
| D3 | Events are matched by company name against the master, using the NSE source only (`nse_csv`). Exactly one (symbol, ISIN) pair is a match. Zero or several pairs are rejected. Nothing is guessed. | Decisions 5, 14; `scanner/company_reference.py` `load_index_for_source` |
| D4 | Unmatched events are rejected (the 31 rows in the 142-item sample, 23 distinct names). No source is added for them. | Q3 ("drop those 23 names"), Decision 3, Decision 14 |
| D5 | The LLM fallback for event matching is dropped for now. It may return only if a master source covers these names. | Decision 14 ("agree") |
| D6 | When NSE and Upstox give different symbol text or name for the same ISIN, NSE wins. | Decision 6 ("nse") |
| D7 | The six indices are loaded into `index_constituents` by the monthly job, and `constituent_membership` is read from the database. The CSV chain is retired except for an offline test path. | Decision 4 ("yes") |
| D8 | Every LLM call from the scanner goes through `llm-client`. The scanner never connects to Ollama, OpenRouter, Anthropic or ChatGPT directly. | Decision 10 |
| D9 | `llm-client` has two provider classes: `ollama` and `openai_compat`. Anthropic, OpenRouter and ChatGPT are `openai_compat` with their own base URL, model and key. BL-2 adds a third class, `anthropic_native`. Superseded for key entry by BL-3; `docs/designs/secrets-and-roles.md` decision 9 amended 2026-11-12. | Decision 11 |
| D10 | Each provider is a named block in the `llm-client` config: class, base URL, model, key reference (the name in the encrypted DB, never the key), extra headers, `strict_check`. Superseded for key entry by BL-3; `docs/designs/secrets-and-roles.md` decision 9 amended 2026-11-12. | Decision 12 |
| D11 | One provider is active at a time, chosen by `LLM_PROVIDER`. No call site picks a provider. | Decision 13 |
| D12 | Migration numbers: 049 S2 `source_cooldown`, 050 S5a grants, 051 S8 filings cron, 052 filings registration. Reserved 049 to 052 as listed. The next free number is 054, since 053 is `fund_daily`. S2a takes the next free number when written. | Q4 ("i accept proposal") |
| D13 | Monthly refresh: the loader role's password is set and stored in a secret file. `POSTGRES_LOADER_PASSWORD_FILE` is set in `.env`. Next refresh due 2026-12-12. | Q5 |
| D15 | Call-site order (brainstorm question 2, user 2026-11-12: "agree as proposed in design"). Order: T1 six indices into the monthly job; then T2 NSE precedence (D6); then T3 constituent membership read from the database; then T4 llm-client; then T5 scanner call sites and T6 test updates; then T7 documents. | Q2 |

## 3. Facts checked in the code (2026-11-12)

- `scanner/company_reference.py` `build_index` (line 128): builds one index from the rows of both sources together. When one symbol or one ISIN has two different partners across the rows, it is recorded as a conflict and left out. It does NOT apply NSE precedence. D6 is not implemented yet.
- `scanner/company_reference.py` `load_index_for_source` (line 199): used for the event lookup with `nse_csv`. `fill_from_name` (line 166) fills symbol and ISIN only when the name resolves to exactly one pair.
- `scanner/company_reference_job.py` `SCAN_INDEXES` (line 36): holds one entry, NIFTY TOTAL MARKET. The six indices are not in it yet.
- `scanner/constituent_membership.py` still reads `data/constituents/nifty_*.csv` (six files). `scripts/fetch_index_constituents.py` downloads them.
- `docker-compose.yml`: `conclude` sets `CONCLUDE_URL: http://host.docker.internal:11434` (line 112). `enrich` reads `LLM_URL`. `env.template` lines 47 and 48 define both.
- LLM call sites: `scanner/llm.py` `extract()` (`requests.post` at line 461) and `health()`; `scanner/conclude.py` `requests.post` (line 558) and `llm.health` (line 105); `enrich.py`; `scanner/extractcheck.py`; `bench_models.py` (line 116); `bench_extract.py` (line 43); `docs/designs/concall-vl-extraction-plan.md` (line 14, planned).
- Secrets: `scanner/service_client.py` reads `SECRETS_API_URL` (line 39). Compose sets it for `collector` (`http://ui:8080`).
- Migrations: `db/migrations/` has 047, 048 and 053. 049 to 052 have no files yet.
- Events feeds carry no symbol and no ISIN. `scanner/home_events.py` `_rss_item` sets both to None.

## 4. Design

### 4.1 Master table

- `company_reference` holds rows from two sources: `nse_csv` (NSE equity list, all series) and `upstox_master`.
- The monthly refresh (`scanner/company_reference_job.py`) replaces each source in one transaction. It refuses the whole refresh if a source parses to zero rows (`EmptySourceError`, `refresh` in `scanner/company_reference.py`).
- Event lookup uses `nse_csv` only (D3). This means the Upstox rows do not decide any event match today.

### 4.2 Event matching (rule A)

NSE RSS items carry no ISIN, so they are matched name-first (no ISIN on items). BSE matching is ISIN-first: the rule was accepted on 2026-11-12. The BSE source was approved on 2026-11-12; see `docs/designs/home-events-t4f-blocker-recommendations.md`.

1. Normalise the event's company name with `normalise_name`.
2. Look up the name in the `nse_csv` index (`fill_from_name`).
3. One pair found: fill symbol and ISIN.
4. Zero or several pairs: leave symbol empty. `filter_items` rejects the item as "universe".

A name match whose ISIN disagrees with the item's ISIN is rejected and counted as `isin_conflict` in the run message (format `rejected parse=<n> universe=<n> isin_conflict=<n>`).

Measured on the 142-item sample (2026-11-12, read-only): 111 matched, 0 ambiguous, 31 not concluded (23 distinct names). Article-text search (matching master names inside the title, headline and description) rescued none of the 31, and it made one row ambiguous that rule A gets right. So article-text search is not adopted.

### 4.3 Source precedence (D6): not implemented

`build_index` treats the two sources as equals. Today a conflict between them drops the symbol or ISIN (see section 3). D6 needs a change: when an ISIN is in both sources and the symbol or name differs, take the `nse_csv` value. Upstox is used only where NSE has no row for that ISIN. This change is open point O1 below. D6 is decided yes (O1, 2026-11-12) but not implemented; implementation is T2.

### 4.4 Index membership (D7)

- Add the six indices to `SCAN_INDEXES`, each with its primary and fallback CSV URL taken from `scripts/fetch_index_constituents.py`. They are stored in `index_constituents` under their index names.
- `scanner/constituent_membership.py` reads the database. The CSV reader stays only as an offline test path.
- Universe count: 752 `index_constituents` rows for NIFTY TOTAL MARKET (current, read from the database on 2026-11-12). The 754 in the handoff is the first load and was replaced. The 751 in spec §4.3 is an older figure and has not been re-checked. Update spec §4.3 to 752 when that section is next edited (O5).

### 4.5 llm-client (D8 to D11)

- New service `llm-client` in `docker-compose.yml`. Built from `docker/llm-client/Dockerfile` (new). It is on the `market-scanner` network only, with no published port.
- Endpoints: `POST /v1/chat` (one request format for the scanner, in the OpenAI chat shape) and `GET /healthz`.
- Presets: `config/llm_providers.json` (new) is a read-only seed of built-in provider presets (see O17). It is loaded into the database. The database is the runtime source; the user adds and edits providers in the app.
- `ollama` class: native `/api/chat` at `http://<host>:11434`. Keeps `num_ctx` and the model settings the scanner already sends.
- `openai_compat` class: `POST <base_url>/chat/completions`, `Authorization: Bearer <key>`. Blocks in scope: `openrouter` (`https://openrouter.ai/api/v1`), `openai` (`https://api.openai.com/v1`), `anthropic` (`https://api.anthropic.com/v1/`, with header `anthropic-workspace-id` if the key needs it).
- Keys are entered in the UI, shown masked, and stored encrypted in the database (BL-3). Each key record binds its origin inside the encrypted record (BL-1). Keys never go into `.env`, compose or chat. `llm-client` reads a key from the UI provider registry by `key_ref`. The `SECRETS_API_URL` read path is not used for key entry; `PUT /secrets` returns 410 (`ui/app/api.py` lines 527 to 538).
- **API key entry (user, 2026-11-12).** The key is entered in the app's settings page, saved to the encrypted database, and referenced by `key_ref`. The key field is optional for the `ollama` class (local model, blank is allowed). It is mandatory for any cloud provider in the `openai_compat` class, including Anthropic. A cloud provider with no saved key does not run: the client fails the call with a clear message that names the provider and says the key is missing, and the UI shows the same notice. The key is never shown back in full after saving.
- **Provider settings per request (decided by Claude 2026-11-12, to match the model decision).** The scanner reads the active provider block from the database at the start of each run: class, route, `key_ref` and model. It sends these with every request to `llm-client`. For a keyed provider the base URL is not sent from the scanner; it comes from the key's record, which binds the origin inside the encrypted record (BL-1). `llm-client` resolves the key from the UI provider registry by `key_ref`, and sends the provider key only from the server, to that origin. It still holds no database access.
- **Model source (user, 2026-11-12: "from database"; the reader is my call, as the user delegated it).** The model name is always read from the database. A model the user typed is saved once and reused on every later run, and the user picks it from the saved list. The scanner reads the saved model at the start of each run and sends it with every request to `llm-client`. `llm-client` holds no database access and takes the model only from the request. Reason: the scanner already has the database connection, and this keeps the database credential out of `llm-client`.
- `strict_check: true` makes the client fail a call whose JSON reply lacks a required field. This matters for Anthropic, whose OpenAI-compatible layer drops unsupported fields silently. Anthropic's layer is described by Anthropic as a test path, not a production path (source: https://platform.claude.com/docs/en/api/openai-sdk). Test before any production use.
- Each result records the provider name and model name. Each call is recorded the way `conclude` records LLM calls today, with `RUN_ID`.
- The scanner side: `scanner/llm.py` keeps its public functions. Their HTTP calls go to the client URL. `scanner/conclude.py` changes the same way. The `enrich`, `extractcheck` and benchmark callers keep their signatures.

### 4.6 Provider, model and URL selection (requested 2026-11-12, not yet approved)

- **Anthropic URL support.** Two routes are configured. Native Messages (`POST /v1/messages`, base `https://api.anthropic.com`) and the OpenAI-compatible layer (`POST /v1/chat/completions`, base `https://api.anthropic.com/v1/`). Either one alone is enough. If both are present, one is primary and one is secondary. A setting, `AI_PROVIDER_ROUTE` (`native` or `compat`), picks the route in use. Agreed 2026-11-12. There is no automatic switch when a route fails.
- **Provider name.** `AI_PROVIDER_NAME` selects the active block in `config/llm_providers.json`. It is a choice between the named blocks. This replaces `LLM_PROVIDER` in D11. Agreed 2026-11-12 (O12).
- **Model name.** `AI_MODEL_NAME` (agreed 2026-11-12, O12) is the name the backend reads. Its value is saved from the settings page to the database, not edited by hand in an env file. The default is the Qwen3.5 Q6_K tag `hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K`, for fresh installs and for upgraded installs (BL-4, confirmed by the user 2026-11-12). The user can change it in settings. Later runs pick from a dropdown of saved models (see Setup in the UI, O16). A run with a blank value stops.
- **Base URL.** `AI_PROVIDER_URL` (section 4.5 and O6) holds the base of the active provider.
- **Setup in the UI.** Every provider, route and model setting is a dropdown in the app UI. The chosen values are saved in the database and used by every run (answered 2026-11-12). The dropdown values reach the UI through the API, as in the model-list path above. If the saved model is cleared, the first run stops. The app then shows a notification that the model must be set in settings. The notification has a link that opens the model configuration page directly, and a short guide. (Answered 2026-11-12.)
- **Provider entries (user, 2026-11-12).** The user can add any provider by its URL and a name. After it is added, the app discovers the models from that provider's list endpoint, and the user chooses one. The provider entries are saved in the database. Keys for them go in the encrypted database, under the secrets rule, and never in a settings file.
- **Model list.** Verified 2026-11-12 from the providers' docs. Anthropic native: `GET /v1/models`, cursor-paged (`limit` up to 1000, default 20; loop on `has_more` with `after_id`). Anthropic native calls need the `x-api-key` and `anthropic-version` headers. The compatibility layer documents no model-list endpoint. OpenAI: `GET /v1/models`. OpenRouter: `GET /api/v1/models`, with `limit` and `offset`. Google Gemini: `GET /v1beta/models`, paged, and ids come back as `models/{id}`, so strip the prefix. Groq: `GET /openai/v1/models`. Mistral: `GET /v1/models`. Together AI: `GET /v1/models`, with the host to check (`api.together.ai` or `api.together.xyz`). Unconfirmed: OpenAI's official page returned 403, so its paging is unknown; Gemini's auth header was not checked; the Anthropic `anthropic-version` value must be taken from the docs when T4 is built. The user picks the model from these lists (O13, answered 2026-11-12). The data path is: provider list, then `llm-client`, then Fastify, then the UI. The browser never calls the provider or `llm-client` directly, because UI data goes only through the API. The Anthropic compatibility layer has no list endpoint, so with `AI_PROVIDER_ROUTE=compat` the picker has no list source (O15).

## 5. Open points (need your answer before approval)

- **O1. Source precedence (D6).** Implement the NSE-wins rule in `build_index` now, or keep the current conflict-drop? Recommendation: implement it, because D6 was decided and the code does not follow it. **Answer (2026-11-12): yes.** Implement the NSE-wins rule in `build_index` as part of T2.
- **O2. BSE.** Enter BSE into the master now, or defer it as spec Z2 says? BSE returned HTTP 403 from our environment. No BSE table or loader exists. **Answer (2026-11-12), user's words: "recommend now, can be deferred".** **Settled 2026-11-12: deferred.** No BSE loader, table or matching in this design. Reference points recorded here: spec Z2 (deferred) and the HTTP 403 from our environment. BSE matching rule accepted 2026-11-12 (ISIN-first, see the blocker file, BL-5). The BSE source is not yet approved. **Standing rule (user, 2026-11-12):** whenever a brainstorm starts for the deferred BSE implementation, its reference points from this entry are recorded in that brainstorm's design file first.
- **O3. Duplicate ISIN rows.** EQUITY_L.csv has series EQ and BE. One ISIN can appear twice (for example, `21STCENMGM` in series BE). Keep one row per ISIN, or keep all rows and key on ISIN? Recommendation: one row per ISIN, using the EQ row, because the match returns one ISIN and the series is not used. **Settled 2026-11-12: option A, one row per ISIN, using the EQ row.** The series is not used for matching. Default for an ISIN that has only a BE or BZ row (no EQ row): keep that one row, so no security drops out of the table. The user accepted this default with the answer A.
- **O4. Name conflicts.** FUTURE ENTERPRISES LTD, GACM TECHNOLOGIES LTD and JAIN IRRIGATION SYSTEMS LTD have name conflicts. Which symbol or ISIN is correct for each? **Settled 2026-11-12 (user agreed to the proposal).** Each pair is two distinct securities with their own ISINs (FEL and FELDVR; GATECH and GATECHDVR; JISLDVREQS and JISLJALEQS). Both stay in the table. The name lookup returns nothing for these three names, by design under Rule A. Symbol and ISIN lookups still work for each security. Matches the handoff, item 5.
- **O5. Count gaps.** EQUITY_L.csv has about 2,635 data rows but `nse_csv` holds 2,633. The universe is 751 (spec), 752 (`index_constituents`) and 754 (handoff). Explain or accept each gap. **Settled 2026-11-12 (evidence, not a parser change):**
  - The parser keeps all 2,635 rows from the local file (`equity_list_rows`, checked offline). `refresh` inserts every parsed row with no dedupe. The write path does not drop rows.
  - The database rows were loaded at 02:57 IST on 2026-11-12 (`loaded_at`, `as_of` 2026-11-12). The local `EQUITY_L.csv` was written at 14:42 IST the same day.
  - A symbol-by-symbol diff shows the database is a strict subset of the local file. The two rows in the file but not in the database are ESFL (INE0ITO01014) and SUVID-RE (INE018420013). Nothing is in the database that is not in the file.
  - Conclusion: the 2-row gap is a snapshot difference, probably NSE listings added between the refresh and the later download. It is not a bug. The next monthly refresh (due about 2026-12-12) or a manual refresh picks up both rows.
  - Universe: 752 `index_constituents` rows is the current figure. 754 is the replaced first load. 751 in spec §4.3 is older and needs updating (see section 4.4).
  - Not done: no refresh was run. A refresh needs the loader role, and that is a write, so it waits for the user's decision.
- **O6. LLM_URL and CONCLUDE_URL (must-not-change list).** Decision 10 replaces both with one internal client URL. That changes names that were listed as must-not-change. Confirm the rename, or keep both names as aliases of the client URL. **Answer (2026-11-12): names settled.** The internal URL from the scanner to `llm-client` is `LOCAL_LLM_URL`. It replaces `LLM_URL` and `CONCLUDE_URL`. The cloud provider base URL is `AI_PROVIDER_URL`. It holds the base of the active provider (`openai_compat` class), and the client appends `/chat/completions`. This supersedes the earlier wording "OpneAI_API_URL". Still open for T4: whether `AI_PROVIDER_URL` overrides the `base_url` in the active block of `config/llm_providers.json`. No change to compose, env or code until T4 is approved.
- **O7. Hosted providers.** A hosted provider receives scanner text outside the machine. Confirm each provider before it is enabled. Ollama stays the default. **Answer (2026-11-12): approved** for hosted providers. The user's stated basis: "there is no sensitive information, information is already available on public domain".
- **O8. Benchmarks.** Do the benchmark scripts (`bench_models.py`, `bench_extract.py`) use the active provider only, or may they name a provider for a measurement run? **Settled 2026-11-12: option A, the active provider only.** A benchmark run uses the provider set as active in settings (`AI_PROVIDER_NAME`) and never names a different provider. Reason: the user uses one provider at a time, and a run that names a second hosted provider would send scanner text to it without its own O7 approval. Consequence for T4: the benchmark scripts read the active provider block from the database like every other run, and take no provider argument. To compare providers, the user switches the active provider in settings first, then runs the benchmark again.
- **O9. Anthropic route.** Use the OpenAI-compatible route (D9) and test it, or add a native Messages adapter later? Recommendation: the compatible route now, with `strict_check`. Decide after the test. **Answer (2026-11-12): both routes are needed.** Anthropic gets two blocks: the native Messages API and the OpenAI-compatible layer. If both are configured, the config names one as primary and one as secondary. The meaning of "secondary" (used only after the primary fails, or chosen by a setting) is still open (O11).

- **O11. Secondary Anthropic route.** When the primary route fails, does the client switch to the secondary route automatically, or does the user choose the route with a setting? **Answer (2026-11-12): the route is chosen by a setting.** There is no automatic switch on failure. The setting is `AI_PROVIDER_ROUTE` (O12).
- **O12. Names for provider and model choice.** **Answer (2026-11-12): agreed.** The names are `AI_PROVIDER_NAME` (replaces `LLM_PROVIDER`), `AI_MODEL_NAME`, and `AI_PROVIDER_ROUTE` (`native` or `compat`).
- **O13. Model list.** Should the scanner or the client fetch the provider's model list, so the user can pick a model from it? **Answer (2026-11-12): pick the model from the provider.** Model-list endpoints are verified (see 4.6).

- **O14. Where the picked model is saved.** Is the picked model saved in the database and used by every run, or does `AI_MODEL_NAME` in the settings file stay the only saved value? **Answer (2026-11-12): "yes".** Read as: the picked model is saved in the database and used by every run. The reading is mine. **Follow-up answer (2026-11-12):** when no model is saved, the first run stops until a model is picked. Since BL-4 the saved model starts as the Qwen3.5 tag, so the stop applies only after the saved model is cleared (see O16).
- **O15. Picker with the compatibility route.** The compatibility layer has no model list. With `AI_PROVIDER_ROUTE=compat`, should the picker show a fixed list in the config, show the native list, or be hidden? **Decided by Claude 2026-11-12 (user delegated the call).** The compatibility route has no list, so the user types the model name. The app then checks it with one small test call before saving it. If the test fails, the model is not saved and the error is shown. The native route keeps the list picker.

- **O16. Role of AI_MODEL_NAME.** The first run stops until a model is picked (answered 2026-11-12), so the setting no longer gives a starting model. Should it seed the dropdown's default, or be removed? **Follow-up (2026-11-12):** the user wants the notification and a settings link to the model page, so the model is set in settings, not in an environment value. **Answer (2026-11-12):** `AI_MODEL_NAME` starts as the Qwen3.5 tag (BL-4). The user can change it. After that, the dropdown reuses saved models. The name stays in the design as the key the backend reads. Its value comes from the saved settings, so it is not removed (user: "it uses the variable in backend if it is applied from settings"). **Confirmed (BL-4, user 2026-11-12):** the Qwen3.5 Q6_K tag `hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K` is the default for fresh installs and for upgraded installs. Upgraded installs with run history keep running with no prompt.

- **O17. Role of `config/llm_providers.json`.** Providers are now added by the user, not only written in the file (answered 2026-11-12). Keep the file as built-in presets that the user can start from, or drop it? This changes D10 and D11. **Decided by Claude 2026-11-12 (user delegated the call, "make the app as user-friendly as possible").** Keep `config/llm_providers.json` as a seed of presets (OpenAI, Anthropic, OpenRouter, Ollama), with URL, class, route and list endpoint filled in. It is loaded into the database on first start. The user adds a key and picks a model, and can add any other provider. The database holds the live provider list. The file is not read at run time.

## 6. Must not change without a separate approval

- The Ollama models in use, and the `num_ctx` settings.
- The migration numbers in D12.
- `db/events_migrations/` is not used for main-database work.
- The schema of `company_reference` and `index_constituents`, except what O1 requires.
- The events runner wiring (filings T9), which is a separate task.
- `company_reference` keeps only `nse_csv` and `upstox_master` as sources until the BSE migration is written. The BSE source was approved on 2026-11-12. Its migration number is 054, subject to the numbering decision (brainstorm question 4).
- The secret AAD scheme changes only by the BL-1 freshness pointer.

## 7. Proposed tasks (not dispatched; for review)

Each task names its files, one acceptance command, what must not change, and a tool-call limit. The acceptance command for every task is:

`.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`

| Task | Files | Depends on | Must not change | Tool-call limit |
|---|---|---|---|---|
| T1 Six indices in the monthly job | `scanner/company_reference_job.py`; tests in `tests/` for the job | none | the NIFTY TOTAL MARKET entry | 30 |
| T2 NSE precedence (D6) | `scanner/company_reference.py` (`build_index`); tests in `tests/test_company_reference.py` | O1 yes | `normalise_name`; `fill_from_name` behaviour for single-source names | 30 |
| T3 Constituent membership from the database | `scanner/constituent_membership.py`; `scanner/relative_strength.py` if it needs the change | T1 | the CSV reader as an offline path | 30 |
| T4 llm-client service | `docker/llm-client/Dockerfile` (new); `llm_client/` package (new); `config/llm_providers.json` (new); `docker-compose.yml` (new service); `tests/test_llm.py` lines 72 to 75 and `tests/test_conclude.py` line 207 (BL-2 test edits) | O6, O7, O9 | the Ollama models and `num_ctx` | 40 |
| T5 Scanner call sites | `scanner/llm.py`; `scanner/conclude.py`; `enrich.py`; `scanner/extractcheck.py`; `bench_models.py`; `bench_extract.py`; `env.template` | T4 | the public function signatures of `scanner/llm.py` | 40 |
| T6 Test updates | `tests/test_llm.py`; `tests/test_llm_payload.py`; `tests/test_conclude_request.py`; `tests/test_conclude.py` | T5 | the assertions about payload content | 30 |
| T7 Documents | `docs/designs/home-events-filings-spec.md` §4.3; `docs/designs/company-reference-handoff.md` items 4 and 6; `docs/designs/concall-vl-extraction-plan.md` line 14 | T1 to T6 | the spec's other sections | 15 |

Order (agreed 2026-11-12, decision D15): T1, then T2 and T3, then T4, then T5 and T6, then T7. The earlier option to run T4 and T5 after T1 to T3 is not chosen.

T4 includes `docker-compose.yml` (the T4 row above, line 148 of the file before this edit), and the BL-2 test edits named in that row.

## 8. Process

- Goldfish review: six lenses plus the synthesizer, on this file, after the user confirms readiness.
- Approval: the user approves the design, with answers to O1 to O9, before any task is dispatched.
- Verification: each task runs the acceptance command. The task is marked done only with a git SHA or a finished task ID.
- Haiku subagents do the routine edits. Any fallback is reported with the work it did.
