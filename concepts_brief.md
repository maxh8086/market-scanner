# Concepts Brief: Shared Column Glossary

Status: proposal, not approved. Nothing here is implemented. Source context is `handoff.md` lines 864-1033 (Report and UI review round, UI direction) and `scanner/workbook.py` lines 57-84 (`_organize_columns`). Reviews were run in BRAINSTORM mode by six lenses (design, codebase details, zoom-out, comprehension, implementation readiness, structural).

## Overview

The model misread `vol_*` as trading volume in 98 of 291 conclusions (34%). Raw field names such as `price.distance_pct` leak into conclusions, concerns and positives. Excel and the UI show many columns with no explanation. The proposal is one glossary file, one entry per column, read by three consumers: Excel cell comments, UI tooltips and labels, and the model prompt. The goal is that the three cannot drift apart.

The problem is real and the three-consumer idea is sound. The proposal as written, however, is over-specified in places it cannot deliver (automatic maintenance, parked formulas, full column coverage) and under-specified in others (format owner, gate, scan scope). The reviews agree that a smaller first version fixes the measured defects.

## Analysis

### What the source establishes

- The measured defects are: the `vol` naming (34% of conclusions read it as volume), raw field names in model text (194 conclusions, 67%), "No order data" listed as a concern (143 rows), "Distance from ATH" listed as a concern (177 rows), and blank positives (67 rows). Most of these are fixed by prompt and naming changes, not by a glossary alone.
- `_organize_columns` (`scanner/workbook.py` 59-84) keeps hand-written lists and silently appends any column not in them (lines 77-79). A new column reaches Excel with no failure. `above_ema50` and `above_sma200` are still listed at line 64, although handoff line 898 says to drop them.
- Packet keys are nested and dynamic (`price.*`, `forecast.*`, `filing{i}.*`, `graph.*`). Handoff line 925 says `price.vol_*`, but the reviewers found `vol_forecast_pct` sits under the forecast group, so its key is `forecast.vol_forecast_pct`.
- Column lists are duplicated in `scanner/report.py` and in `GROUPS` in `scanner/conclude.py` (about lines 47-61). No existing test enumerates workbook or packet columns.
- Several rules in the handoff describe values that are not yet settled: the `stance_score` thresholds and pillars (handoff 901, parked by 970-972), `breakout_quality` (928-938, to be redefined once volume data arrives), and the `order_value_source` labels (903, "user to confirm").
- Code and handoff disagree in places: `order_significance` is documented as blank when unknown (904), but the code writes the string `UNKNOWN` (`enrich.py` near 996, via `significance.py`; reviewer-reported, not re-run). `above_sma200` is used by `scanner/portfolio.py` for logic (around lines 99, 231-235, 290), so it cannot be dropped from the backend without a change there.
- The UI is moving to Node.js and supersedes the FastAPI plan (handoff 1011-1012). Current consumers under `ui/app/` (`api.py`, `queries.py`, static files) will be replaced. The glossary format must not depend on Python.

### Weak points and objections

1. **"The system maintains the file automatically" conflicts with the rest of the proposal.** Plain-English tooltips and explanations need human authorship. The handoff requires user-confirmed wording (903), wireframe sign-off (871, 891), and a banned-word rule. Generated prose will not reliably pass plain-English checks, and LLM-drafted text is non-deterministic. Fix: a human writes the prose; the automation only reports entries that are missing, stale (formula changed), or still marked "proposed".

2. **The formula test has no independent oracle.** The rule is "a test checks the code output against the stated formula." A prose derivation cannot be checked by a machine. A second implementation inside the test copies the code and drifts with it. The HV windows and baseline definition are not fully stated (918-922), the percentile uses a midpoint rank and tolerance (`volatility.py` 150-172), and the zero-baseline branches are unspecified (213-223). Fix: write each formula with its inputs, window, blank rule and branches, then test against hand-computed fixtures, not against the code.

3. **Parked and redesigned logic is frozen into the glossary.** `stance`, `stance_score`, `stance_why` and `breakout_quality` will change with the scoring redesign (901, 928-938, 970-972). Writing exact formula tests now locks in behaviour the user has already said will change. Fix: mark these entries "provisional, pending scoring redesign", with a warning rather than a failure, until the redesign lands.

4. **The column set is not closed.** "Every column" cannot be enumerated from the source: `_organize_columns` appends unknown columns, packet keys are dynamic, and handoff line 905 uses the wildcard `rev_ttm_dev_*`. Fix: the coverage test should run on the real workbook header and a generated model packet, and fail on any key without an entry. It should not rely on the hand-kept lists. Remove the duplicate lists in `report.py` and `GROUPS` as part of the same change.

5. **Rules do not fit the three-way split.** Some values are rule-based, not formula-based or model-written: the `order_significance` bands (two different tables, `MCAP_BANDS` and `REVENUE_BANDS`, in `significance.py`), `stance` (deterministic scorecard), and the `industry PE == own PE` fallback (983). Fix: add a third class, "rule", that names the function and thresholds. Entries should state the blank meaning explicitly, since blank also means "not in uptrend" for `breakout_quality` and "not reported" elsewhere (890).

6. **Rename and alias rules collide with the packet rule.** Handoff 925-926 says packet keys the model sees must not contain `vol`. A rollout alias that still serves old keys to the model keeps the misreading alive. Stored runs (868-870) keep old names. Fix: aliases are for read paths only (lookups for stored data), never emitted into the packet or the UI. Give each alias a removal point and a test. For a single-user workbook regenerated each run, a single-commit rename with a grep test for old keys may be simpler than an alias map.

7. **The Screener-name check is too narrow.** Handoff 887-888 says the source must not be shown in the UI. The check as written covers UI tooltips and labels only. The same glossary text feeds Excel comments and the prompt, and model-written fields (conclusion, positives, concerns) can reach the UI. Fix: scan every output that leaves the repository (UI files, Excel comments, the packet, the model's output fields), and scan the built UI, not only source. Name the forbidden terms and the scanned paths in the spec, and add a planted-fixture test that proves the check fails.

8. **Gate and visibility are inconsistent.** "Build warns, test fails" lets a warning be ignored. There is no build target in the repository (no `pyproject.toml`, `Makefile` or `ui/package.json` build step, per the readiness lens), so "build" is undefined. Hidden columns (889, 905-908) have no visibility field, so each consumer decides separately. Fix: one hard gate (a pytest test); the entry carries a visibility field (excel, ui, prompt, backend-only).

9. **Buzzword and plain-English rules are not testable as written.** No banned-word list exists. The handoff's own wording uses "tailwind", "signal", "regime", "anchor", "clamped" and "pillars". Acronyms (ATH, TTM, PEG, QoQ, EMA, SMA, HV, LLM) need expansion on first use in each consumer. Fix: ship a banned-term list and a short acronym list with the test.

10. **Model glossary can give conflicting instructions.** The prompt glossary must say that blank means "not reported", and must say what each field is for. Without this, "No order data" concerns and "Distance from ATH" concerns persist (1003-1004). Fix: each prompt-facing entry carries a role line (for example "screen criterion, not a concern") and a blank meaning.

11. **Reader comprehension of the proposed labels is weak.** "CAUTIOUS" can read as "sell". "MIXED" also covers "fewer than 3 pillars have data" (901), so no-data reads as mixed signals. "HV_PCT" reads as "HV as a percent" when it is a median of history. "breakout_quality" promises a breakout judgement it does not make (936). "Filed figure (unit inferred)" does not say what was inferred. Fix: each label carries a one-sentence meaning and a "not a buy or sell call" note; insufficient data gets its own wording.

12. **Scope and effort are larger than the defect needs.** Auto-generated text, a formula-check suite for every column, a banned-word linter and an alias layer together form a platform. A minimum version covers the defect: one hand-written data file for the columns that reach Excel, UI or the packet, one coverage test, one forbidden-token test (old keys, `vol` in packet keys, `UNKNOWN`, the Screener name), and formula fixtures for the three formulas that are stable.

13. **Format must outlive the Python code.** A Python module as the glossary would tie the Node UI to Python. Store it as JSON or YAML at one path, name the loader module for Python, and record the decision in an ADR before the first task.

### Corrections to the source before building

- Packet key for HV Forecast is `forecast.vol_forecast_pct`, not `price.vol_*`.
- `order_significance` writes `UNKNOWN` today; the blank rule in the handoff is a proposal, and the writer must change first.
- `above_sma200` is read by `portfolio.py`; removing it from the display and the packet is fine, removing it from the backend is not.
- `HV Forecast` is empty without a model, and the `rev_forward_ttm_*` bands come from backtest percentiles. Both are model- or backtest-derived; the test should check presence and range, not exact values.

## Goals vs. Non-Goals

**Goals**
- One data file with one entry per column that reaches Excel, UI or the model packet.
- Excel comments, UI tooltips and labels, and the model's glossary read from that one file.
- Stop the model reading `vol` as volume: rename to HV, and forbid `vol` in packet keys the model sees.
- Stop raw field names appearing in model text.
- Blank means "not reported" everywhere, and the code writes it that way.
- The Screener source name never appears in anything shown to a user or sent to the model.

**Non-Goals**
- Automatic generation of plain-English prose. Humans write entries.
- Exact formula tests for `stance`, `stance_score` or `breakout_quality` before the scoring redesign.
- Volume-based breakout logic (waits for the delivery and volume work).
- BSE data.
- Building the Node UI itself. This brief only sets the glossary format it will read.
- Keeping backward-compatible old keys in the model packet.

## Key Decisions and Staging

**Decided by the user (2026-10-31)**
1. Wording is generated by an LLM from the data. A column with no data has nothing to derive, so it gets no entry, and the coverage test skips it.
2. Renames happen in one commit with a grep test. There is no alias layer.
3. The build prints a warning for a missing entry. The test suite fails on a formula mismatch and on the Screener-name check.
4. The Screener-name check covers every output: Excel, the prompt, model text and the UI.
5. Excel headers are display labels written for the reader, not backend keys.

**Resolved by the user (2026-10-31)**
1. Sign-off: the user signs off on the final wording and labels, including LLM-written wording. The wireframe is a separate gate and is not covered here.
2. Wording for `order_value_source`, the stance labels, the HV labels and the "Forecast uncertain" chip depends on the data present. It is not mandatory: a column or label with no data has no entry.
3. Hidden backend-only columns get a short entry for the record only. They get no tooltip. This resolves the conflict between lines 884 and 889 of the handoff.
4. `above_sma200` and `above_ema50` stay in the backend.
5. Stored runs are re-run through a key mapping. Old key names are not kept in stored runs.

**Staging (proposed order)**
0. Confirm the wording and decisions above. Wireframe sign-off for the UI stays a separate gate (871, 891).
1. Write an ADR for the file format, its path, the loader module and the single pytest gate. Set the list of forbidden terms and scanned paths.
2. Fix the defects that do not need the glossary: rename `vol_*` to HV labels and packet keys in one change, add the field-name ban to the prompt, make `UNKNOWN` blank for `order_significance`, remove duplicate column lists, and make an unlisted column fail instead of appending silently. Each change gets a grep or unit test. Acceptance: the test suite passes and the old keys are gone from the packet.
3. Write hand-authored entries for the columns that reach Excel, UI or the packet, with visibility set per entry. Add the coverage test and the forbidden-token test (including the Screener name over every consumer's output).
4. Write formula entries for the stable formulas (HV, HV percentile and regime, `order_significance` bands, `volume_spike` once it exists), each with fixtures computed by hand.
5. Mark `stance`, `stance_score`, `stance_why` and `breakout_quality` as provisional. Revisit after the scoring redesign.
6. The Node UI reads the same file when its build starts. Wireframes first.

## Top Objections (short list)

1. **Auto-maintenance contradicts hand-written, user-confirmed wording.** Automation should only flag missing or stale entries.
2. **The formula test has no independent oracle, and it locks in parked formulas** (`stance_score`, `breakout_quality`). Use hand-computed fixtures and mark redesign-dependent entries provisional.
3. **The column set cannot be enumerated from the hand-kept lists.** `_organize_columns` appends unknowns silently, and packet keys are dynamic. The coverage test must run on real output.
4. **The alias layer keeps the misreading alive and conflicts with the no-`vol`-in-packet rule.** Aliases must be read-only and removed on a date, or the rename done in one commit.
5. **The Screener-name check is scoped too narrowly and the gates are inconsistent.** Scan every output (Excel, prompt, model text, UI) with one hard gate, and define the format owner so Python and Node read the same file.

## Verification note

Six reviewer lenses ran read-only. Their factual claims about `order_significance`, `forecast.vol_forecast_pct`, `above_sma200` in `portfolio.py`, and the duplicate lists were not re-run by this synthesis; they should be confirmed with a grep before the ADR is written. No code was modified.
