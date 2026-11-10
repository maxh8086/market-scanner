# Review: docs/designs/home-event-sources.md

Date: 2026-11-10. Mode: EGM default review (six Goldfish lenses, then synthesis). Documentation only. The design file was not edited.

## 1. Status conflicts

1. Line 3 says "brainstorm in progress. Not approved", while section 7 records final decisions and ends with "Still open: None". **Closed 2026-11-10:** line 3 now reads "decisions recorded ... Not approved: awaiting the six-lens re-review and the user's approval." Approval itself is still open.
2. Section 4.1 line 102 says "Status: not decided". Section 5.2 says resolved, and section 7 says option (a) decided on 2026-11-09.
3. Section 7 "Still open: None" conflicts with items that are still open:
   - Upstox terms check (4.5), which blocks that source
   - Telegram unconfirmed-update retention (section 7)
   - NSE and BSE rate limits (4.1, 7)
   - MoSPI release time (8.2.3)
   - Market cap column name and DDL (5.4)
   - Order-win keyword reconciliation with `factors.py` (5.5)
   - FRED series IDs (4.3)
4. Section 1 row 6 says "to confirm", while 5.4 says the refresh rule is decided.
5. Section 1 row 7 (Upstox News) says "proposal open for review", with no matching entry in section 7.
6. Section 7 jumps from Q3 to Q5. Q1 and Q2 appear only in section 1.
7. Beat/miss wording: 5.1 uses "beat / miss / in line, per news". Section 7 says "met or failed".
8. RSS OFF by default (section 7 Q3, 4.5) conflicts with the 5.3 "alerts within minutes" freshness goal when the laptop is off.
9. Retention: 2.1 keeps all relevant rows, including source_url and reason, "for future use". Section 7 keeps only tier 1 and 2 critical events, and says titles and links are not kept long term.
10. Dangling reference in 4.3 to "3.3", which does not exist. Section 4.5 sits before 4.3 and 4.4.

## 2. Brainstorm-complete verdict

NOT complete. Most questions in sections 1-6 have decisions, but "Still open: None" is false. Seven items are neither answered nor explicitly deferred (list in 1.3). Items 1.4 and 1.5 are unresolved status lines. The retention rule (1.9) is a design contradiction, not just a status issue.

## 3. Findings by lens

### egm-design
- Major: the licence stance is contradictory. 5.2 says the terms are "open for personal use", while 4.1 and 4.2 say storing and scraping clauses apply. There is no mitigation (kill switch, backoff, user-agent and rate policy). NSE rate limits are unchecked.
- Major: the LLM pipeline has no capacity or cost estimate, no prompt-injection defence for untrusted headlines, and no JSON validation or retry policy. Rejects are kept only as counts, so recall errors cannot be seen.
- Major: the retention conflict (1.9).
- Major: the laptop-hosted Telegram bot is a single point of failure. The 48-hour delete window and update retention are unchecked, and there is no gap detector.
- Major: the SLA is unstated while RSS is OFF.
- Nit: the draft keyword filter matched 0 of 21 headlines. The 100-item labelled set should include negatives the user did not choose.

### egm-codebase-details
- Blocker: the 5.4 claim that the `basis` label is wrong and the fix is "not yet made" is stale. `scanner/fund_derive.py:195` already reads "price x shares (equity capital / face value)".
- Major: `factors_matched` (section 7 Q4) is not a function. It is a local count in the enrichment code. The real outputs are `bonus_issue`, `demerger`, `orderbook_signal` and `expansion_signal`.
- Major: 5.5 says section 6 "differs" from `factors.py` without listing the differences. Several tier 1 terms already match `ORDERBOOK_KEYWORDS`. Real differences include "LoA", "Purchase order" and "Bags contract".
- Nit: "751 rows, all with ISIN" is point-in-time, because the schema allows a null ISIN.
- Nit: the Upstox token claim (covers News, no static IP) is not in `secrets-and-roles.md`, which only confirms that the token exists.
- Verified OK: `classify_bucket` (`max_dist=26.0`), `classify_trend`, the 39-of-298 figure (`handoff.md:113`) and the UI spec sections 5.1, 5.4 and 6.

### egm-zoom-out
- Blocker: the scope is too wide for one Home feed doc. It holds an LLM pipeline, RSS, a Telegram bot, Upstox News, a macro panel and a calendar. Ship filings plus the shortlist first and split the rest.
- Blocker: terms risk is accepted for NSE, Investing.com and CNBC, and Upstox adds more. Prefer sources with clear terms.
- Major: the LLM filter is premature. Start with keyword rules, as `factors.py` does, and add the LLM only if measurement shows a need.
- Major: the Telegram bot is a heavy service for one user pasting links.
- Major: the 14-field event row (model_id, prompt_version) is speculative.
- Major: Upstox News is specified before its terms are cleared.
- Major: the market cap storage and Upstox fundamentals tables belong in `fundamentals-tables.md`.
- Nit: section 6 duplicates `factors.py`. Section 8 could be its own doc. `scanner/expiry_alerts.py` is a reuse candidate for alerting.

### egm-comprehension
- Major: status versus section 7 (1.1). Retention (1.9). Beat/miss vocabulary (1.7). The OFF-by-default switch is never defined. Broken cross-references ("3.3", and a "section 5" consensus pointer that does not discuss consensus).
- Major: "tier" means three different things (event tiers, keyword tiers, feed tiers). The "user's list" is not linked.
- Nit: undefined terms (SAST, MPC, SDF, MSF, bp, ISIN, event tracker, intake queue, critical event). 5.4 is a long mixed paragraph. Section 7 has two "Decided" blocks and an unlabelled Hosting paragraph. Section 6 is "draft", but section 2 treats it as the live prefilter. "Fed" and "PCE" are ambiguous keywords.

### egm-implementation-readiness
Verdict from the lens: not ready.
- Blocker: no DDL for the events table, intake queue or calendar table. Types, keys, indexes and status enums are undefined.
- Blocker: no parser spec for the exchange feeds (XML field mapping, tier per feed with several "to confirm", cookies and headers for NSE, rate limits).
- Blocker: the retention rule is undefined for purge, fields and job.
- Blocker: the Upstox source is blocked, and there is no failure handling for a failed batch of 30 keys.
- Major: no `LLM_URL` contract (request format, prompt, timeout, batch size, retries, malformed JSON) and no enum for `category`.
- Major: undefined thresholds ("significant" insider trade, contract value to market cap ratio, back-to-back wins).
- Major: no toggle for RSS OFF, no holiday calendar source, unconfirmed FRED IDs, and India CPI comes from a PDF with no ingestion method.
- Major: the Telegram dedupe key is undefined. The shortlist-to-feed join and the place where the 3-per-stock cap is applied (API or UI) are not stated.
- Nit: no file-change list or test plan beyond the precision and recall targets.

### egm-structural
- Major: the header versus "Still open: None" (1.1, 1.3). 4.1 "not decided" (1.2). The "3.3" reference. The 4.5 order.
- Nit: section 4.2 lines 112-120 are unbulleted and unseparated, and the Telegram batch paragraph sits after "Status".
- Nit: section 5 item 6 lacks a bold lead-in, and item 4 mixes topics.
- Nit: the section 6 test results and macro keyword set need their own subsection.
- Nit: section 7 mixes Q blocks, "Decided" and "(continued)", and paragraphs break the bullet list at lines 239-242.
- Nit: section 3 repeats the tier lists from section 1 row 1. Section 9 omits links to `secrets-and-roles.md`, `handoff.md` and the fundamentals doc.

## 4. Synthesized blocking items before approval

1. Status truth: change line 3, replace "Still open: None" with a real open or deferred list, fix 4.1 "not decided", add Q1 and Q2 to section 7, and give Upstox (row 7) a decision or an explicit "deferred".
2. Retention contradiction (2.1 versus section 7): state which fields are kept for which rows, what is purged and when, and which job does it.
3. Unresolved gates need an explicit "deferred, source stays OFF until" entry: Upstox terms, Telegram retention, NSE and BSE rate limits, MoSPI time, FRED series IDs.
4. Licence stance: reconcile 5.2 with 4.1 and 4.2 into one statement, and add a mitigation policy (kill switch, backoff, user-agent, rate limit).
5. Scope: the user decides whether to split the doc. Filings plus the shortlist first, with the LLM filter, Telegram, Upstox, RSS and the macro calendar as separate designs or phases.
6. Missing build specs for any in-scope phase: DDL for events, queue and calendar tables, an exchange feed field mapping with tiers per feed, the LLM contract (including the `category` enum and JSON validation), and the insider, order-value and back-to-back thresholds.
7. Factual errors: remove the stale `basis` label claim (`fund_derive.py:195` is already correct), replace `factors_matched` with the real signal names, list the actual diffs between section 6 and `factors.py`, and fix the "3.3" reference.
8. Beat/miss vocabulary (5.1 versus section 7) and the RSS-OFF versus freshness SLA: choose one of each.

Non-blocking: nits above (numbering of 4.5, undefined terms, formatting, missing links in section 9).

## 5. Verdict

NOT READY: 8 blocking items (status truth, retention contradiction, undeferred open gates, licence stance and mitigation, scope split, missing build specs, factual errors, beat/miss and RSS-SLA inconsistencies).
