# Home event sources: six-lens re-review (compiled)

Date: 2026-11-10. Targets: `docs/designs/home-event-sources.md` (overview) and the four split docs `home-events-filings.md`, `home-events-news-telegram.md`, `home-events-upstox-news.md`, `home-events-macro-calendar.md`. Lenses: design, codebase-details, zoom-out, comprehension, implementation-readiness, structural. Items marked (V) were checked against the files.

## Verdict: NOT READY

The overview holds up as a record of decisions. It is not an approvable design. The splits are stubs, the overview contradicts itself on status and licence, and nothing is buildable (no DDL, config, or owner paths).

## Blocking items

1. **Status and "Still open" are false (V).** Overview line 3 says "review blockers answered" and line 270 says "Still open: None", but lines 272-288 list open items (blocker 4 reconciliation, keyword reconciliation). Fix: rewrite line 3 and line 270 to list the real open items, and set Status to "draft, not approved".
2. **Licence stance is self-contradictory (V).** 4.1 and 4.2 quote prohibitions with no carve-out. Section 5 item 2 (line 173) says the user reads the terms as allowing personal use. Line 276 says Upstox is "allowed", while 4.5 (line 135) says "blocked". Fix: one "Licence position" paragraph in section 5: terms prohibit storing and scraping, the user accepts the risk for personal use, and Upstox is blocked until written confirmation. Delete the "allowed" wording at line 276.
3. **Split docs are stubs (V).** Each split's line 3 says "Build specs are not written yet". Implementation-readiness found none of the four buildable. Fix: before approval, each split needs events or series DDL, config keys with defaults and units, env var names, owner module paths (scanner/, server/src, ui), test counts and fixtures, and the acceptance command.
4. **No events DDL anywhere.** Missing: table name, types, keys, indexes, and the company, tier and event-type fields required by Q5 (line 240). Fix: write it in the filings spec first, since the other sources reuse it.
5. **No shortlist-to-event join or dedupe key.** The BSE scrip code to symbol map is undefined. Fix: specify the mapping table and the dedupe key (source, source id, or hash) in the filings spec.
6. **Rate-limit and kill-switch policy is inadequate.** Line 287: a 24 h stop after 3 failures defeats the "alerts within minutes" goal (line 174). 16 NSE/BSE requests at 5-8 s is about 2 minutes of a 5-minute cycle, and the other sources have no per-host policy. Fix: replace with a cooldown of 15 min, then 1 h, then 24 h, with a visible "source paused" marker. Add a per-host table covering Upstox, RSS, RBI, Fed, FRED and BLS, and state the cycle budget.
7. **Wrong or contradictory data facts.**
   - FRED `CPIMEDSL` (line 285) is medical-care CPI, not headline inflation. Remove it, or justify it.
   - MoSPI release time: the overview has 16:00 at line 284 and "do not show a time" at line 308. The macro doc line 13 states 4:00 PM as fact (V). Fix: pick one, and mark it unconfirmed until MoSPI confirms it.
   - Market cap name: line 175 says `market_cap_cr` and line 281 says `mcap_cr`. Use `mcap_cr` in both, and the column is named in the DDL.
8. **Dangling and stale references (V).**
   - Sections "5.1" to "5.6" do not exist, because section 5 is a numbered list. They are cited in the overview and in filings (lines 14, 16, 18), news-telegram (10, 14, 15), and macro (13, 20). Fix: promote the items to `###` headings, or cite "section 5, item N".
   - Upstox doc line 7 cites "open item 15", which does not exist.
   - Overview line references (lines 35, 132, 223, 278) are stale. Cite sections instead.
9. **Undefined thresholds.** Significant insider trade, order-to-mcap ratio, back-to-back wins, the macro alert lead times, and the FRED pass condition are all missing. Fix: put the numbers in the relevant split doc, or mark them "to be set before build".
10. **Missing governance rules.** There is no purge job owner or spec, and "critical" retention (line 35) is meaningless as written. Rejected rows are kept only as counts (line 58), so recall is unauditable. Telegram's retention of unconfirmed updates is unchecked. Fix: assign each to a spec, or cut the feature (see the cuts below).

## Should-fix

- Section 7 is titled "brainstorm, answered 2026-11-09" but holds 2026-11-10 decisions. Q1 and Q2 are missing. Section 4.5 sits before 4.3 and 4.4. Renumber.
- "Tier" means three things (the user's tiers, the feed tiers, the keyword tiers). Rename the keyword tiers "keyword level A/B/C" and add a glossary entry.
- Stale wording: "met or failed" at line 246 (the decision was "beat / miss / in line"). Line 161 meta-comment "the old 3.3 reference". NSE/BSE "not decided" at line 102 and macro placement "not decided" at line 146, both already decided.
- The LLM stage reads "Decision" in section 2 but "proposed" in the news doc. Align.
- No glossary. Undefined terms: ATH, UPTREND, Priority 1-3, intake queue, analytics token, "blocker N", "six-lens re-review".
- Duplication: the overview carries substance that belongs in the splits. Add a split-doc index, and give each rule (request policy, retention, keyword lists) one owning doc. Add Owner and Screen lines to the splits.
- Pseudo-headings in sections 2-3 should become real headings.
- Filings: map the 14 feed URLs to fields, fix the keyword lists, and specify NSE cookie and header handling, the backoff numbers, and failure behaviour.
- News: specify the LLM prompt, timeout, retry, malformed-JSON handling, and an injection defence, and add the queue DDL.
- Upstox: add batch-failure handling and verify the rate numbers.
- Macro: add the series table, RBI and Fed poll cadence, a decision on India CPI ingestion (hand entry suggested), and the alert lead times.
- Name a trading-day calendar source.

## Zoom-out cuts (decisions for the user, not applied)

- C1. Drop or defer the LLM pipeline (queue, expiry, batch worker, model_id, 100-item labelled set with precision and recall gates). Use a keyword prefilter plus a watchlist test. If kept, use a set of about 30 real filings.
- C2. Drop or replace the Telegram bot. It has no delete rights and the 48 h delete window adds no value.
- C3. Move the fundamentals tables (5.4) and the keyword reconciliation (6.1) out of this design.
- C4. Macro: seed the 4 calendar rows by hand, use FRED `CPIAUCSL` and `FEDFUNDS` only, and drop RBI priorities 2-3, the speeches feed, and stance extraction.
- C5. Defer the 30-day price-impact tracking.
- C6. Build order: filings, then macro (4 rows), then RSS keyword-only. Telegram, LLM, and Upstox later or never.

## Open questions for the user

1. Keep the Telegram bot, or drop it (C2)?
2. Keep the LLM stage, or defer it (C1)? If kept, is a 30-item test set acceptable?
3. Accept the kill-switch cooldown change of 15 min, 1 h, 24 h (item 6)?
4. Approve cuts C3-C6 and the build order?
5. MoSPI release time: 16:00, or stay unconfirmed?
6. FRED: drop `CPIMEDSL`?
7. Use `mcap_cr` in the events table (recommended)?
8. India CPI: hand entry, or an ingest job?

## Path to READY

Resolve the blockers above and answer the open questions. Then write the filings spec (DDL, config, tests) and re-review it before dispatching any task.

## Conflicts resolved 2026-11-10

1. Upstox poll cadence: once a day. Section 7.3 now names it as the one exception to the 5-minute and hourly schedule.
2. Exchange feed count: 14 active feeds (9 NSE, 5 BSE). The overview's "15" was an error. The "16" in blocking item 6 counted the 2 parked feeds. The cycle budget is settled at 70 to 112 seconds of gaps per 5-minute cycle.
3. Order-win matching: as `matches_orderbook` in `scanner/factors.py:828-847`. Exclude by description; match by exact description category, or by an attachment-text keyword substring. The filings doc's "attachment text only" rule was wrong and is corrected.

## Answers recorded 2026-11-10

1. Telegram bot (C2): kept. Rate it as in scope, not dropped.
2. LLM stage (C1): kept. A 30-item test set is accepted (instead of the 100-item labelled set).
3. Kill-switch cooldown: 15 minutes for the first pause, doubling on each further failure, capped at 3 hours. This replaces the 24 h kill switch and the 15 min / 1 h / 24 h proposal.
4. Cuts C3, C4, C5, C6 and the build order (filings, then macro, then RSS keyword-only; Telegram, LLM, Upstox later): approved.
5. MoSPI India CPI release time: 16:00 IST, confirmed by the user.
6. FRED CPIMEDSL: dropped. Reason given by the user: it is not headline inflation. Its series is the medical-care component of CPI. Use CPIAUCSL for headline CPI.
7. Market cap column in the events table: mcap_cr, approved.
8. India CPI ingestion: ingest job, not hand entry.

Design status is unchanged: the overview is still not approved. The blockers listed above still need the overview rewrite and the filings spec before approval.
