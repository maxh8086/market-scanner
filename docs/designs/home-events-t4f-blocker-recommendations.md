# T4f blocker recommendations (BL-1 to BL-5)

* **Status:** Recommendations only, except where the section "Decisions recorded 2026-11-12" below records a decision. Nothing is dispatched. On 2026-11-12 the design files were edited to match the recorded decisions only; the edit log lists each change.
* **Date:** 2026-11-12
* **Source:** Goldfish review `docs/designs/home-events-t4f-goldfish-review.md` (BL-1 to BL-5). Each recommendation was checked by an investigator and then by a separate adversarial verifier (workflow `wf_7e3734f0-07e`, 10 agents, 0 errors).
* **Decisions needed from you:** five. They are listed at the end, one at a time, starting with BL-5.

## Summary

| Blocker | Problem in one line | Recommendation | Needs your answer? |
| :--- | :--- | :--- | :--- |
| BL-1 | Any container on the shared network can make llm-client send a saved key to any host. | Option 2: the UI owns a provider registry, and each key record is bound to its host inside the encrypted value. Add a freshness check. | Yes: should a saved key move when a URL changes? |
| BL-2 | The native Anthropic route has no adapter, and current payloads fail on the compatibility route. | Option B: a third class, `anthropic_native`, with both routes built in T4. | Yes: build the native route in T4, or compatibility only for now? |
| BL-3 | The provider store has no migration number, no seed loader and no key-entry path. | Option A: migration 054 with the presets seeded inline. Keys entered only through the v1 command-line tool. | Yes: keys on the settings page, or command-line only in v1? |
| BL-4 | After upgrade, every enrich and conclude run stops until a model is saved. | Option A: seed the current production model on upgrade only, guarded by existing run history. Stopped runs record `failed` with a reason. | Yes: upgraded installs keep running, or stop once and ask? |
| BL-5 | The spec says ISIN-first for events. The code and design say name-first. Events have no ISIN, so ISIN-first matches nothing. | Option 1: name-first for events. Reword spec section 3.2 and record your BSE rule in your own words. | Yes, and first. |

## Decisions recorded 2026-11-12

These are the user's answers from 2026-11-12. Items marked PROPOSED are not yet approved.

### BL-1: accepted, Option 2

- The UI owns a provider registry. Each key record binds its origin inside the encrypted record (AAD). A freshness pointer held by the UI stops rollback to an older record.
- Correction: AES-GCM stops forgery, not rollback. The freshness pointer is what covers rollback.

### BL-2: accepted, Option B

- `anthropic_native` is a third provider class. Both the OpenAI-compatible route and the native route are built in T4.
- Tests that change in T4:
  - `tests/test_llm.py` lines 72 to 75 (asserts `json_object`).
  - `tests/test_conclude.py` line 207 (asserts temperature 0.0).
- `max_tokens` 500 applies to extract only. The conclude default is 1400.

### BL-3: user decision, overrides Option A

- Keys are entered in the UI, shown masked, and stored encrypted in the database. This overrides Option A's command-line-only key entry.
- Conflicts to record (not edited here):
  - `docs/designs/secrets-and-roles.md` decision 9 (line 63): v1 is a CLI, and the web admin is v2.
  - `docs/designs/secrets-and-roles.md` line 64: values are typed at a terminal prompt, never through chat.
  - `PUT /secrets` returns 410 (`ui/app/api.py` lines 527 to 538).
- The user must amend `docs/designs/secrets-and-roles.md`. **NOT EDITED.**
- Guardrails:
  - The UI is bound to 127.0.0.1 (`docker-compose.yml` around line 154).
  - Writes need a custom request header plus an Origin check.
  - No plaintext is echoed after save.
  - The master key is on the `ui` service only (`docker-compose.yml` around line 149).
- Correction: `collector_settings` exists (`db/migrations/001_core.sql` line 81), so "no settings table" is false.

### BL-4: user recommendation, confirmed 2026-11-12

- Model for the initial test and run: `hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K`.
- **Confirmed by the user 2026-11-12:** this is the default for fresh installs and for upgraded installs. O16 and section 4.6 of the design are updated to match.
- `qwen3:8b` appears in the goldfish review (line 32), not in the design.

### BL-5: name-first for NSE RSS items (accepted)

- BSE matching rule accepted 2026-11-12: ISIN-first, using rules (a) to (d) in the "BL-5 BSE mapping" section below. The BSE source (a `company_reference` source) was approved 2026-11-12.

- NSE RSS items carry no ISIN, so they are matched name-first.
- Measured offline on 2026-11-12 from `cr.psv` and the seven fixtures: 111 matched, 0 ambiguous, 31 unmatched, 0 ISIN disagreements, 23 distinct unmatched names. This matches the user database run.
- Test added: `test_name_resolved_item_with_disagreeing_isin_is_rejected` (`tests/test_home_events_run.py` line 540). Result at this step: 1 test run, OK.
- `run_cycle` is not wired into production. Wiring is T2.

### BL-5 BSE mapping: rule accepted 2026-11-12 (ISIN-first); BSE source approved 2026-11-12

Measured data (1,002 BSE rows):

- No blank or malformed ISIN. No duplicate ISIN or scrip code.
- 995 of 1,002 ISINs appear in `nse_csv`. 987 of those also appear in `upstox_master`. 8 appear in `nse_csv` only. 7 appear in neither.
- Name-first against `nse_csv`: 762 matched, 0 false matches, 1 ambiguous, 239 unmatched.
- ISIN-first: 995 resolved, 0 multi-symbol, 0 disagreements with name-first where both resolve.
- Of the 239 name-unmatched rows, 232 have an ISIN match. 181 of those BSE names are exactly 30 characters, because the BSE file cuts names at 30 characters (227 rows are exactly 30 characters).
- BSE scrip codes overlap NSE symbols in 0 cases, so a scrip code cannot be used as an NSE symbol.
- Ambiguous example: code 500219 JAIN IRRIGATION SYSTEMS LTD., ISIN INE175A01038, resolves by ISIN to JISLJALEQS. Its name matches two pairs, one with the non-standard ISIN IN9175A01010.
- Neither source matches: codes 526433, 544896, 544836, 544467, 544937, 500285, 506854.
- Schema: `db/migrations/047_company_reference.sql` line 11 allows only `nse_csv` and `upstox_master`. A BSE source needs a migration. The next free number is 054, subject to the numbering decision.

Rule accepted by the user on 2026-11-12 (ISIN-first):

- (a) BSE item with an ISIN: resolve by ISIN against the BSE master, then cross-check `nse_csv`.
- (b) Scrip code: map through the BSE master to an ISIN, never to an NSE symbol.
- (c) Name only: accept only one exact name key whose pair is unique. Ambiguous means refuse.
- (d) Any disagreement means refuse.

Name-first alone is not used for BSE, because it misses the truncated names that ISIN resolves.

Limits: one snapshot; the BSE feed is deferred (Z2); the pinned library evidence covers field names only.

**BSE source approved by the user 2026-11-12.** It needs a migration, with number 054 (the next free number), subject to the numbering decision (brainstorm question 4). The migration must be written before the source is loaded.

## BL-1: a caller can send a saved key to any host

### What the problem is

Design section 4.5 has the scanner send the base URL and `key_ref` with every call. llm-client then looks up the key by `key_ref` and sends it to that base URL. Nothing ties a key to one host. `POST /v1/chat` has no caller authentication. The compose network is one shared network, and every service on it can reach llm-client by name (`docker-compose.yml` lines 225–227). The UI also has no login, and it is reachable at `ui:8080` from any container on that network (line 128 shows the collector using that address).

Today there is no live key-sending path to protect. `scanner/llm.py` has no API key and no Authorization header. So this is a design gap, not a leak in running code.

### Options

- **Option 1: static host allowlist plus a caller token.** llm-client holds a fixed list of allowed hosts in its own config. This is the smallest change. It conflicts with your answer that any provider can be added by URL (design line 97), and with O17, which says the database holds the live provider list. Every new provider needs a file edit and a restart. Rejected.
- **Option 2 (recommended): UI-owned provider registry, with the origin bound inside the encrypted key record.** The UI is the only writer of provider rows and key records. Each key record is AES-GCM encrypted JSON holding the key, the origin (scheme, host, port) and an `approved` flag. The scanner sends only `provider_id`, `model` and `route`. llm-client has its own token. It reads the provider row and the key record through the internal secrets API, and sends the key only when the provider row's origin matches the origin in the key record.
- **Option 3: the secrets API releases a key only if the caller's target origin matches.** The check sits with the master-key holder. But the caller still picks the origin on every call, `/v1/chat` still needs authentication, and the check cannot be tested inside llm-client alone. Possible, but weaker than Option 2.

### Recommendation: Option 2, with a freshness check

Why Option 2:

- It keeps your any-URL request and the O17 database rule.
- The key check runs in the one service that holds the master key (`docker-compose.yml` line 149). llm-client needs no database access, which the design requires.
- A scanner-side database write cannot move a key to another host, because the origin is inside the AES-GCM value. The AAD binds table, name, owner and key version (`scanner/secret_crypto.py` lines 68–70), so forging a new value is not possible without the master key.

**Correction from verification.** The first investigation called this binding "tamper-evident" and said the shared login "cannot defeat" it. That overstates it. AES-GCM stops forgery, but it does not stop replay. A scanner with write access can restore an older valid row (nonce, ciphertext, key version), and it will still decrypt. So the origin could be rolled back to a value that was valid before. The fix is a freshness check: the UI keeps a current-version pointer or counter for each key record, and llm-client refuses a record whose version is not the current one. The UI alone holds that pointer. Without it, Option 2 does not hold against rollback.

**Other changes that come with Option 2:**

- A new `llm` compose network joined only by scanner, ui and llm-client. No published port on llm-client. Outbound internet access stays on, because llm-client must reach the providers.
- llm-client requires `Authorization: Bearer` with a new token that only scanner holds. `GET /healthz` returns no key, URL or provider data.
- The `approved` flag sits in the encrypted record, not in the provider row, so a scanner write cannot flip it.
- The UI write routes require a custom header and refuse foreign `Origin` values, because the UI has no login.
- The goldfish review's wording ("a foreign base URL is refused before any secret is fetched") must change. llm-client has to read the record to compare origins, so the requirement becomes: the key is never sent to a foreign host.
- The per-request payload in design line 84 is a Claude decision, not one of your answers, so this change does not need your approval.

**Risk that stays open.** A scanner write can still change a provider's display URL or break routing. That is a denial of service, not a key leak. Accept it, or close it with a second database login for the UI (a separate decision, linked to BL-3).

### Question for you (BL-1)

When you change the URL of a provider that already has a saved key, should the saved key move to the new host after you confirm that host in the app? Or must you type the key again?

**My recommendation:** move it, but only after you confirm the new host by name in the app. The UI then writes a new record with a new version, and llm-client sends the key only to the confirmed host. Until you confirm, the old record stays bound to the old host, so calls to the new URL fail. If you prefer, typing the key again is the safest option and costs one step per URL change.

### Tests (proposed names, none exist yet)

- `tests/test_llm_client_auth.py`: a call without a bearer token gets 401; a wrong token gets 401; `/healthz` has no URLs or keys.
- `tests/test_llm_client_origin.py`: a request with a `base_url` field is rejected; the key is not sent when the record origin differs (no outbound call, no key in logs or responses); the origin check ignores the path.
- `tests/test_llm_client_registry.py`: an unapproved provider is refused; a missing key record fails with a message that names the provider.
- `tests/test_llm_client_freshness.py` (new): a stale record version is refused after a rollback.
- `tests/test_service_secrets.py`: extend the 403 test to the llm-client token; the llm-client token cannot read the Upstox token.
- `tests/test_compose_llm_network.py`: parses `docker-compose.yml` and checks that llm-client has no `ports` key and joins only the `llm` network.

### Items to check before T4

- `bench_models.py` line 116 uses `127.0.0.1`. If the benchmark runs on the host, it cannot reach an unpublished llm-client. Check this before T5.
- Confirm with a read-only database query that no key records exist yet, so nothing needs migrating.

## BL-2: the native Anthropic route

### What the problem is

The code has two request shapes: `api` set to `ollama` or `openai`, and endpoints `/api/chat` and `/v1/chat/completions` (`scanner/llm.py` lines 66 and 73–76). Anthropic appears in no Python file. The design's section 4.6 and O9 add a native Messages route (`POST /v1/messages`, `x-api-key`, `anthropic-version`), but no class, request mapping or adapter is defined for it.

Current payloads also fail on Anthropic's OpenAI-compatible route as written:

- `scanner/llm.py` lines 366–371 default to `response_format: json_object`, and the schema path sends `json_schema` without `strict: true`. Anthropic's compatibility page says only `json_schema` with `strict: true` is accepted.
- `temperature` is always sent (default 0.0, `scanner/llm.py` line 68 and `scanner/conclude.py` line 490). On Claude 4.7 and later, any value below 1 returns a 400, so the field must be omitted for those models.
- The system prompt is a `system` role message in `conclude.py` (lines 473–475 and 488–489). The native API takes a top-level `system` field.
- The native route requires `max_tokens`. The compatibility route always sends it.

### Options

- **Option A: compatibility route only now, native later.** Smallest change. It conflicts with your settled answer O9 ("both routes are needed"). Anthropic calls the compatibility layer a test path, not production. It has no documented model list. Native features are not available. Not recommended.
- **Option B (recommended): third class `anthropic_native`, both routes built in T4.** A new class in D9 and section 4.5. Its own adapter in llm-client maps the OpenAI-shaped request to `POST /v1/messages`: system goes to the top-level field, `max_tokens` is always set, and temperature is omitted for Claude 4.7 and later. It maps the content blocks and usage fields back. Both routes stay configured, and `AI_PROVIDER_ROUTE` picks one (O11). The model picker gets a real list endpoint.
- **Option C: native route only for Anthropic.** Honest for production, but it conflicts with O9 and removes the compatibility route you asked to keep as a test path.

### Recommendation: Option B

Option B is the only option that honours O9 and O11. Every option needs an adapter, because there is no Anthropic code today. Keeping the request shape fixed in the scanner, and moving the translation into llm-client, means each mapping is written once per class. The strict-flag and temperature fixes are needed on the compatibility route under every option, because the current payloads fail there.

**Design changes:**

- Section 2 D9 and section 4.5: add `anthropic_native`. Mark D9 superseded (review M-04). Anthropic gets two blocks: native (`https://api.anthropic.com`, `/v1/messages`, `x-api-key` and `anthropic-version`) and compatibility (`https://api.anthropic.com/v1/`, `/chat/completions`).
- Section 4.5: add the request mapping (system to top-level, `max_tokens` always set, no temperature for Claude 4.7+, `json_schema` with `strict: true`, no `json_object`) and the response mapping. Add `GET /v1/models` and the one-call test endpoint (O15).
- Section 4.6, line 92: remove the words "primary" and "secondary". `AI_PROVIDER_ROUTE` alone picks the route (O11).
- Section 7: add T4a (the two adapter files under `llm_client/adapters/`) and T4b (their tests). T5 changes so `scanner/llm.py` and `scanner/conclude.py` send the OpenAI-shaped request only and read the normalised response. Remove the separate `conclude.py` request body.
- `enrich.py` lines 1071–1072 and `bench_extract.py` line 35: add the new class value, or remove those flags once the route moves into llm-client (review M-28).

**Corrections from verification:**

- The compatibility page says only `json_schema` with `strict: true` is accepted. It does not say a missing `strict` returns a 400. That is an inference.
- The design says the compatibility layer "silently drops unsupported fields". Several fields return a 400 (`json_object`, `text`, temperature below 1 on Claude 4.7+, `n` not 1). Say "most unsupported fields are ignored, and some return an error".
- The 500-token cap (`OPENAI_MAX_TOKENS`, `scanner/llm.py` line 297) applies only to the extract path. The conclude path's default is 1400 (`scanner/conclude.py` line 517).
- Two existing tests would break and are missing from the list: `tests/test_llm.py` lines 72–75 (asserts `json_object`) and `tests/test_conclude.py` line 207 (asserts `temperature == 0.0`). The `test_conclude_request.py` body test is at line 32.
- The native response field names (content blocks, `usage.input_tokens`, `output_tokens`), the native `GET /v1/models` path and the `anthropic-version` value were not confirmed. The fetched page was cut off before the response schema. Check all three in the live docs before T4 starts.
- The design cites `platform.claude.com/docs/en/api/openai-sdk`. The canonical URL is `.../cli-sdks-libraries/libraries/openai-sdk`. The content matches; fix the link.

**Risk.** Dropping temperature on Claude 4.7+ changes output compared with the Ollama path, which uses 0.0. Run a benchmark before cutover (O8: benchmarks use the active provider).

### Question for you (BL-2)

Should the native Anthropic Messages route be built in T4 as its own adapter, with both routes configured and `AI_PROVIDER_ROUTE` choosing between them (Option B)? Or should Anthropic ship only through the compatibility route for now, with the native route moved to a later design (Option A, which conflicts with O9)?

## BL-3: the provider store, seed and key entry

### What the problem is

Three things are missing:

1. **No migration number is claimed.** Design D12 reserves 049–052 for other slices. 053 is `fund_daily`. The next free number is 054, and nothing claims it yet. The S2a slice takes "the next free number when it is written" (`docs/designs/collector-split-slices.md` line 329), so another slice could take 054 first.
2. **The presets file does not exist.** Section 4.5 says `config/llm_providers.json` is loaded into the database, but no such file exists, and no loader reads it. `config/` holds only `glossary.json` and `retention.json`.
3. **Key entry conflicts with existing rules.** The design (line 83) says API keys are entered on the settings page (your answer, 2026-11-12). But `PUT /secrets` returns HTTP 410 with the docstring "The UI has no login, so it must not write secrets" (`ui/app/api.py` lines 527–538). Secrets-and-roles decision 9 says v1 key entry is a command-line tool inside the API container, and the web admin screen is v2 (`docs/designs/secrets-and-roles.md` line 63). The rule that secrets are typed at a terminal prompt, never through chat, is at line 64 of that file.

### Options

- **Option A (recommended): migration 054 with presets seeded inline.** One new migration creates the provider table and the per-provider settings table, then seeds the preset rows with `INSERT ... ON CONFLICT DO NOTHING` in the same file. The app login owns the tables, so no `GRANT` is needed. Each provider has a `key_ref` that names an `app_secret` row. Keys are entered through the v1 command-line tool.
- **Option B: migration 054 for tables, plus a Python loader that reads the JSON.** Keeps O17 as written and lets presets change without a migration. But it adds a second write path at start, which every start route must call, and a JSON file that must be in the image.
- **Option C: one `app_config` row holding the providers as JSON.** `app_config` is proposed but not built, so this adds a build step. It has no typed columns and no constraints, and it mixes the provider list with the dashboard template.

### Recommendation: Option A, plus command-line-only key entry

Option A follows the migration rules the repo already has. The runner applies 054 on the next start, with no new startup code. The app login owns the tables, so the 048 failure (an `InsufficientPrivilege` error, fixed by changing the table owner, `CHANGELOG.md` line 8) cannot repeat. Keys stay in `app_secret`, which already has encryption, a name rule and no `DELETE` grant. The seed follows the `041_index_eod_source.sql` pattern.

**The cost:** O17 changes from "keep the JSON as the seed" to "seed in migration 054". Applied migration files cannot be edited, so a later preset change needs migration 055. That is how the repo already works.

**On keys:** I recommend keeping decision 9. The settings page shows whether each key is set, and lets you change the provider URL and model. It does not take a key. Accepting keys on the page would need a new authenticated write path, which the UI does not have. That is a bigger build than v1 needs. This reverses your 2026-11-12 answer on key entry, so it needs your sign-off.

**Other items to resolve before writing 054:**

- The name mismatch: `env.template` line 9 sets `POSTGRES_USER=scanner` and calls it the app login. The grants (`045_app_secret.sql` line 20 and `048`) name `market_scanner_app`. The owner test only works if the migrating login is the one the app uses. Resolve this first.
- Claim 054 now, so S2a cannot take it. Write this in design D12 and in `collector-split-slices.md`.
- The design says Fastify routes. The deployed browser API is FastAPI (`ui/app/api.py` line 11). Fastify is in `server/`, which is not in `docker-compose.yml`. Fix the route wording before any route task is written. The mentions are at goldfish review lines 145 and 221.

**Design changes:**

- D12 (design line 33): claim 054 for T4f; record that 049–052 stay with the other slices.
- Section 4.5 (line 79): replace the JSON load with the inline seed.
- O17 (line 127): change to "seeded in migration 054". Mark it for your sign-off.
- Lines 82–83: name each `key_ref` as an `app_secret` row. Add each key name to `ui/app/internal_secrets.py` `SERVICE_ALLOWED` only for the service that calls that provider.
- Section 7: add one migration task (054) and one command-line task for key entry. Remove any JSON-loader task.

**Corrections from verification:**

- "No provider or settings table exists" is literally false. `collector_settings` exists (`db/migrations/001_core.sql` line 81). It holds collector schedules, not providers. The correct statement is "no provider table exists".
- The "terminal prompt, never through chat" rule is at `docs/designs/secrets-and-roles.md` line 64 (the 2026-11-10 credentials answer), not decision 10 (line 65).
- The `fund_daily` table name is at `053_fund_daily.sql` line 6, not line 1.
- "On first start" in the O17 wording is at design line 127, not line 79.
- The 001_core seed (lines 90–96) is a bare `INSERT` with no `ON CONFLICT`. It is not insert-if-missing.

### Question for you (BL-3)

Should LLM provider API keys be entered only through the v1 command-line tool inside the API container, as secrets-and-roles decision 9 says (my recommendation)? Or should the settings page accept keys in v1? The second option needs a new authenticated write path, because the UI has no login and `PUT /secrets` returns 410.

### Tests (proposed)

- `tests/test_llm_provider_migration.py` (new): 054 applies on a throwaway schema (`tests/pgschema.py`); the seed is idempotent; an edited preset row survives a re-apply; the new tables are owned by the app login.
- `tests/test_app_secrets.py`: extend `test_bad_names_rejected` (line 58) to the provider `key_ref` names.
- `tests/test_ui_api.py`: keep the 410 test for `PUT /secrets`; add a check that no provider key write route exists in v1.
- `tests/test_pg_migrate_events.py`: the runner tests must not depend on the file count.

## BL-4: the upgrade stop

### What the problem is

Design section 4.6 says `AI_MODEL_NAME` starts blank, is saved in the database, and the first run stops with a notification if no model is picked. After an upgrade, every enrich and conclude run would stop until someone saves a model. The design has no task for the settings page, the notification, or the seed of the model production already uses.

**Which model is in use.** The design and the goldfish review say the current default is `qwen3:8b`. That is only the library default in `scanner/llm.py` line 65. Production runs `hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K`: `start.ps1` line 62 sets it and passes it to enrich at line 328, and `scanner/conclude.py` line 41 sets it as `DEFAULT_MODEL`. `docker-compose.yml` line 107 runs conclude with no model argument, so it uses that default. The seed must use the Qwen3.5 tag.

**Failure record.** `runs.status` allows only `running`, `complete`, `failed` and `partial` (`db/migrations/001_core.sql` line 11). So a stop with status `model_not_set` would be rejected by the database. `record_run.py --fail` writes `failed` with no reason (lines 103–106). With `-Symbols`, no run row is written at all (`start.ps1` line 67).

### Options

- **Option A (recommended): seed the current model on upgrade only.** Migration 054 inserts the current Ollama provider and the Qwen3.5 tag with `ON CONFLICT DO NOTHING`, but only when the `runs` table already has at least one row. A fresh install stays blank and keeps the first-run stop.
- **Option B: seed the current model for every install.** The simplest migration, but it contradicts O16 ("starts blank", "you type the model the first time") for every install. A fresh install would silently run a model nobody chose. Not recommended.
- **Option C: a one-release environment fallback.** `AI_MODEL_NAME` in `env.template` and `start.ps1`. It conflicts with the settled rule that the model is saved in the database and not edited in an env file (design line 94). It creates two sources of truth. Not recommended.

### Recommendation: Option A, plus three fixes

Option A keeps upgraded installs running, which is the failure this blocker is about. It keeps the O16 behaviour for new installs. It adds no env value, so the database-only rule holds. The seed reuses an existing insert-if-missing pattern (`scanner/collect/settings.py` lines 49–54).

The three fixes are needed whichever option you choose:

1. The stop records status `failed` with notes `model_not_set`. No new status value.
2. `record_run.py --fail` takes `--reason`, and the reason is passed through to `finish_run` notes (`scanner/runs.py` lines 313–323 already accept `**fields`).
3. The banner reads the saved setting from the API, not the run row. The banner and the setting then cannot disagree. Subset runs (`-Symbols`) write no run row, so for them the banner is the only signal.

**Risks of Option A:** the guard on existing run history can misfire. An install with old run rows but no saved model gets the seed silently. If the migration fails, `start.ps1` lines 284–286 only warn, and the upgrade falls back to the stop. The two Ollama URLs also differ: `start.ps1` line 64 uses `host.docker.internal`, `env.template` lines 47–48 use `127.0.0.1`. The seed must pick one.

**Design changes:**

- Section 4.6 (lines 90–98): correct the default. Production uses the Qwen3.5 tag. Cite `start.ps1` line 62 and `scanner/conclude.py` line 41.
- Line 96: replace "the first run stops and the app shows a notification" with "the stop records `failed` with notes `model_not_set`, and the banner reads the saved setting".
- Section 7: add T4b (migration 054 with the guarded seed) and T4c (settings API, model picker, banner, stop). Make both prerequisites of T5.
- T5: add root `conclude.py` (model default, line 86) and `start.ps1` (lines 62 and 328). Change the `LLMConfig.model` default in `scanner/llm.py` line 65 to blank, so no code path silently uses `qwen3:8b`. `docker-compose.yml` is already in T4 (line 148), so state which task owns the model change.

**Corrections from verification:**

- `qwen3:8b` is not in the design document. It appears in `docs/designs/home-events-t4f-goldfish-review.md` line 32. Attribute it there.
- Section 4.6 is at design lines 90–98. Lines 124–131 are O14 to O17 and the start of section 6. The O16 text is at line 125.
- The `RecordRunCLITests` anchor is at `tests/test_backfill.py` line 23.
- The "no notification or settings code" claim is right in substance. One comment in `server/src/collectorRefresh.ts` mentions the settings file, so say "no settings page and no LLM settings code".

### Question for you (BL-4)

When an install that already has run history upgrades, should it keep running on the model it uses today (`hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K`) with no prompt? Or should it stop once and ask for a model, the same as a fresh install?

**My recommendation:** keep running with no prompt, which is Option A. The stop is a failure mode for every enrich and conclude run after upgrade. The first choice changes O16 for upgraded installs only, so it needs your sign-off.

## BL-5: name-first or ISIN-first for events

### What the problem is

Spec section 3.2 (line 97, decided 2026-11-12) says the master is keyed by ISIN and name lookup runs after the master match. That is ISIN-first. Design D3 and section 4.2 (rule A), spec section 4.3 (lines 358–362), spec section 6 (line 556), the code and the tests are all name-first.

Events carry no ISIN. `_rss_item` in `scanner/home_events.py` sets `"symbol": None` and `"isin": None` (lines 630–631). So ISIN-first would match zero events in the 142-item sample.

### Options

- **Option 1 (recommended): name-first for events, reword spec section 3.2.** Events match by exact normalised name against `nse_csv`. One (symbol, ISIN) pair is a match. Zero or several pairs are rejected. An ISIN the item carries must agree with the pair. The spec sentence is replaced with the actual key, `(source, symbol, isin)`, and the rule that ISIN is the cross-source join key. Your words are recorded with their date.
- **Option 2: ISIN-first as written.** It rejects every event (0 of 142) until an ISIN source for event text exists. The spec's own survey found none (spec lines 159, 160, 166). Rule A, the `fill_from_name` wiring and spec section 6 would all need replacing, and filings T9 would be blocked.
- **Option 3: keep the spec wording and add an exception.** "For events, the name lookup is the master match. When an item carries an ISIN, it must agree." The result is the same as Option 1, but section 3.2 then holds two rules, and the "keyed by ISIN" claim stays wrong for the table. Option 1 is cleaner.

### Recommendation: Option 1

The code, the tests, design D3 and section 4.2, spec 4.3 and spec section 6 are all name-first. Option 1 changes only wording. On the sample it works: 111 of 142 items match by name, 0 are ambiguous, and 31 are not concluded (23 distinct names). Those 23 names are an accepted gap under D4, and article-text search rescued none of them (design line 63).

The spec's "keyed by ISIN" sentence comes from another project's `CLAUDE.md` (lines 125–128, cited at spec line 130). This repo's `CLAUDE.md` has no such rule. The table's primary key is `(source, symbol, isin)` (`db/migrations/047_company_reference.sql` line 19), with a non-unique index on ISIN (line 22).

**Design changes once you confirm:**

- Spec section 3.2 (line 97): replace the ISIN-first sentence with the confirmed rule.
- Spec decision log (line 669): add your verbatim answer on event order and BSE order, with the date.
- Design O2: the BSE matching rule was accepted on 2026-11-12 (ISIN-first). No separate wording was given. Keep BSE deferred.
- Design D3 (line 24): change "Exactly one ISIN is a match" to "Exactly one (symbol, ISIN) pair is a match". The code counts pairs, not ISINs (`scanner/company_reference.py` lines 157–162).
- Design section 4.2: add the check that rejects an item whose ISIN disagrees with the pair (`fill_from_name`, `company_reference.py` line 180).

**Corrections from verification:**

- Name-first is implemented in `run_cycle` behind the `by_name` parameter (`home_events.py` line 404, `fill_from_name` at line 476), and it is tested. But no production runner passes `by_name` or calls `run_cycle`. Only tests do (lines 362, 374, 533 of `tests/test_home_events_run.py`). So it is implemented, not wired. Wiring belongs to filings T9. Say that, not "works today".
- The phrase "symbols follow the same master process for BSE as for NSE" is in spec line 97, not in the decision log. The log (line 669) reads "BSE symbols follow the NSE master process". Quote each where it appears.
- The `_parse_financial_results` docstring (`home_events.py` lines 675–677) says name resolution is not built. That is stale, because `fill_from_name` exists. Update it.
- The spec cites name-first wording at lines 258, 377 and 379 as well. Cite these as further evidence.

**Tests:**

- Existing, keep: `tests/test_company_reference.py` `test_fill_from_name_resolves_and_rejects` (line 176), `test_name_with_two_pairs_is_ambiguous` (line 168), `test_load_index_for_source_same_name_two_pairs_is_conflict` (line 213); `tests/test_home_events_run.py` `test_name_only_items_resolve_through_by_name` (line 527).
- New: `tests/test_home_events_run.py` `test_name_resolved_item_with_disagreeing_isin_is_rejected`. The disagreement check is only tested at unit level today.
- New, optional: a test that reads `047_company_reference.sql` and asserts the primary key, so the spec wording is checked against the schema.

### Question for you (BL-5), asked first

For events, do you confirm name-first matching: exact normalised name against the NSE list; one (symbol, ISIN) pair is a match; zero or several pairs are rejected; an ISIN the item carries must agree? And should spec section 3.2 be reworded to say so, instead of the ISIN-first order it states now? ISIN-first would reject every event, because events carry no ISIN.

BSE matching rule: answered 2026-11-12. The user accepted ISIN-first, rules (a) to (d) in the "BL-5 BSE mapping" section above. The user gave no separate wording, so the measured rule text is the record.

## Open items after the five decisions

- Three kept goldfish findings were never checked, because the verifier failed on each one: zoom-out F12, comprehension CMP-05 and readiness IR-16. Re-run the verifier on them if you want them checked. The goldfish review lists them in section 5.
- Measurement and task definitions in the design are still open for T1–T7 until these five answers are in.

## Order of questions

1. BL-5: name-first or ISIN-first for events, and the BSE rule. BSE rule answered 2026-11-12: ISIN-first accepted. BSE source approved 2026-11-12.
2. BL-1: should a saved key move after a URL change, once you confirm the host?
3. BL-2: build the native Anthropic route in T4 (Option B), or compatibility only for now?
4. BL-3: key entry through the command-line tool only in v1, or on the settings page?
5. BL-4: upgraded installs keep running with no prompt, or stop once and ask?

Nothing in this file has been applied. Each design change above waits for your answer.
