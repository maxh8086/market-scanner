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
| LC1 | partial | c8c601b, PR #112; tests/test_migration_054.py 4 tests; migration 054 applied to the dev database (runner run from origin/main 99dcf31, recorded in schema_migrations) | Dev DB read-back of the 054 tables pending. The earlier 047 digest concern did not reproduce: the stored digest of 047 matches the current file in text mode, so 047 was not edited. |
| LC2 | partial | c6f2175, PR #113 | healthz 200 from the scanner container and 401 token_missing passed. Authenticated call through ui returned 503 (ui not on the llm network at test time). A direct unkeyed Ollama call replied but not through llm-client. Full runtime check pending. |
| LC3 | partial (merged) | PR #114 merged, merge commit ee22ba1; commit 3de46a7; full suite on the combined tree 1525 run, 64 skipped, 0 failed | runtime check pending: UI test call to the local ollama provider needs approval and the dev database 054 tables. Test-call and models routes are 501 stubs until LC4. |
| LC4 | done | PR #115, merge e3860c8; 8 new tests; full suite 1516 run, 64 skipped, 0 failed | gate confirmed 2026-11-13 (output_config.format, anthropic-version 2026-10-21), recorded in design section 4.5. Adapters are not yet wired into llm_client/app.py (still 501 adapter_not_built). The three tests in tests/test_llm_payload.py still target scanner/llm.py and stay until LC6 removes the builders. |
| LC5 | partial (merged) | PR #116 merged, merge commit b68f29b; full suite on the combined tree 1525 run, 64 skipped, 0 failed; 5 new tests. Migration 055 applied to the dev database (same run as 054). Open: UiRegistry has no active-provider or model getter, so healthz reports nulls on the real service; run-start warning is wired into record_run --begin only (scanner run-start call site not changed); base_host is llm-client's host until LC6 sets provider_id and route; health() no longer checks the model name. record_run --fail --reason writes runs.notes (the column name; the design says note). | runtime check pending: run with the model cleared needs the database |
| LC6 | partial (merged) | PR #117 merged, merge commit 35b5d88 (stacked on #116, now in main); full suite on the combined tree 1525 run, 64 skipped, 0 failed; tests/test_llm_payload.py deleted (equivalents in test_llm_client_adapters.py and test_llm.py). Open: the conclude and enrich compose services have no LLM chat token mount (design 4.5 mounts it into scanner and llm-client only) and enrich is not on the llm network, so those jobs cannot authenticate to llm-client until the user decides; json_schema is sent as a bare schema object; token counts are 0 on the new path; bench_models.py vLLM path still uses api=openai and does not fit the new contract; scanner/llm.py LLMConfig.api kept as an ignored field. | runtime check pending: scanner run through llm-client needs the running stack; PR held, not merged |
| LC7 | done (docs) | PR #118 merged, merge commit 99dcf31; grep checks passed; docs only | user confirmed concall plan line 14 (route the VL step through llm-client; llm-client has no image input yet) with "yes" on 2026-11-13 |

Batch 1 results are recorded below as each PR lands.

## Batch 1 log

- LC0: done (see table).
- LC3: implemented and accepted in the worktree (full suite 1513 run, 64 skipped, 0 failed).
- LC3: PR #114 held (runtime check pending); not merged.
- LC4: acceptance 1516 run, 64 skipped, 0 failed. Carries the ledger and gate-record commit (cherry-picked from #114; identical content).
- LC5: held, not merged (runtime check pending: model-cleared run needs the database). Acceptance 1521 run, 64 skipped, 0 failed.
- LC4: merged as PR #115, merge SHA e3860c8; synaptree re-index done (index_repository only accepts /workspace/Market-Scanner, the server's registered root).
- LC6: held, not merged (changes the live scanner LLM path; runtime check pending). Acceptance 1520 run, 64 skipped, 0 failed.

## Post-merge log (2026-11-13)

- #114 (LC3), #116 (LC5), #117 (LC6) merged; #118 (LC7 docs) merged as 99dcf31.
- Migrations 054 and 055 applied to the dev main database by the runner from origin/main 99dcf31. Status afterwards: both applied, nothing pending.
- The 047 digest concern was checked: the stored digest matches the current 047 text in text mode. 047 was not edited.
- Still open: LC1 read-back, LC2 authenticated call through ui on the llm network, LC3 UI test call to ollama, LC5 model-cleared run, LC6 scanner run through llm-client. These need the running stack and an operator go-ahead.

## Final verification plan for group B (prepared 2026-11-13, NOT run; wait for the user to clear the holds)

Merge order (the user decides each merge; never auto-merge):
1. #114 (LC3). Independent; carries the ledger commit also merged via #115, so expect an identical-content merge.
2. #116 (LC5) after the dev DB has 054 and the model-cleared run check is done (migration 055 then applies in order).
3. #117 (LC6) is stacked on #116: after #116 merges, retarget #117 to main (`gh pr edit 117 --base main`), re-run the full suite on the result, then merge. Settle the open items first: chat-token mount and llm network for the conclude and enrich services, the bare json_schema shape, bench_models vLLM path.
4. The LC7 PR (stacked on #117): retarget to main after #117 merges, rerun the suite, then merge.
After each merge: fetch, create the next branch from the current origin/main, run the acceptance command, record counts here.
Post-merge checks: synaptree index_repository from the main checkout (server root /workspace/Market-Scanner), then index_status; apply 054 and 055 to the dev DB only after the 047 digest question is settled by the user; then run the LC1 read-back, the LC2 authenticated call through ui on the llm network, the LC3 UI test call to ollama, the LC5 model-cleared run (expect a failed runs row with notes model_not_set), and the LC6 scanner run through llm-client (one call, one llm_calls record).
