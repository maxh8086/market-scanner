# Strategy engine: rules, results and outcomes

Status: draft, not approved. No code written. Date: 2026-11-09.
Owner: Vaibhav Pavtekar
Related: `docs/designs/home-event-sources.md` (order-win rule, event tracker), `docs/designs/fundamentals-tables.md` (Postgres fundamentals), `docs/designs/secrets-and-roles.md`, `docs/designs/ui-redesign-spec.md`, `ui/wireframes/strategy.html` (wireframe, sample values).

## 1. Purpose

The system finds stocks. A strategy decides which of them to shortlist or recommend, using a stated set of rules. Strategies will be added over time, and each one gets its own panel on the dashboard. This design keeps three things apart:

1. **System (facts).** Prices, trend, ATH distance, corporate-event factors, fundamentals, and the stock scorecard. These produce numbers and labels. They know nothing about strategies.
2. **Strategy (rules).** A named set of conditions over the facts, plus how to rank matches and how to measure them. A strategy is data, not code.
3. **Rule engine.** One component that evaluates any strategy against the facts, and writes results and later outcomes. It is the only component that knows what a strategy is.

Adding a strategy should mean adding a spec and a panel entry. It should not mean editing the scanner, the engine or the core UI.

## 2. Current state (checked in code, 2026-11-09)

| Piece | Where | What it does today |
|---|---|---|
| ATH scan | `scanner/ath.py`, `ath_scan.py` | Computes distance from the all-time high. `classify_bucket` drops anything above `max_dist=26.0`. |
| Trend | `scanner/indicators.py` `classify_trend` | Labels a stock UPTREND (above EMA50 and SMA200), ABOVE_200_ONLY, ABOVE_50_ONLY, BELOW_BOTH or INSUFFICIENT_HISTORY. |
| Corporate-event factors | `scanner/factors.py`, `build_factor_table` | Sets `bonus_issue`, `demerger`, `orderbook_signal`, `expansion_signal` and `factors_matched` (count of the four). Joined on ISIN from NSE data. |
| Scorecard | `scanner/conclude.py` `scorecard` | Six pillars (trend, growth, quality, valuation, forecast, orders), each clipped to -2..+2. Stance: CONSTRUCTIVE if total >= 3, CAUTIOUS if total <= -2, otherwise MIXED. Fewer than 3 pillars with data gives MIXED. Returns the rules that fired. |
| Shortlist | `handoff.md` lines 113-114 | Described as the intersection: UPTREND and at least one factor. The 2026-09-28 run gave 298 ATH matches and 39 names in that intersection. **No code applies this intersection.** It is a manual step recorded in the handoff. |
| Scan output | `scanner/workbook.py` | Written to an Excel workbook. That workbook was designed before the database existed. Strategy results do not go to Excel (decision 6). No table stores each run's facts yet. |

Two items from earlier notes are corrected here:
- The scorecard has six pillars, not five.
- The order-win rule in `scanner/factors.py` is the source. The section 6 keyword list in `home-event-sources.md` is a draft. Section 5.5 of that doc is corrected in the same change as this design.

## 3. Layers and boundaries

```
Facts (system)  -->  Fact snapshot  -->  Rule engine  -->  Results  -->  Outcome job  -->  Outcomes
                                             ^
                                             |
                                      Strategy specs (data)
                                                                 |
                                                                 v
                                       API (read only)  -->  Dashboard panels (one per strategy)
```

Boundary rules. These are the constraints the build must keep:

- **B1. Facts know no strategy.** Scanner modules produce facts with stable names. A module never imports a strategy, and never filters rows for one.
- **B2. A strategy is data.** It lives in a spec file. The loader validates it. Specs cannot run code, call functions or read other data. They only compare facts with values, using the operators in section 4.
- **B3. The engine reads facts and writes results.** It never recomputes a fact. The fact snapshot is the input, so a result can be reproduced later.
- **B4. Results and outcomes are append-only.** A result for a run date is written once. Outcomes are written by a separate job after the horizon date. Nothing is edited after it is complete.
- **B5. The UI computes nothing.** Each panel reads its own strategy's API endpoints. The browser never reads the database and never evaluates a rule. This follows the rule already recorded in the project memory: UI data goes through the API.
- **B6. A strategy change is a new version.** Changing a rule, threshold, horizon or benchmark creates a new spec version. Old results stay. Metrics are shown per version, so a change cannot quietly replace earlier numbers.

## 4. Strategy spec

Each strategy is one JSON file under `strategies/` (path to be confirmed in the build). Example for the current shortlist. Field names are illustrative and are set in the build.

```json
{
  "id": "ath-uptrend-events",
  "version": 1,
  "title": "Near the high, in an uptrend, with a corporate event",
  "universe": "scan_universe",
  "rules": {
    "all": [
      {"id": "near_ath",  "field": "ath.dist_pct",           "op": "<=", "value": 26},
      {"id": "uptrend",   "field": "price.trend",            "op": "==", "value": "UPTREND"},
      {"id": "event",     "field": "factors.factors_matched", "op": ">=", "value": 1}
    ]
  },
  "on_missing": "fail",
  "rank": {"field": "factors.factors_matched", "order": "desc"},
  "outcome": {
    "track_until_trading_days": 756,
    "report_at_trading_days": [20, 60, 252, 756],
    "benchmark": "NIFTY 750 TOTAL MKT",
    "success": "excess_return_pct > 0"
  },
  "panel": {
    "title": "Near ATH, uptrend, with event",
    "columns": ["symbol", "dist_pct", "trend", "factors_matched", "rule_trace"]
  }
}
```

**Operators.** `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not_in`, `is_null`, `exists`.

**Combining rules.** `all` (AND) and `any` (OR), nested at most two levels deep. No other syntax.

**Missing facts.** `on_missing` decides what happens when a fact is null for a stock. `fail` (the default) counts the rule as not passed. `unknown` leaves the stock out and reports it in the counts. Either way the rule trace records that the value was missing. A missing value is never treated as a pass.

**Outcome settings.** `track_until_trading_days` is the longest period an outcome is followed. It is 756 (about 3 years) in the example. `report_at_trading_days` lists the points where the panel shows a figure. Both are set per strategy, not fixed by the engine. The benchmark is an index name from the list in `scanner/index_candles.py`.

**Validation.** The loader checks the field names against the fact snapshot schema, the operators, the types and the nesting depth. A spec that fails validation is rejected whole. A partly valid spec never runs.

## 5. Rule engine

**Input.** One fact snapshot per run date. One row per symbol, with the facts named in the spec. The snapshot is written at the end of the scan, before any strategy runs.

**Output.** For each symbol: `matched` (true or false), `score` (the rank value, if any), and a `rule_trace` listing each rule with the value it saw and whether it passed.

**Properties.**
- Pure. Given the same snapshot and the same spec version, the output is the same.
- Idempotent. A rerun for the same strategy, version, run date and symbol replaces nothing new. It either matches the stored row or the run is flagged.
- Several strategies run against the same snapshot, so one scan can feed many panels.

**Acceptance test.** Run the current shortlist spec on the 2026-09-28 fact snapshot. It must give 298 ATH matches and 39 names with a factor and UPTREND, which matches `handoff.md`. The snapshot for that date has to be rebuilt from the saved data. If it cannot be rebuilt exactly, the difference is recorded, and the 39 figure is not treated as verified until it matches.

## 6. Results and outcome store

Proposed Postgres schema `strategy` (consistent with the fundamentals move to Postgres). Table names are proposals.

| Table | Key | Holds |
|---|---|---|
| `strategy.spec` | `strategy_id, version` | The spec JSON, a hash of it, created time. Rows are never changed. |
| `strategy.fact_snapshot` | `run_date, symbol` | The facts used, as they were at the end of the run. Needed so results can be reproduced. |
| `strategy.run` | `run_id` | Strategy, version, run date, universe count, matched count, unknown count, status, start and end time. |
| `strategy.result` | `strategy_id, version, run_date, symbol` | `matched`, `score`, `rule_trace` (jsonb), `unknown_rules`. |
| `strategy.outcome_path` | `strategy_id, version, run_date, symbol, trading_day` | One row per trading day after the run date: `adj_close`, `benchmark_close`, `return_pct`, `excess_return_pct`, `running_max_drawdown_pct`. Written as each day closes. |
| `strategy.outcome` | `strategy_id, version, run_date, symbol, report_at_trading_days` | Summary at each reporting point: `entry_close`, `exit_close`, `return_pct`, `excess_return_pct`, `max_drawdown_pct`, `status` (open, reached_report_point, reached_cap, no_data). Derived from `outcome_path`. |

**Outcome rules.**
- **Entry.** The close on the run date. Runs happen after the market closes (15:30 IST), so the entry uses a close that was known at the time of the run. Intraday runs are not part of this design (decision 2 in section 10).
- **Exit.** Open-ended. Each trading day after the run date adds one `outcome_path` row, using the exchange trading calendar. The outcome is `open` until a report point or the cap is reached. Once the cap (`track_until_trading_days`) is reached, the outcome is closed as `reached_cap`. A stock that stops trading (delisted or suspended) is closed as `no_data` at its last close, with the reason recorded.
- **Prices must be adjusted** for bonus issues, splits and demergers. Without adjustment, a bonus or demerger shows as a fall. The adjusted price source is an open item (section 11).
- **Benchmark.** The index return over the same days. An index EOD source already exists (`db/migrations/041_index_eod_source.sql`). Whether it covers the benchmark index needs checking.
- **Pending.** Outcomes stay `pending` until the horizon date is reached. A missing price gives `no_data`, not zero.

**Metrics** (computed from complete outcomes, per strategy version and horizon):
- Count of events.
- Hit rate: share of events with excess return above zero.
- Median return and mean excess return.
- Worst drawdown.

**Minimum sample.** Metrics show "sample too small" below 30 complete events for a horizon. No claim of an edge is made below that count.

## 7. API and dashboard

**API (Fastify, read only, reads Postgres only):**
- `GET /api/strategies`: list of strategies with title, version and panel config.
- `GET /api/strategies/:id/results?run_date=`: matches and rule traces for a run.
- `GET /api/strategies/:id/outcomes?horizon=`: outcomes for the run dates.
- `GET /api/strategies/:id/metrics`: the section 6 metrics per version and horizon.

**Dashboard.** A panel registry in `ui-v2`. Each entry names a strategy, its columns and its outcome view. Adding a strategy adds one registry entry and its spec. The core layout does not change.

**Stock page.** Each stock shows which strategies it matched, and its `rule_trace`, on the same screen as its other facts.

**Wireframe.** `ui/wireframes/strategy.html` already exists. Its panel layout has to be checked against `ui-redesign-spec.md` before the first panel is built.

## 8. Relationship to other parts of the system

- **Scorecard (`scanner/conclude.py`).** Stays in the system layer. Its `stance` and `score` are facts that a strategy can use as a rule, for example `stance == CONSTRUCTIVE`. It is not a strategy.
- **Order-win rule (`scanner/factors.py`).** Stays in the system layer. The coded rule is the source. The section 6 draft in `home-event-sources.md` is reconciled with it before any change.
- **Home event feed (`home-event-sources.md`).** The event tracker is a separate source. In version 1, news items are not strategy inputs. Only facts from the scanner and fundamentals are used.
- **Fundamentals (`fundamentals-tables.md`).** Facts from the Postgres fundamentals tables enter the snapshot through the same route as the other facts.

## 9. Build plan (after approval; nothing started)

Each step gets the EGM brainstorm and user approval before any task is dispatched, as the project rules require. Each step is verified by the offline test command before it is marked done.

1. **Fact snapshot.** Write each scan run's facts to `strategy.fact_snapshot` in Postgres. No Excel output for strategy data.
2. **Spec loader and engine.** Pure Python, no I/O. Tests cover the operators, missing-fact handling, nesting limits, and the 39-name acceptance test.
3. **Run job.** Started manually or at end of day, whenever the system is up. Runs every active spec and writes `strategy.run`, `strategy.result`. A missed day is not backfilled from later data (see section 11).
4. **Outcome job.** Adjusted prices, benchmark, horizons, `pending`, `no_data`, metrics.
5. **API.** The four read endpoints in section 7.
6. **First panel.** The shortlist as strategy 1, using the registry entry.

Tests: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -q`.

## 10. Decisions

Resolved on 2026-11-09:

1. **Spec format: declarative JSON, no code in specs.** Agreed.
2. **Run timing: manual, or at end of day when the system is up.** The system may not run every day, so no run is assumed for any date. Intraday runs are out of scope.
3. **Outcome horizons: open-ended, tracked up to 3 years (756 trading days).** Some outcomes take years to play out. The engine stores the daily path, and the panel shows report points (20, 60, 252, 756 trading days). The 20 and 60 day points are not the only measure. Report points are per strategy.
4. **Benchmark: NIFTY 750 TOTAL MKT (Nifty Total Market), the index the scan universe is drawn from.** It is in the index list in `scanner/index_candles.py` (`NIFTY 750 TOTAL MKT`, mapped to `NSE_INDEX|NIFTY TOTAL MKT`), and daily closes are stored in Postgres. Depth of history for this index has not been checked. The universe is its members, so each stock is part of its own benchmark (see section 11).
5. **Scorecard: a system fact that strategies can use.** Agreed.
6. **Fact snapshot storage: Postgres only.** Results and the snapshot are not sent to Excel. The Excel workbook was designed before the database existed.

## 11. Open risks

- **Corporate-action price adjustment.** The outcome figures are wrong without adjusted prices. This is a blocker for outcomes, though not for results. The source has not been chosen.
- **Survivorship bias.** The universe is today's constituents. Stocks removed since then do not appear in past results, so past hit rates look better than they were.
- **Look-ahead in events.** A factor must use only announcements dated on or before the run date. The factor cache joins by announcement date, so the join has to be checked for this in the build.
- **Small samples.** A new strategy has few events for months. The minimum sample rule (section 6) prevents early claims, but the panel must still show the count.
- **Overfitting.** Rules picked after seeing outcomes will look good. The version rule (B6) keeps every version visible. A rule change must be recorded before its outcomes are seen.
- **Missed days.** Runs happen only when the system is up, so some dates will have no snapshot. A missed date is recorded as missing. It is never rebuilt from later prices, because that would use information that was not available on the day.
- **Benchmark includes the stocks.** The universe is the members of NIFTY 750 TOTAL MKT, so a stock's return is part of the benchmark return. For a large stock the excess return is partly against itself. Compare with a benchmark that excludes the universe, or report both, before reading excess return as skill. This needs your decision.
- **Shortlist not yet coded.** The 39 names come from a manual step. Until the engine runs the spec, the panel for the shortlist would be the first place the rule is applied in code.
