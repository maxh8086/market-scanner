# Home event sources: six-lens re-review 2 (compiled)

Date: 2026-11-11. Target: docs/designs/home-event-sources.md and the four split docs at origin/main b5913e4. A re-review of the 2026-11-10 NOT READY verdict, after the blockers were partly answered and the design was approved on 2026-11-11.

Abbreviations: overview = home-event-sources.md; filings stub = home-events-filings.md; filings spec = home-events-filings-spec.md (rev 4); news = home-events-news-telegram.md; macro = home-events-macro-calendar.md; upstox = home-events-upstox-news.md; split = collector-split-spec.md.

## Verdict

NOT READY. The overview does not meet its own gate (section 8.1): items 3, 4, 5, 8 and 9 are still open or partly closed (overview lines 226-232), and 8.2 item 20 (line 255) still says approval waits for them, while line 3 says the design is approved. Only the filings split is buildable (filings spec rev 4 holds DDL, dedupe key, config, tests and tasks, and migration 001 exists), and even that is partly gated by T0 feed samples, the token file path and the split spec migration numbers. The news, macro and Upstox splits are not buildable. The top three things that stop a build are: (1) the approval record is contradictory and absent from the checked-in ledger (the one verified Blocker); (2) event_intake (002), news_events (003) and macro_events (004) have no DDL, and macro has no defined data path; (3) the split spec that owns the scheduler and cooldown still carries the old 15 min / 2 h / exchange_cooldown / 15-minute filings values against the overview's 3/6/15 and 15/60 min classes and the */5 filings cron.

## Status of the 2026-11-10 blocking items (1 to 10)

Majority of the six lens statuses. (V) = verified by the lens by Grep, Glob or read.

| Item | Status | Evidence |
|---|---|---|
| 1. Status and Still-open text false | partly closed | Overview line 3 says approved (2026-11-11, ledger item 13) with section 8 open, but line 255 says approval waits for 8.1 items 3 to 9, and lines 227 and 246 say the filings spec is "awaiting approval" while lines 3 and 9 say approved rev 4. Filings stub lines 3 and 5 still say "draft, not approved". execution-ledger.md lines 37, 89 and 101 still say not approved; no 2026-11-11 or Run 4 entry (V). Five lenses: partly closed; the zoom-out lens agrees. |
| 2. Licence stance self-contradictory | closed | Overview section 4 (lines 43-56) is one position plus 4.1; Upstox "blocked until written confirmation" (lines 45, 56, 88). No "allowed" wording for Upstox (V). Residual: line 55 admits the user's reading does not cover storing or scraping clauses (accepted risk); line 313 "FRED personal use is allowed" has no terms record. |
| 3. Split docs were stubs, no build specs | open (3 lenses: open; 3: partly closed) | Lenses disagree. Decided by the evidence: only filings has a spec (filings spec DDL lines 130-147, config 374-382, tests 392-404, tasks 413-432). News lines 128-138, macro lines 139-152 and upstox line 3 have none; overview line 226 admits it. Three of four splits remain unspecified, so the status is open for the set, partly closed only for filings. |
| 4. No events DDL | partly closed | home_events DDL at filings spec lines 130-147; db/events_migrations/001_home_events.sql exists, migrate.py has an events target (V). event_intake 002, news_events 003, macro_events 004 have no DDL (news lines 22, 107; macro lines 45, 143). Overview line 227 still says "awaiting approval". |
| 5. Shortlist join, dedupe key, BSE scrip map | partly closed | Filings dedupe key (filings spec 4.2 line 174) and ISIN join via symbol_sector (line 184) specified; BSE map deferred (Z2). News events carry free-text symbols (overview line 137), no alias source (news B7 line 147); Telegram dedupe key unspecified (news line 79); Upstox D3 open. |
| 6. Rate-limit and kill-switch policy | partly closed | Per-host table and "source paused" marker exist (overview lines 181-187); user replaced 15 min/1 h/24 h with API 3/6/15 min and other 15 min to 1 h. Gaps "Not set" for all non-NSE/BSE hosts (lines 185-187). Cycle budget stated for NSE only (line 245). split lines 69, 83, 84 still carry 15 min retry, 2 h cap, exchange_cooldown; ledger line 37 still says 24 h kill switch (V). |
| 7. Wrong data facts | closed (4 lenses closed, 2 partly closed) | CPIMEDSL only as "removed" (overview 94, 295; macro 72) (V). MoSPI 16:00 IST consistent (overview 252, 296, 301, 320; macro 82) but user-confirmed only, no MoSPI page (macro U1). mcap_cr matches scanner/fundamentals.py:38 (V). Disagreement: the technical lens notes overview line 199 cites fund_derive.py:195 where the key is market_cap_cr (lines 194-195), and filings spec line 172 defers mcap_cr entirely; that residue is carried as Major finding 15, not as a wrong fact. |
| 8. Dangling references | partly closed | Overview 5.1 to 5.5 exist; filings spec sections resolve (V). Remaining: line 191 cites "line 192"; line 178 cites 7.3 from inside 7.3; 8.1 item 8 (line 231) points to 8.2 items 6, 9, 10 (10 is the cycle budget; thresholds are 6 and 16); macro Open list cites stale lines (28, 50, 56, 72, 83, 137); macro line 76 cites 8.2 item 15, which lists none of RBI/Fed/FRED/BLS/MoSPI; upstox line 38 "line 49". |
| 9. Undefined thresholds | partly closed (3 lenses: partly closed; 2: open; 1: closed per wording) | Lenses disagree. Overview lines 160-161 and 8.2 item 6 (line 241) say "proposed, not decided" with owner (filings doc); item 16 (line 251) owner macro doc. No numbers and no due-by. Filings spec line 172 defers value_cr, pct_shares, mcap_cr so none can be applied. The deciding line is 241: owner assigned, value absent, hence partly closed. |
| 10. Missing governance | partly closed | Purge deferred with owner (8.2 item 4 line 239; filings spec line 312). Rejected rows: kept 30 days (overview lines 107, 121, 192) but line 193 says counts are "the only trace". "Critical" retention: 3 years flat (7.4), 8.2 item 5 (line 240) still open. Telegram unconfirmed-update retention unchecked (line 207, 8.2 item 2). No job named to purge event_intake terminal rows. |

## Overview gate (section 8.1, items 3 to 9)

Items are numbered as in overview 8.1 (lines 224-232).

- Item 3, split docs lack build specs (line 226): open. Closes when news and macro have a build spec in the style of filings spec sections 4 to 9, or 8.1 says news and Upstox specs are deferred to their phase. Write macro first.
- Item 4, events DDL and dedupe key (line 227): partly closed. Filings closed (rev 4 and migration 001); text still says "awaiting approval". Closes when 002 to 004 DDL exists and line 227 is corrected. The BSE scrip map stays deferred (Z2).
- Item 5, shortlist join and related (8.1): partly closed. Filings join by ISIN specified; news and Telegram have no join or Telegram dedupe key. Closes with an alias source (news B7) and a Telegram dedupe key.
- Item 6, wrong data (line 229): effectively closed. The item claims split docs still carry old values; they do not (macro lines 71-72, 82, 118-119). Mark it closed and keep only the stale line cites.
- Item 7, stale numbers (line 230): effectively closed on the same evidence; re-check 8.2 item 14.
- Item 8, undefined thresholds (line 231): open. Cites the wrong 8.2 items. Closes with correct refs (6 and 16) and values or a "needed before" gate (for example order-win feed).
- Item 9, governance (line 232): partly closed. Rejected-row text at line 193, "critical" retention, Telegram retention and the intake purge job remain.

What closes the gate as a whole: record the approval as waiving or keeping each of items 3 to 9 (Blocker 1), reconcile 8.1, 8.2 item 20 and the ledger.

## Blockers (verified)

1. docs/designs/home-event-sources.md lines 3 and 255 (also 8.1 lines 224-232), and docs/progress/execution-ledger.md lines 37, 89, 101. Defect: approval status is contradictory and the cited approval record is absent. Evidence: line 3 says "design approved by the user (confirmed 2026-11-11, ledger item 13)" with section 8 blockers open; line 255 says "Approval of this overview waits for items 3 to 9 in section 8.1"; ledger line 37 says "Not approved", line 89 "gated: design approval", line 101 "still not approved"; Grep for 2026-11-11 and Run 4 in the checked-in ledger (origin/main) found nothing. The record exists in the uncommitted main-checkout ledger at docs/progress/execution-ledger.md, line 161 ("Run 4 (2026-11-10): design approvals recorded") and line 165 ("Item 13 (home event sources): design approved by the user"). That record is dated 2026-11-10, while overview line 3 says 2026-11-11; the two dates conflict and the approval commit must settle one. Verdict: confirmed (verifier rated it Blocker because the design gate in CLAUDE.md depends on this status and a false "approved" could let the loop dispatch unapproved work). Fix: record one dated approval sentence stating exactly what was approved and which of 8.1 items 3 to 9 were waived; rewrite item 20 as waived or live, not both; update ledger row 13 in the same commit. Blocker-severity lens entries cite it. The zoom-out lens rated it Major. The verifier confirmed the comprehension lens instance as Blocker 1, and the other instances are merged into it.

## Majors

Each item gives doc:line, defect and fix. All are from lens reports.

1. Filings spec approval is stated three ways (downgraded from Blocker). Overview 3 and 9 say approved; overview 227 and 246 and filings stub 3 and 5 say "awaiting approval" or "draft, not approved"; filings spec line 3 says approved and also "No task may be dispatched from this spec until the user approves it"; spec line 466 lists overview edits as still to do. Fix: set all to approved 2026-11-11 rev 4 (one date: ledger line 105 says 2026-11-10), delete the contradicting sentence, and say which of T0, token path, S1a/S3/S4/S5a still gate which task.
2. Macro data path undefined (downgraded from Blocker). Macro line 35 stages raw RBI/Fed/MoSPI items in event_intake (002, news-owned, built after macro); macro line 42 "raw-item route: open"; overview 6.3 route table has no macro intake route; overview line 110 still names macro in the LLM relevance criteria; line 236 stance open. Verifier: v1 path (hand-seeded rows plus FRED via POST /internal/events/macro, macro doc line 41, overview 214-215) works without intake or the LLM, so only post-v1 raw items are undefined. Fix: state macro writes directly with a rules parser in 6.3 and the macro doc, drop macro from 6.1 criteria for v1, or add the route.
3. Cooldown and scheduler values conflict across docs (downgraded from Blocker). split 69 (15 min retry), 83-84 (exchange_cooldown, "15 min doubling to 2 h"), 17 and 198 (filings every 15 min) versus overview 178 (*/5), 181 (3/6/15 and 15/60, source_cooldown) and filings spec 115-116 (*/5); filings spec line 466 cites 3 h versus 2 h; overview line 181 "3, 6, then cap 15" is ambiguous; macro, news and upstox repeat the classes. Verifier: stale wording already tracked as a change request in collector-split-spec-requests.md lines 17 and 29. Fix: update split 4.3, 4.3a and the retry rule; make overview 7.3 the single copy of classes; write the doubling sequence explicitly; fix ledger row 13 "24 h kill switch".
4. News/Telegram doc has no build spec (downgraded from Blocker). news 22, 107, 128-138: no columns, status set, config, env names, modules, fixtures or acceptance command; B1, B5-B9, M3-M17 open (lines 144-160). Fix: write the phase 1 spec before any dispatch; defer until that phase.
5. Macro doc has no build spec (downgraded from Blocker). macro 139-152: no macro_events DDL, config, cron (line 124), modules, India CPI job spec or acceptance; B2-B5, M1-M10 open. Fix: write it next in build order.
6. event_intake (002), news_events (003), macro_events (004) have migration numbers and routes but no DDL, source values, unique key or status CHECK (overview 121-136; news 22, 107; macro 45). It gates three docs. Fix: write the event_intake DDL first.
7. Queue status set lacks prefiltered_out. Overview 103-107 step 3 uses it; 6.3 line 121 and news PATCH route line 31 list new, processing, kept, rejected, expired only; re-poll would re-queue. Fix: add as terminal status with 30-day retention, or state such items are not inserted.
8. Rejected-item retention contradicts itself: overview line 192 (30-day terminal rows; also 107, 121) versus line 193 ("not stored... counts are the only trace"); line 191 cites "line 192". Fix: reword 193, cite the section.
9. Macro facts held in two docs with diverging copies. Overview 295-312 versus macro 89-97: four rows versus five (macro 95 adds US CPI Nov data) while macro line 110 and C4 say four; macro line 89 "US row for October data is today" is stale (10 Nov, today 11 Nov) and breaks the line 150 test; macro M13 (line 170) asks which governs. Fix: one owner (decisions file C recommends the macro doc), pointer in the other, reconcile rows, drop past row.
10. Keyword and prefilter ownership misplaced. News 9.2 list owned by filings doc, whose stub has none (news 81-83, 147; overview 27, 247, 279-285); RBI filter list in 5.5 differs from 9.2 (macro N5); order-win list in 9.1; Telegram prefilter bypass open (B7). Fix: one named owner doc per list and the match field.
11. LLM relevance and Home priority depend on an undefined event-tier list. Overview 110, 158-162 versus filings spec 16 (tier is a code constant) and 445 (D6a open). Fix: add a type-to-tier table in 7.1 or use type names.
12. LLM contract carries stance that C4 removed, and category is undefined. Overview 106 (step 4 JSON), 236, 293; 215 (C4); news 92. Fix: remove stance from v1 or decide it; define the category enum.
13. Telegram laptop-only hosting depends on an unchecked fact. Overview 205-207, 237; news 60-63, 146: retention of unconfirmed getUpdates items unchecked, delete rights undecided, 48-hour windows add coupling. Fix: record the Bot API figure and the loss rule in 7.6.
14. Per-host request gaps "Not set" for Investing.com, CNBC TV18, RBI, Fed, FRED, BLS, MoSPI, Upstox (overview 185-187, 244); cycle budget only for 8 NSE feeds. Fix: set defaults or assign an owner and forbid build before.
15. mcap_cr approved but in no table. Overview 199-201, 161, 11; filings spec 172 (Z3: "no table has mcap_cr today"); overview cites fund_derive.py:195 where the key is market_cap_cr (lines 194-195; fundamentals.py:38, conclude.py:51, significance.py:131 use mcap_cr). Fix: state the name applies when the column is added, name migration owner, cite fund_derive.py:194, note order-win ratio is out of the first build.
16. Terms gate for RBI, Fed, FRED, BLS, MoSPI points at a list that omits them: overview 250 (item 15), 47-56 (4.1), 313 ("FRED personal use is allowed", no source); macro 76, 169 (M10). Fix: add the hosts to 4.1 and item 15, or record the user's acceptance; drop "is allowed".
17. LLM verification set does not test the component. Overview 151-152 ("30 real filings from the opt-in sample") versus 6.1 (news and Telegram headlines; filings skip staging, 122); "opt-in sample" undefined; 8.2 item 13 and news M7 (line 152) still open; 30 items cannot show 0.90 recall. Fix: state population, labeller, positive count, or set a miss count.
18. Order-to-mcap threshold called open although scanner/significance.py:26-32 (MCAP_BANDS 50/25/10/2), 135 and 184 already implement it; not cited (overview 160-161, 241; filings spec section 3). Fix: cite it and decide adoption.
19. India CPI (Q8) has conflicting records. Overview 296 and 8.2 item 17 (line 252): ingested by a job, decided; overview 215 (C4): hand-seeded; macro 49 ("C5, open"), 83, 145, 158 (B4), 163 (M4) still open; decisions file C5 recommends hand entry; job spec unwritten. Fix: one answer; zoom-out lens suggests cutting the job from v1.
20. Decision tags collide and have no key: overview C5 (price-impact tracking, line 215) versus macro C5 (India CPI job, lines 49, 158); C12, C10, A, B, D, M, Z, Q codes undefined; filings spec reuses Q1-Q4 (overview 41, 66, 215, 248). Fix: add a tag key with file prefixes.
21. Six ingest routes and token roles specified for sources that are OFF or unbuilt (overview 6.3 table 138-147; news 24-33). Fix: keep the filings route, write others when each phase is next.
22. Order-win, back-to-back and order-to-mcap rules and the 9.1 reconciliation of about 25 keywords are specified for a deferred feed (overview 66, 160-161, 259-275; filings spec 172). Fix: move to a deferred block and remove from the blocking list.
23. Cooldown rows requested for nine or more hosts plus ensure_source_row for arbitrary Telegram link hosts (overview 181, A9) before those sources exist; page-fetch safety open (news B8). Fix: rows only for built sources.
24. Filings is only partly startable. Filings spec 415 (T0 not a local-model task), 425 (T4d needs token path 4.6), 429 (T5c needs index.ts and kiteToken.ts committed or stashed), filings stub 6-9. Startable: T3a-T3c, T4a-T4c, T5a, T5b, T6 (T2a merged). Fix: state the first dispatch set and an owner and date for T0 and the token path.
25. News open list carries settled items as open and stale cross-refs: news 144-160 (M3, M4 "settled by A2/A3"; M14 settled by A5; B1 versus overview 217; M7); header "Updated 2026-11-10". Fix: move to a Settled list.
26. Macro doc scope far exceeds approved cut C4: about 20 open items, routes /internal/events/macro, /api/macro, /api/calendar, stance, alerts, RSS filters, trading-day calendar (macro 3, 139-178; overview 215). Fix: define v1 as a seed file plus one route.
27. Overview ownership claims are untrue. Overview line 11 and section 2 (lines 18-30) say the filings doc holds the events table, keyword rules, retention and market cap field; the stub (14 lines) holds none and the values are in overview 7.4, 7.5, 9; line 123 and the 002 table owner disagree. Fix: add a "where the value lives today" column.
28. "Critical event" has two statuses: defined as tier 1 and 2 (overview 38, 162, 232) but 8.2 item 5 (line 240) says undecided; 7.1 gives no retention period. Fix: define once, narrow item 5 to impact tracking.
29. Upstox doc is a blocked stub: upstox 3, 11-14, 30-34, 58-60; endpoint and shape live only at commit 729e093; UpstoxClient._get does not expose an HTTP status for cooldown handling (see Minor 9). Acceptable by design; do not count against first build.

## Minors and nits

Minors
1. Overview 229-230 (8.1 items 6, 7) say split docs still carry old values; they do not. Mark closed.
2. Overview 214 versus 217: build-order bullet superseded but not edited. Write one order: filings, macro, news phase 1, LLM, Telegram, Upstox.
3. Overview 231 (8.1 item 8) cites 8.2 items 6, 9, 10; should be 6 and 16. 8.1 has 9 items versus the re-review's 10: add a mapping.
4. Overview 3, 17, 301, 320 use "section 8" without sub-section; glossary (32-41, 87) omits collector, Fastify, cooldown, opt-in sample, run deadline.
5. Filings stub 1-14 is stale ("draft, not approved", missing item 1) and gives no decided/open/owner view.
6. Upstox 21-28, 38: dense decision-code prose hides the single blocker.
7. Overview 83: "751 rows, all with an ISIN" unsupported; symbol_sector.isin is nullable (025_symbol_sector.sql:9); 751 is a candle count (handoff.md:298).
8. Overview 163, 202-203 list "tier" as an event field; home_events stores feed_tier only (filings spec 130-145).
9. Overview 84-87 versus scanner/upstox.py:269-297: _get retries 429 internally and raises a string error with no status; cooldown trigger on 403/429 needs a code change recorded in the Upstox spec.
10. FREDAPI_KEY (overview 94, 313; macro 73, 164) appears in no non-doc file; M5 leaves .env versus secret store open.
11. Overview 269-272: "only in factors.py" list omits CONTRACT WIN (factors.py:72); LETTER OF INTENT line 70.
12. Overview line 123 versus 125-135 and news 22, macro 36, 57: table ownership wording differs (002/003 news, 004 macro).
13. No job or owner purges event_intake terminal rows after 30 days (overview 121, 191-193, 239; filings spec 310-312).
14. Overview 5.4 (79-88) holds a full Upstox design while the Upstox stub removed it; duplicated. Reduce to a pointer.
15. Overview 7.5 (197-201) fundamentals tables paragraph is not a Home concern; fundamentals-tables.md exists.
16. Filings spec line 11 uses "my default" and "Your approval" wording; spec line 466 lists overview edits already made.
17. Thresholds and gaps (overview 241, 251, 244) have owners but no "needed before" gate or date.

Nits
1. Line-number cross-references are brittle and stale: overview 191; macro 156-173; upstox 38, 49.
2. Overview 87 "as in the fundamentals doc" names no file.
3. Missing blank lines before headings at overview 56-57, 117-118, 164-165, 296-297; line 138 run-in; section 4 has a single subsection.
4. Overview 178 cites section 7.3 inside 7.3; lines 178 and 181 are very long single paragraphs.
5. The overview "held here" mechanism duplicates every value in two places (lines 18-30).
6. Macro Open items keep settled entries and cite an older revision (macro 156-173).

## Split readiness

| Split doc | Buildable | Why |
|---|---|---|
| home-events-filings.md with home-events-filings-spec.md rev 4 | yes, partly | Spec has DDL (130-147), dedupe key (174), config (374-382), tests (392-404), tasks and acceptance commands (413-432); T2a merged, migration 001 exists. T3a-T3c, T4a-T4c, T5a, T5b, T6 can start. T0, T1 (migration number), T4d, T4e, T7, T9 wait on NSE samples, token path, S1a/S3/S4/S5a. The stub's status text is stale. One lens (comprehension) said no because the pointer is stale and approval is stated inconsistently; the majority says yes. |
| home-events-news-telegram.md | no | No DDL, config, modules or acceptance (22, 107, 128-138); about 15 open decisions; no LLM contract; Telegram retention unchecked. |
| home-events-upstox-news.md | no | Stub by design; blocked by licence and terms gates and no sample (3, 30-34, 60). |
| home-events-macro-calendar.md | no | No macro_events DDL, config, cron, modules or CPI job spec (139-152); data path through event_intake has no route; calendar rows stale and inconsistent. Next in build order, so write next. |

## Refuted or downgraded candidates

No candidate was refuted or unverified. Eight were downgraded to Major and appear above as Majors; one approval candidate was confirmed.

- Architecture lens Blocker "Approval status contradicts itself" (lines 3, 226-227, 246, 255): downgraded. Verifier: the contradiction and missing ledger record are real, but it is a documentation inconsistency and the user's approval is stated at line 3; the ledger is probably stale. The same defect reported by the comprehension lens was confirmed as Blocker 1 (verifier reason: the design gate depends on this status). Kept as Blocker 1 only on that confirmed instance.
- Architecture lens Blocker "Macro data flow and build order circular": downgraded to Major 2. Verifier: v1 uses hand-seeded rows and FRED through the direct macro route, not intake or the LLM, so nothing blocks the first build; only post-v1 raw items are undefined.
- Architecture lens Blocker "Scheduler rule conflicts with overview cadence and cooldown classes": downgraded to Major 3. Verifier: split spec wording is stale but already tracked in collector-split-spec-requests.md (lines 17, 29); decisions are recorded.
- Comprehension lens Blocker "Filings spec approval stated three ways": downgraded to Major 1. Verifier: stale status wording with a mechanical fix; does not break a design decision.
- Build lens Blocker "News/Telegram doc cannot be built from": downgraded to Major 4. Verifier: staged gap in a doc that openly defers to a build spec; nothing is wrongly specified.
- Build lens Blocker "Macro doc is a stub": downgraded to Major 5. Verifier: labelled a stub; filings builds first and does not depend on it; the missing items mostly await user decisions.
- Structural lens Blocker on approval (lines 3, 255, 8.1 numbering): downgraded. Verifier: line 3 discloses the open blockers; documentation inconsistency. Merged into Blocker 1 and Minor 3.
- Structural lens Blocker "Filings spec status contradicts itself": downgraded to Major 1. Verifier: stale wording, blocks no build task.

## Open questions for the user

Current state from the docs.

- Q1 Keep the Telegram bot: answered, kept (rereview.md line 75; overview 216, 7.6). Follow-ups open: delete rights and unconfirmed-update retention (8.2 item 2).
- Q2 Keep the LLM stage with a 30-item set: answered, kept (rereview.md 76; overview 99, 151, 216). The set's population (filings versus news headlines) and labeller are undefined (Major 17; news M7).
- Q3 Kill-switch cooldown 15 min, 1 h, 24 h: answered with different values: API 3/6/15 min, other 15 min to 1 h (overview 181), superseding the interim 3 h cap (rereview.md 77). Not accepted as asked; split spec and filings spec not yet updated.
- Q4 Cuts C3 to C6 and build order: answered, approved (rereview.md 78; overview 214-215). Build order superseded for news by A5 (217) without editing 214.
- Q5 MoSPI 16:00 IST: answered, user-confirmed (rereview.md 79; overview 296); no MoSPI page confirms it (macro U1; 8.2 item 17).
- Q6 Drop CPIMEDSL: answered, dropped (rereview.md 80; overview 295). FRED pass condition still open (8.2 item 16).
- Q7 mcap_cr: answered as a name only (rereview.md 81; overview 199); no events table carries it (filings spec 172, Z3); no owner or migration.
- Q8 India CPI hand entry or job: answered "job" (rereview.md 82; overview 252, 296) but contradicted by C4 (215) and by macro 49, 145, 158, 163 (still open). No single record.

Additional unanswered items from the lenses: which of 8.1 items 3 to 9 the user waived on 2026-11-11 and where it is recorded; whether macro goes through event_intake and the LLM; which doc owns macro facts; per-host gaps for non-NSE hosts; the event-tier list (D6a); whether stance is in the v1 contract.

## Path to READY

1. Record the 2026-11-11 approval in the ledger (row 13) and overview with scope and waived items; rewrite 8.2 items 11 and 20, 8.1 item 4, and the filings stub status; use one approval date.
2. Resolve the filings first-build gates: T0 samples, token file path, migration numbers, S1a/S3/S4/S5a; state the first dispatch set.
3. Update collector-split-spec to source_cooldown, the 3/6/15 and 15/60 classes and per-source cron; make overview 7.3 the single copy of the numbers.
4. Decide macro's data path (direct write with rules parser, no staging) and the India CPI answer; write the macro build spec with DDL, config, calendar rows (one owner, four or five rows, no past row).
5. Write event_intake DDL (002) with the full status set including prefiltered_out and a purge owner; then 003 and 004.
6. Fix the internal contradictions: line 193 retention, 214 versus 217 build order, 8.1 cross-refs, critical-event status, decision-tag key, stance and category, event-tier list.
7. Verify the Telegram retention figure and record the loss rule; add RBI/Fed/FRED/BLS/MoSPI to the terms gate; set per-host gaps or mark them owned.
8. Define the LLM test set population and labeller; settle mcap_cr ownership and cite scanner/significance.py for thresholds.
9. Defer or trim: news and Upstox specs until their phase, six-route table, order-win and fundamentals paragraphs, Upstox 5.4 duplicate.
10. Re-review.

## Method

Six fresh lens subagents (design, codebase-details, zoom-out, comprehension, implementation-readiness, structural lenses; the lens reports in the input are labelled architecture and design soundness, technical accuracy, simplicity and scope (zoom-out), comprehension, build readiness and structural), one skeptic verifier per blocker candidate (nine candidates: eight downgraded, one confirmed), and one synthesizer (this report). The synthesizer used no sub-agents. Findings were deduplicated by document and line; a Blocker stands only where its verdict was confirmed (one: the comprehension lens approval candidate), downgrades became Majors. No design doc was edited.
