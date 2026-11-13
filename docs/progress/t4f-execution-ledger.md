# T4f execution ledger (home-events, groups A and B)

Source of truth: docs/designs/home-events-t4f-design.md. Created 2026-11-13. Statuses: done, partial, pending, blocked, not started. A task is done only with a real SHA or PR and a passing acceptance run.

Baseline on origin/main 5c6b460 (before batch 1): 1508 tests run, 64 skipped, 0 failed.

Approvals: group A approved 2026-11-13; group B (B 1 to B 8) approved 2026-11-13; design approved as a whole 2026-11-13. The optional second Goldfish review (design section 8) is a user decision and has not been made.

## Group A

| Task | Status | Evidence | Open items |
|---|---|---|---|
| MT1 | done | c713a65 | operator refresh run (seven non-zero index counts) not recorded |
| MT2 | done | 66fb8e4 | none |
| MT3 | done | 66fb8e4 | operator equity_list_drop_counts run on EQUITY_L.csv pending |
| MT4 | done | 66fb8e4 | membership and relative-strength jobs must be rerun after deploy (uppercase index_name) |
| MT5 | done | 7861bfe | run check_loader_grants before the 2026-12-12 refresh |
| MT6 | done | fcb491d | none |

## Group B

| Task | Status | Evidence | Open items |
|---|---|---|---|
| LC0 | done | gate check, this ledger | compose: POSTGRES_USER of the scanner-postgres service is POSTGRES_ADMIN_USER (docker-compose.yml line 212, admin, owns ./data/postgres, used only by that container). App services connect through POSTGRES_DSN_CONTAINER / POSTGRES_* from .env, where env.template line 10 names POSTGRES_USER=scanner (the app login, not the admin). The company-reference loader uses POSTGRES_LOADER_USER (default market_scanner_loader). So 054 tables are owned by the app login; a loader grant is not needed for group B. |
| LC1 | partial | c8c601b, PR #112; tests/test_migration_054.py 4 tests | migration 054 NOT applied to the dev database: the runner stops at 047 because its comment-only text changed after it was applied; the 047 digest is unverified. 047 is not edited and the ledger is not re-hashed. Dev DB runtime check pending. |
| LC2 | partial | c6f2175, PR #113 | healthz 200 from the scanner container and 401 token_missing passed. Authenticated call through ui returned 503 (ui not on the llm network at test time). A direct unkeyed Ollama call replied but not through llm-client. Full runtime check pending. |
| LC3 | partial (PR held) | PR #114 (open, not merged: runtime check pending); commit 3de46a7; full suite 1513 run, 64 skipped, 0 failed | runtime check pending: UI test call to the local ollama provider needs approval and the dev database 054 tables. Test-call and models routes are 501 stubs until LC4. |
| LC4 | done | PR #115, merge e3860c8; 8 new tests; full suite 1516 run, 64 skipped, 0 failed | gate confirmed 2026-11-13 (output_config.format, anthropic-version 2026-10-21), recorded in design section 4.5. Adapters are not yet wired into llm_client/app.py (still 501 adapter_not_built). The three tests in tests/test_llm_payload.py still target scanner/llm.py and stay until LC6 removes the builders. |
| LC5 | partial (PR held) | branch feat/llm-healthz-lc5, commit and PR number in batch 1 log; full suite 1521 run, 64 skipped, 0 failed; 5 new tests. Migration 055 not applied to any database. Open: UiRegistry has no active-provider or model getter, so healthz reports nulls on the real service; run-start warning is wired into record_run --begin only (scanner run-start call site not changed); base_host is llm-client's host until LC6 sets provider_id and route; health() no longer checks the model name. record_run --fail --reason writes runs.notes (the column name; the design says note). | runtime check pending: run with the model cleared needs the database |
| LC6 | partial (PR held) | branch feat/llm-cutover-lc6, stacked on feat/llm-healthz-lc5 (PR #116); PR number in batch 1 log; full suite 1520 run, 64 skipped, 0 failed; tests/test_llm_payload.py deleted (equivalents in test_llm_client_adapters.py and test_llm.py). Open: the conclude and enrich compose services have no LLM chat token mount (design 4.5 mounts it into scanner and llm-client only) and enrich is not on the llm network, so those jobs cannot authenticate to llm-client until the user decides; json_schema is sent as a bare schema object; token counts are 0 on the new path; bench_models.py vLLM path still uses api=openai and does not fit the new contract; scanner/llm.py LLMConfig.api kept as an ignored field. | runtime check pending: scanner run through llm-client needs the running stack; PR held, not merged |
| LC7 | not started | | batch 2, after user review |

Batch 1 results are recorded below as each PR lands.

## Batch 1 log

- LC0: done (see table).
- LC3: implemented and accepted in the worktree (full suite 1513 run, 64 skipped, 0 failed).
- LC3: PR #114 held (runtime check pending); not merged.
- LC4: acceptance 1516 run, 64 skipped, 0 failed. Carries the ledger and gate-record commit (cherry-picked from #114; identical content).
- LC5: held, not merged (runtime check pending: model-cleared run needs the database). Acceptance 1521 run, 64 skipped, 0 failed.
- LC4: merged as PR #115, merge SHA e3860c8; synaptree re-index done (index_repository only accepts /workspace/Market-Scanner, the server's registered root).
- LC6: held, not merged (changes the live scanner LLM path; runtime check pending). Acceptance 1520 run, 64 skipped, 0 failed.
