# Company reference (T4f) handoff

Status as of 2026-11-12. Read this after the plan execution completes.

## Done

- Migration 047 (`company_reference` table, `company_reference_by_isin` view, six indexes) is applied in the `market_scanner` database.
- `scanner/company_reference.py`: name normalisation, CSV and master row builders, `build_index`, `fill_from_name`, `load_index`, `refresh`.
- `scanner/company_reference_job.py`: monthly fetch and refresh. Not yet run against the database.
- `scanner/home_events.py`: `run_cycle` takes an optional `by_name` map. Behaviour is unchanged when it is None.
- Loader role `market_scanner_loader` exists. It has `SELECT, INSERT, DELETE` on `company_reference` in `market_scanner`. The table ACL shows `ard`.

## Open items

1. **Loader password.** Done (user, 2026-11-12). The role `market_scanner_loader` has its password set, and the password is stored in `secrets/company_reference_loader_password`. It is not in chat, and Claude did not read the file.
2. **Loader credential location (decided 2026-11-12, user approved).** The loader password is read from a secret file, not from `.env` or the database.
   - Implemented: `loader_dsn()` in `scanner/company_reference_job.py` reads the file named by `POSTGRES_LOADER_PASSWORD_FILE`. Host, port and database come from `POSTGRES_HOST`, `POSTGRES_PORT` and `POSTGRES_DB`. The user comes from `POSTGRES_LOADER_USER` (default `market_scanner_loader`). `main()` no longer uses `db.connect()`.
   - Tested offline: 6 new tests in `LoaderDsnTests`. Related suites: 88 tests pass.
   - Done by the user (2026-11-12): the role password was set. The same password is in `secrets/company_reference_loader_password`, the repo's existing secret folder (git-ignored and excluded from the image, like `secrets/collector_token`). `POSTGRES_LOADER_PASSWORD_FILE=secrets/company_reference_loader_password` is set in `.env`.
   - Not yet checked: `docs/designs/secrets-and-roles.md` decision 1 says the database password comes from a Docker secret file, but the app's own `db.connect()` still reads `POSTGRES_PASSWORD` from `.env`. That gap predates this change and is left as is.
3. **Monthly refresh: done 2026-11-12.** Run as the loader role. `nse_csv` now holds NSE's full equity list (`EQUITY_L.csv`, all series): 2633 rows. `upstox_master` holds 2757 rows. Next refresh due about 2026-12-12. The first run loaded only the constituents CSV (754 rows), and it was replaced.
4. **Call-site migration not started.** The reads in `ath_scan.py`, `enrich.py`, `collect/sources.py`, `symbol_sector.py`, `scripts/pull_upstox_5y.py`, `constituents.py` and `isin_resolver.py` stay on the current sources until `company_reference` has data.
5. **Name conflicts: reviewed, closed 2026-11-12.** `build_index` reports 3 name conflicts, each a pair of distinct securities that share one name: `FUTURE ENTERPRISES LTD` (FEL and FELDVR), `GACM TECHNOLOGIES LTD` (GATECH and GATECHDVR) and `JAIN IRRIGATION SYSTEMS LTD` (JISLDVREQS and JISLJALEQS). Each pair has its own ISIN. A name lookup on these names resolves to nothing, which is the intended result. Symbol and ISIN lookups still work.
6. **Class (c) names: reviewed 2026-11-12.** The earlier list had 37 distinct names. 14 are now found by normalised name in the full equity list. 23 are still missing from both sources (for example `Dar Credit & Capital Limited`, `Gammon India Limited`, `Ballarpur Industries Limited`). The cause is not established. Do not describe them as delisted. Check each one against the NSE and Upstox lists before using it.
7. **dotenv warning.** `could not parse statement starting at line 37` in `.env` is unchecked.
8. **Task registration.** The breakdown is not registered with `plan_add`, because tokenfrugal is not available. Any Haiku execution must be disclosed in the report.
9. Symbol master code references (2026-11-12): see docs/designs/home-events-filings-spec.md section 3.2.
