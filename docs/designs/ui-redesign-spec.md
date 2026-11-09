# UI redesign: Phase 4 design system and spec

Date: 2026-11-09. Status: approved by you on 2026-11-09. No code yet; Phase 5 starts in slices.
Direction: Option D (screener table with a full stock page), from `docs/designs/ui-redesign-directions.md`.
Inputs: `docs/designs/ui-redesign-brief.md`, `docs/designs/ui-redesign-audit.md`.

## 0. Progress

Updated 2026-11-09. This section is updated at each milestone.

| Phase | Status | Notes |
|---|---|---|
| 1. Audit | Done | `docs/designs/ui-redesign-audit.md` |
| 2. Brief | Done | `docs/designs/ui-redesign-brief.md` |
| 3. Direction | Done | Option D confirmed by you on 2026-11-09 |
| 4. Design system and spec | Approved by you on 2026-11-09 | Contrast measured for all text, signal, neutral and border tokens (section 2). Section 9 decisions answered; decision 4 closed |
| 5. Implementation (slices) | Unblocked, not started | Slices in order: tokens and shell, scan table, filter bar and presets, stock tab and chart, sector heatmap, states |
| 6. Audit and optimize | Not started | |

Next action: install the chosen skills (section 9, decision 5), then start Phase 5 slice 1 on your go-ahead.

Stack: Node.js + TypeScript + Fastify backend. Vite + React + TypeScript frontend, built to static files and served by Fastify. TanStack Table with row virtualization. TanStack Query. TradingView Lightweight Charts v5 only. Tailwind v4 and shadcn/ui, confirmed by you on 2026-11-09 (section 9).

## 1. Principles

1. The app shows data and does not give a verdict. Every label (buy, add, hold, trim, sell, rebalance) sits next to the inputs that produced it.
2. Calm by default. Dark is the default. The screen must not add to fear in a falling market.
3. The table is the entry point. Clicking a company opens its stock tab.
4. One event record feeds both the timeline and the Telegram alert. The two always match.
5. Semantic tokens only. No hard-coded colours in components.

## 2. Design tokens

All colour values are proposals. Each text and background pair must reach WCAG AA (4.5:1 for body text, 3:1 for large text and UI boundaries).

Measured 2026-11-09 with the WCAG 2.x relative-luminance formula (script in the session scratchpad). Every pair passes 4.5:1:

| Pair | Dark | Light |
|---|---|---|
| `--text` on `--bg` / `--surface` / `--surface-2` | 14.48 / 11.87 / 10.18 | 17.06 / 17.85 / 16.30 |
| `--text-muted` on `--bg` / `--surface` / `--surface-2` | 6.96 / 5.71 / 4.89 | 7.24 / 7.58 / 6.92 |
| `--gain` on `--bg` / `--surface` | 9.29 / 7.61 | 5.24 / 5.48 |
| `--loss` on `--bg` / `--surface` | 6.63 / 5.44 | 6.01 / 6.29 |
| `--accent` on `--bg` / `--surface` | 5.98 / 4.90 | 7.55 / 7.90 |
| `--caution` on `--bg` / `--surface` | 10.69 / 8.76 | 4.80 / 5.02 |
| `--focus` on `--bg` / `--surface` | 8.96 / 7.34 | 9.49 / 9.93 |

Measured 2026-11-09 for `--neutral` and borders:

| Pair | Dark | Light | Result |
|---|---|---|---|
| `--neutral` on `--bg` / `--surface` | 6.96 / 5.71 | 7.24 / 7.58 | Passes 4.5:1 |
| `--border` (`#334155` / `#CBD5E1`) on `--bg` / `--surface` / `--surface-2` | 1.72 / 1.41 / 1.21 | 1.42 / 1.48 / 1.36 | Fails 3:1 in both modes |

Decision: `--border` is kept for decorative dividers only (WCAG 1.4.11 does not apply to them). A new token, `--border-ui`, carries every boundary that identifies a control or input. Its values are dark `#7C8A9E` (3.58:1 or better on all surfaces) and light `#7A8699` (3.36:1 or better on all surfaces). Both are shown in section 2.1.

### 2.1 Colour (semantic names, CSS variables on `:root`)

| Token | Dark (default) | Light | Use |
|---|---|---|---|
| `--bg` | `#0F172A` | `#F8FAFC` | Page background |
| `--surface` | `#1E293B` | `#FFFFFF` | Cards, panels, table body |
| `--surface-2` | `#273449` | `#F1F5F9` | Table header, hover, tabs strip |
| `--border` | `#334155` | `#CBD5E1` | Decorative dividers and table lines only |
| `--border-ui` | `#7C8A9E` | `#7A8699` | Input, select, button and tab outlines. Meets 3:1 on all surfaces (section 2) |
| `--text` | `#E2E8F0` | `#0F172A` | Primary text |
| `--text-muted` | `#94A3B8` | `#475569` | Labels, secondary text |
| `--gain` | `#34D399` | `#047857` | Price up (always with ▲ and sign) |
| `--loss` | `#FB7185` | `#BE123C` | Price down (always with ▼ and sign) |
| `--neutral` | `#94A3B8` | `#475569` | Unchanged (always with ● or "0.00%") |
| `--accent` | `#818CF8` | `#4338CA` | Selection, focus ring, active tab |
| `--caution` | `#FBBF24` | `#B45309` | Stale data, warnings, "not available" |
| `--focus` | `#A5B4FC` | `#3730A3` | Keyboard focus outline (2px minimum) |

Gain and loss are colour-blind-safe because the sign and the arrow carry the meaning, not the colour.

The dark values are defined once under `:root:not([data-theme="light"])` inside `@media (prefers-color-scheme: dark)`, and again under `:root[data-theme="dark"]`. This follows the convention in the project's global rules.

### 2.2 Type

- Text: Fira Sans. Numbers: Fira Code with `font-variant-numeric: tabular-nums`. Both are already used by the live app.
- Scale (px): 12, 13, 14 (body), 16, 20, 24. Table rows use 13 or 14. The stock header price uses 24.

### 2.3 Spacing and shape

- Spacing steps: 4, 8, 12, 16, 24, 32.
- Radius: 6px on cards, 4px on controls.
- Table row height: 32px (dense), 40px (touch, when the viewport is below 768px).

### 2.4 Motion

- Price-change flash: a 600ms background tint on the changed cell, then fade out.
- Under `prefers-reduced-motion: reduce`, the flash is replaced by a static 2px left bar in the gain or loss colour. No layout shift in either case.

## 3. Number and currency formatting

These rules apply everywhere a number is shown.

- **INR** with the ₹ symbol. Indian grouping: `1,23,45,678.90` (lakh and crore grouping, not thousands grouping).
- Prices: 2 decimals. Percent change: 2 decimals with a sign: `+1.24%` and `−0.87%`. The minus sign is `−` (U+2212) in display text.
- Changes: sign, arrow, then number: `▲ +12.30 (+1.24%)`.
- Market cap in crore: `₹4,512 Cr`. Turnover in lakh or crore, whichever reads more naturally.
- Zero change: `● 0.00%`. It is never shown as a gain or a loss.
- Missing data: `—` (em dash) with a tooltip "Not available". Never `0` and never blank.
- Dates: `09 Nov 2026`. Times: 24-hour IST, with a `IST` suffix on the market clock.

## 4. Components

| Component | Source | Notes |
|---|---|---|
| `AppShell` | custom | Top bar with search (Ctrl/Cmd+K), tab strip, data-age stamp. Holds the two-column layout below |
| `ResizablePanels` | custom | Left panel and main area, split by a drag handle. Slice 1 (decision 6) |
| `WatchlistPanel` | custom | Left panel listing watchlist symbols. Slice 1 (decision 6). Empty state when no symbols |
| `TabStrip` | custom | Open stock tabs. Ctrl-click or middle-click opens a stock in a new browser tab at its own URL |
| `ScreenerTable` | TanStack Table | Sortable, filterable, row virtualization, sticky header and first column, column hide and resize |
| `ColumnFilterPopover` | shadcn/ui Popover (if confirmed) | Replaces the current filter popover |
| `FilterBar` | custom | Scan filters, saved presets |
| `ChangeValue` | custom | Enforces sign, arrow and tabular numerals (section 3) |
| `StockHeader` | custom | Price, change, distance from ATH, stance |
| `PriceChart` | lightweight-charts v5 | OHLC legend, moving averages, volume pane, timeframe bar, right price scale. No TradingView branding |
| `EventTimeline` | custom | Reads the shared event record (section 6) |
| `GuidelineCard` | custom | A label, plus its inputs and "what would change it" |
| `FundamentalsPanel` | custom | Reads from the database only |
| `ConcallSummaryPanel` | custom | Reads from the database only (section 7) |
| `OrderBookPanel` | custom | Backlog and contract awards from stored announcements |
| `StateView` | custom | One component for loading, empty, error, market-closed, pre-open, stale and reconnecting |
| `Command` palette | shadcn/ui Command (if confirmed) | Ctrl/Cmd+K symbol search |
| `Sparkline` | custom SVG | Row sparkline in the table |
| `SectorHeatmap` | custom | Built from scanner data. Gain and loss shown with sign and arrow, not colour alone |

## 5. Screens

### 5.1 Home (scan table)

- Full-width `ScreenerTable` with the latest ATH run.
- A header line shows the run date, the run's age, and the data-age stamp. The stamp reads the run's own timestamp, not the browser clock (audit item 6).
- Above the table: a shortlist of stocks with new events, and the event feed.
- Columns: symbol (sticky), name, price, change, ATH date, distance from ATH, sparkline, sector, stance. Each column can be hidden or resized.

### 5.2 Stock tab

- Opens from a company name in the table. Closing a tab does not close others.
- One grid, in this order: header (price, change, distance from ATH, stance), chart, announcements and events, fundamentals, concall summaries, order book, guidelines with their inputs.
- Each section shows its own `StateView` for loading, empty and error.

### 5.3 Portfolio

- Holdings list, with a guideline per holding and its inputs.
- Recent updates per holding.
- Three sources: Zerodha (Kite API, daily login step), Upstox API, CSV import with a column mapping per broker. One holdings model for all three.
- Holdings are never named in alerts (brief, Events and alerts).

### 5.4 Events

- Company red flags and policy items, each with its source link.
- Filter by type and date.

### 5.5 Settings and operations

- Existing master configuration and API key screens carried over. Write actions need an authentication decision first (section 9).

## 6. Event rule

- One event record per event. The timeline and the Telegram alert both read it.
- An alert names only the company and the event. It never names a holding.
- Policy items show category, severity, a one-line reason, affected companies and the original link. The LLM classifies, and you make the call.

## 7. Data rules

- The UI reads only from the database. It never calls a third-party site.
- Fundamentals: the collector brings them into the database (decision 1, 2026-11-08).
- Concall content: the local LLM generates summaries from stored transcripts and presentations, using `docs/designs/concall-summary-template.md`. No site text is copied (decision 2).
- Order book: the company's backlog and contract awards, from stored announcements (decision 3).
- Market mood (breadth, volatility) is not available. It shows as "Not available", never a guess.
- End-of-day prices are the only data today. The timeframe bar shows intraday options as "Not available" until an intraday source exists.

## 8. States

Every data view uses `StateView` and handles these states:

| State | Shown when | Visual |
|---|---|---|
| Loading | A request is in flight | Skeleton rows, no layout shift |
| No results | The query returns zero rows | Message plus a "clear filters" action |
| API error | The request fails | Error message, retry button. Never shown as "No runs yet" (audit item 7) |
| Market closed | Outside NSE/BSE hours | Caution banner with the last close time |
| Pre-open | 09:00 to 09:15 IST | Caution banner |
| Stale data | The run is older than the expected cadence | `--caution` stamp with the age |
| Reconnecting | Only once a live transport exists | Caution banner. Not built in v1 for live tickers yet (see section 9) |

## 9. Open decisions

1. **WebSocket for live tickers. Answered 2026-11-09: Upstox market-data feed.** Live, reconnecting and pre-open states depend on it. Before use, the Upstox data-sharing licence terms must be checked (brief, Blocker 3). Cost is still unknown.
2. **Tailwind v4 and shadcn/ui. Answered 2026-11-09: Tailwind v4 + shadcn/ui.**
3. **Authentication for write endpoints. Answered 2026-11-09: local-only bind, no token.** The audit found that config and secret writes are open on all interfaces (audit item 1). The bind to 127.0.0.1 stops other machines on the network. It does not stop a web page open in the same browser from calling localhost. Accepted risk, recorded here so it is a known trade-off.
4. **Border and neutral contrast. Closed 2026-11-09.** `--neutral` passes. `--border` failed 3:1, so `--border-ui` was added for control outlines (section 2).
5. **Skills. Answered 2026-11-09: install shadcn/ui, Vercel agent-skills, and financial-ui-patterns and styles.** Install is pending. The brief says to remove them after implementation. Their rules are also written into this spec (sections 2 to 4).
6. **Watchlist and resizable panels. Answered 2026-11-09: slice 1.** Layout rules for slice 1:
   - At 768px and wider: a left panel (default 240px, min 200px, max 480px) and the main area. A vertical separator with `role="separator"` sits between them. Arrow keys move it 16px. Pointer drag works too. The width is saved in `localStorage` under `ms-watchlist-width`, with try/catch. Storage can fail, and the layout must still work without it.
   - Below 768px: the watchlist stacks above the main area, full width, with no resize handle.
   - Watchlist content: the panel takes a list of symbols as a prop. Slice 1 passes an empty list, so it shows "No symbols on the watchlist yet." No fake symbols. Adding and removing symbols belongs to the scan table slice, which brings the data source.
   - Persistence of the watchlist itself (localStorage or server) is an open question for that later slice.
7. **TypeScript, Vite and Vitest major versions.** Open. The build is on TypeScript 7.0.2, Vite 8.3.6 and Vitest 5.1.0. Waiting for your choice (see the chat message of 2026-11-09).

## 10. WCAG AA checklist (to complete before approval)

- [x] Text and signal token pairs measured in light and dark (section 2.1).
- [x] `--border` against surfaces (3:1) and `--neutral` on `--bg` measured. `--border-ui` added for controls.
- [ ] Gain and loss have a sign and an arrow everywhere (section 3).
- [ ] Table rows are keyboard reachable. Enter and Space open the stock. Visible focus ring on every interactive element.
- [ ] Sticky table header has a real scroll container (audit item 16).
- [ ] `prefers-reduced-motion` replaces the flash with the static bar.
- [ ] Layout works at 375px wide with no horizontal page scroll, and the data-age stamp stays visible.
- [ ] Colour is never the only signal for state (stale, closed, error).

## 11. Next steps after approval

1. Build in slices, each approved before the next: tokens and shell, scan table, filter bar and presets, stock tab and chart, sector heatmap, states.
2. Run the old UI side by side until you approve the switch (brief, Constraints).
3. Audit and optimize: 5,000-row test and 1-second tick test.
