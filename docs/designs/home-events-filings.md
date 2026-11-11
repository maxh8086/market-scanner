# Home events: exchange filings (NSE and BSE)

Status: approved (confirmed by the user 2026-11-11). Owned rules and decisions follow the overview (sections 7 and 8). The build spec is [home-events-filings-spec.md](home-events-filings-spec.md) (revision 4, 2026-11-10). It holds the DDL, feed registry, dedupe key, run behaviour, config, module and file paths, tests and ordered tasks. Its review reports are in `docs/progress/home-events-filings-spec-review*.md`. Still open:

1. Approval of the spec: given 2026-11-11.
2. The NSE feed samples (spec T0): captured 2026-11-11 and met on the sample side. The parser-output comparison is part of T4e's acceptance.
3. The collector's token file path (spec 4.6): decided 2026-11-11 as `/run/app-keys/home_events_ingest_token`. T4d and T9 still wait on split-spec items (item 4) and the base URL (spec 4.6).
4. The collector-split spec's S1a, S3, S4 and S5a, and its migration numbers.
5. A keyword and precision/recall test plan for the deferred order-win feed.

## Open

- Build order is approved (overview section 7.7). This doc's approval was given 2026-11-11 with the build spec.
- Overview section 8.2 items 5, 6 and 11, and 8.1 item 4 (items 4 and 10 updated by the spec).
