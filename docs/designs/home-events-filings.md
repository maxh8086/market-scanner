# Home events: exchange filings (NSE and BSE)

Status: draft, not approved. Owned rules and decisions follow the overview (sections 7 and 8). The build spec is [home-events-filings-spec.md](home-events-filings-spec.md) (revision 4, 2026-11-10). It holds the DDL, feed registry, dedupe key, run behaviour, config, module and file paths, tests and ordered tasks. Its review reports are in `docs/progress/home-events-filings-spec-review*.md`. Still missing before any build:

1. Your approval of the spec. No task is dispatched before it.
2. The NSE feed samples (spec T0): URLs, tags, date format and feed depth for 4.0.
3. The collector's token file path (spec 4.6), needed by T4d and T9.
4. The collector-split spec's S1a, S3, S4 and S5a, and its migration numbers.
5. A keyword and precision/recall test plan for the deferred order-win feed.

## Open

- Build order and approval for this phase. Build order is approved (overview section 7.7); this doc's approval waits for the build specs.
- Overview section 8.2 items 5, 6 and 11, and 8.1 item 4 (items 4 and 10 updated by the spec).
