# Home events filings spec: third review (revision 3 to revision 4)

Date: 2026-11-10. Subject: `docs/designs/home-events-filings-spec.md`.

**Method disclosure.** The six lenses (`egm-design`, `egm-codebase-details`, `egm-zoom-out`, `egm-comprehension`, `egm-implementation-readiness`, `egm-structural`) ran as fresh subagents. The `egm:egm-synthesizer` agent was not used: I compiled this synthesis myself from the six reports. Treat it as a single-author synthesis.

## Verdict

All six lenses returned findings; none said the design is unsound. The implementation-readiness lens found five blockers (interfaces that could not be tested as written); all are fixed in revision 4. The zoom-out lens raised a scope question that only you can answer (below).

## Applied in revision 4

| Area | Finding | Fix |
|---|---|---|
| Readiness | No injected clock, so the run deadline was untestable | `clock` injected into `fetch_feed` and `run_cycle` (5.1, 6) |
| Readiness | `feeds` and `parse_fn` not injectable, so T4b/T4c depended on T4e/T7 | Both injected (6) |
| Readiness | `FetchResult` outcomes undefined | `ok`, `blocked`, `transient`, `fatal` mapped from `classify_response` (5.2, 6) |
| Readiness | TypeScript file contract missing | Named files and signatures in section 6; T5a/T5b/T5c split in section 9 |
| Readiness | T4d and T9 waited on an undecided token path | Recorded in section 2 and 4.6; T4d and T9 depend on it |
| Design | Rows rejected by the API were silent (`ok` with `new=0` forever) | `invalid > 0` ends the run `failed` (5.2) |
| Design | One wrong URL answered with 403 pauses all NSE | Paragraph in 5.2; T0 must fetch every URL; T9 depends on T0 |
| Design | 4.4 claimed duplicates that may not exist | Caveat added; T0 checks the two `results` feeds |
| Design | Registration migration leaves a placeholder cron | T9 sets cron and mode together (4.1, 9) |
| Design | T9 missing T2b | Added |
| Design | 285 s run plus container start had a thin margin | Watchdog request raised to 330 s (5.3, section 2) |
| Codebase | `db.connect(**kw)`, `dsn()`/`_check_dsn_agrees`, `migrate.py` imports `db` | Section 3 and 4.5 corrected; parameter named `target` |
| Codebase | `pgschema.create` calls `apply()` with no arguments | Default stays "main"; a must-not-change guard on T2a |
| Codebase | `eventsPoolConfig()` missing; `config.ts` ignores overrides | Added to 4.6 and T5c |
| Codebase | `reset` after a mid-run cooldown | Skipped (5.1 step 5) |
| Codebase | S8 also claims a migration number; four stale "filings spec 4.7" citations in the split spec | Section 2 table rows |
| Structure / comprehension | Stale Q3 line, build-order contradiction, undefined Z/D/T tags, legend gaps, "its tests" ambiguity | Fixed in the header, legend, section 2, section 9 |

## For you to decide (not applied)

1. **Reopen D8/D9?** The zoom-out lens says a `home_events` table in the main database, written by `HomeFilings` through the existing writer pattern, removes T2a, T2b, T5a, T5b, T5c and T6: about 12 tasks become about 7. The cost is that the separate-database isolation and the "only the API touches it" rule go away. You decided D8/D9 on 2026-11-10; this is raised, not applied.
2. **Optional simplifications:** drop the cooldown mid-run re-read and the 30 s request retry; drop the start-feed rotation and per-feed deadline accounting; defer `ingest_floor_days` and `date_future`; move 4.3a, 4.4 and 4.7 out of this spec and remove the moot D4, D5 and D6b; poll the two quarterly feeds less often than every 5 minutes.
3. **Single-feed 403:** keep it as `blocked` (exchange-wide cooldown, conservative, proposed) or make it a plain `fail`.

## Your answers (2026-11-10)

- D8/D9: keep as decided.
- Keep: cooldown mid-run re-read, 30 s request retry, start-feed rotation, per-feed deadline accounting, 4.3a/4.4/4.7 in this spec.
- Defer: `ingest_floor_days` / `date_floor` and `date_future` (applied in 4.3, sections 6, 7, 8, 10; pure tests 25 to 20).
- Single-feed 403: stays `blocked`.
- Quarterly feeds polling: explained, no decision yet; default is every 5 minutes.

## Still outstanding

- Parent docs (`home-events-filings.md`, overview 5.1, 7.3, 7.4, 8.1, 8.2, split-docs index) are stale; they are edited after your decisions.
- The split-spec session must be told: its four "filings spec 4.7" citations (4.2, the 4.6 table, S5a, S7), the S4 330 s request, the S8 migration claimant, and the S1a, S3, S4, S5a requests. This work does not edit its file.
- `fundamentals-trigger-spec.md` is not written.
- T0 needs a network path NSE accepts; NSE timed out and BSE returned 403 from this machine.
