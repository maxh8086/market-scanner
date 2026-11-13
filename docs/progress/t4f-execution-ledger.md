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
| LC3 | see batch 1 | PR in batch 1 | runtime check pending: UI test call to the local ollama provider needs approval and the dev database 054 tables. Test-call and models routes are 501 stubs until LC4. |
| LC4 | see batch 1 | | gate confirmed 2026-11-13, recorded in design section 4.5 |
| LC5 | see batch 1 | | runtime check pending: run with the model cleared needs the database |
| LC6 | see batch 1 | | runtime check pending: scanner run through llm-client needs the running stack; PR held, not merged |
| LC7 | not started | | batch 2, after user review |

Batch 1 results are recorded below as each PR lands.

## Batch 1 log

- LC0: done (see table).
- LC3: implemented and accepted in the worktree (full suite 1513 run, 64 skipped, 0 failed).
