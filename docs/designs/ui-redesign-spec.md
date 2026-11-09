# UI redesign: Phase 4 design system and spec

Date: 2026-11-09. Status: approved by you on 2026-11-09. Updated 2026-11-09 to match the code on `main` (Phase 5 in progress).
Direction: Option D (screener table with a full stock page), from `docs/designs/ui-redesign-directions.md`.
Inputs: `docs/designs/ui-redesign-brief.md`, `docs/designs/ui-redesign-audit.md`.

## 0. Progress

Updated 2026-11-09. This section is updated at each milestone.

| Phase | Status | Notes |
|---|---|---|
| 1. Audit | Done | `docs/designs/ui-redesign-audit.md` |
| 2. Brief | Done | `docs/designs/ui-redesign-brief.md` |
| 3. Direction | Done | Option D confirmed by you on 2026-11-09 |
| 4. Design system and spec | Approved 2026-11-09, updated 2026-11-09 | Dark theme changed to pitch black with glass frames on your request. Contrast re-measured for the current tokens (section 2). Section 9 decisions answered |
| 5. Implementation (slices) | In progress | Slices on `main` are listed below. Command palette and scan table completion are open |
| 6. Audit and optimize | Not started | |

### Phase 5 slices on `main` (checked 2026-11-09 against `origin/main` at `b1ab1e1`)

| Slice | Status on `main` | Code |
|---|---|---|
| Tokens and shell (top bar, glass frames, data-age stamp) | On main | `ui-v2/src/styles/`, `ui-v2/src/shell/AppShell.tsx`, `TopBar.tsx`, `DataAgeStamp.tsx` |
| Watchlist and resizable panels (slice 1, decision 6) | On main | `ui-v2/src/shell/ResizablePanels.tsx`, `WatchlistPanel.tsx` |
| Scan table (virtualized rows, sort, column hide and resize, sticky symbol column) | On main. Completion in progress in another session | `ui-v2/src/table/ScreenerTable.tsx`, `ColumnChooser.tsx`, `columnWidths.tsx` |
| Live prices in the scan table (Upstox feed, LTP flash, day change) | On main. Added beyond the slice list (decision 1) | `ui-v2/src/live/useLiveTicks.ts`, `ScreenerTable.tsx` |
| Filter bar and saved presets | On main | `ui-v2/src/filters/`, `ui-v2/src/table/ColumnFilter.tsx` |
| Stock tab with price chart | On main, header and chart only. Other sections not built | `ui-v2/src/stock/StockPage.tsx` (uses lightweight-charts) |
| Sector heatmap | On main | `ui-v2/src/sectors/SectorHeatmap.tsx` |
| Market-session banners and data states | On main | `ui-v2/src/App.tsx` (`sessionBanner`), `ui-v2/src/shell/StateView.tsx`, `ui-v2/src/lib/marketSession.ts` |
| EOD refresh button (with ETA countdown) | On main | `ui-v2/src/shell/EodRefreshButton.tsx` |

### Open slices

- **Command palette (Ctrl/Cmd+K).** Not on main. The top bar shows a "Ctrl K" hint with no handler behind it. In progress in another session.
- **Scan table completion.** In progress in another session. The open checklist items in section 10 depend on it.
- **Everything in section 11, "Open after this batch".**

Next action: merge the command palette and scan table completion, then re-check section 10 against `main`, then start the items in section 11, "Open after this batch", in the order you approve.

Stack: Node.js + TypeScript + Fastify backend. Vite + React + TypeScript frontend, built to static files and served by Fastify. TanStack Table with row virtualization. TanStack Query. TradingView Lightweight Charts v5 only. Tailwind v4 and shadcn/ui, confirmed by you on 2026-11-09 (section 9).

## 1. Principles

1. The app shows data and does not give a verdict. Every label (buy, add, hold, trim, sell, rebalance) sits next to the inputs that produced it.
2. Calm by default. Dark is the default. The screen must not add to fear in a falling market.
3. The table is the entry point. Clicking a company opens its stock tab.
4. One event record feeds both the timeline and the Telegram alert. The two always match.
5. Semantic tokens only. No hard-coded colours in components.

## 2. Design tokens

All colour values must reach WCAG AA: 4.5:1 for body text, and 3:1 for large text, UI boundaries and focus indicators.

Dark theme changed on your request to pitch black (`#000000`) with translucent glass frames. Dark surfaces are `rgba`, so every dark contrast figure below is measured after compositing each surface over `#000000`, which is the page colour. The composited surfaces are:

- `--surface` `rgba(255,255,255,0.06)` = `#0F0F0F` on black
- `--surface-2` `rgba(255,255,255,0.10)` = `#1A1A1A` on black
- `--surface-solid` `#0A0D12` (opaque, used for sticky and dropdown elements)

**Method.** WCAG 2.x relative luminance, contrast = (L1 + 0.05) / (L2 + 0.05). Values were measured on 2026-11-09 from `ui-v2/src/styles/tokens.css`.

### 2.1 Dark theme: measured 2026-11-09

Body text (4.5:1 required):

| Pair | on `--bg` `#000000` | on `--surface` `#0F0F0F` | on `--surface-2` `#1A1A1A` | on `--surface-solid` `#0A0D12` | Result |
|---|---|---|---|---|---|
| `--text` `#E2E8F0` | 17.03 | 15.55 | 14.12 | 15.78 | Pass |
| `--text-muted` `#94A3B8` | 8.19 | 7.48 | 6.79 | 7.59 | Pass |
| `--gain` `#34D399` | 10.92 | 9.97 | 9.05 | 10.12 | Pass |
| `--loss` `#FB7185` | 7.80 | 7.12 | 6.47 | 7.23 | Pass |
| `--neutral` `#94A3B8` | 8.19 | 7.48 | 6.79 | 7.59 | Pass |
| `--accent` `#818CF8` | 7.04 | 6.43 | 5.83 | 6.52 | Pass |
| `--caution` `#FBBF24` | 12.58 | 11.48 | 10.43 | 11.66 | Pass |

UI boundaries and focus (3:1 required):

| Pair | on `--bg` | on `--surface` | on `--surface-2` | on `--surface-solid` | Result |
|---|---|---|---|---|---|
| `--focus` `#A5B4FC` | 10.53 | 9.62 | 8.73 | 9.76 | Pass |
| `--border-ui` `#7C8A9E` | 5.99 | 5.46 | 4.96 | 5.55 | Pass |
| `--border` `rgba(255,255,255,0.14)` (decorative) | 1.35 | 1.47 | 1.53 | 1.45 | Fails 3:1, by design: decorative only, exempt from 1.4.11 |

Every body-text and UI pair passes in dark. The one failing row is the decorative divider, as the decision below states.

### 2.2 Light theme: unchanged

The light-theme values were not changed in this update. They were re-measured with the same method, and the figures match the earlier measurement.

| Pair | on `--bg` `#F8FAFC` | on `--surface` `#FFFFFF` | on `--surface-2` `#F1F5F9` | Result |
|---|---|---|---|---|
| `--text` `#0F172A` | 17.06 | 17.85 | 16.30 | Pass |
| `--text-muted` `#475569` | 7.24 | 7.58 | 6.92 | Pass |
| `--gain` `#047857` | 5.24 | 5.48 | 5.01 | Pass |
| `--loss` `#BE123C` | 6.01 | 6.29 | 5.74 | Pass |
| `--neutral` `#475569` | 7.24 | 7.58 | 6.92 | Pass |
| `--accent` `#4338CA` | 7.55 | 7.90 | 7.21 | Pass |
| `--caution` `#B45309` | 4.80 | 5.02 | 4.58 | Pass |
| `--focus` `#3730A3` | 9.49 | 9.93 | 9.07 | Pass (3:1) |
| `--border-ui` `#7A8699` | 3.52 | 3.69 | 3.36 | Pass (3:1) |
| `--border` `#CBD5E1` (decorative) | | | | Fails 3:1, decorative only |

### 2.3 Known issue: translucent sticky header

The table header cells use `bg-surface-2`. In dark that is translucent (`rgba` 0.10), and the glass rule in `ui-v2/src/styles/index.css` makes only `bg-surface` sticky elements opaque. So rows that scroll under the header can show through it, and the header text then loses its measured contrast. The fix is to give sticky header cells `--surface-solid`. Not changed in this update, because it is a source change. Listed in section 11.

### 2.4 Colour (semantic names, CSS variables on `:root`)

| Token | Dark (default) | Light | Use |
|---|---|---|---|
| `--bg` | `#000000` | `#F8FAFC` | Page background |
| `--surface` | `rgba(255,255,255,0.06)` | `#FFFFFF` | Glass frames for cards and panels. Composites to `#0F0F0F` on black |
| `--surface-2` | `rgba(255,255,255,0.10)` | `#F1F5F9` | Table header, hover, tabs strip. Composites to `#1A1A1A` on black. See section 2.3 |
| `--surface-solid` | `#0A0D12` | `#FFFFFF` | Opaque surface for sticky and dropdown elements, so text stays readable over scrolling content |
| `--border` | `rgba(255,255,255,0.14)` | `#CBD5E1` | Decorative dividers and table lines only |
| `--border-ui` | `#7C8A9E` | `#7A8699` | Input, select, button and tab outlines. Meets 3:1 on all surfaces (section 2.1 and 2.2) |
| `--text` | `#E2E8F0` | `#0F172A` | Primary text |
| `--text-muted` | `#94A3B8` | `#475569` | Labels, secondary text |
| `--gain` | `#34D399` | `#047857` | Price up (always with ▲ and sign) |
| `--loss` | `#FB7185` | `#BE123C` | Price down (always with ▼ and sign) |
| `--neutral` | `#94A3B8` | `#475569` | Unchanged (always with ● or "0.00%") |
| `--accent` | `#818CF8` | `#4338CA` | Selection, focus ring, active tab |
| `--caution` | `#FBBF24` | `#B45309` | Stale data, warnings, "not available" |
| `--focus` | `#A5B4FC` | `#3730A3` | Keyboard focus outline (2px minimum) |

Gain and loss are colour-blind-safe because the sign and the arrow carry the meaning, not the colour.

The dark values are defined once under `:root:not([data-theme="light"])` inside `@media (prefers-color-scheme: dark)`, and again under `:root[data-theme="dark"]`. This follows the convention in the project's global rules. `tokens.css` is the source of these values.

### 2.5 Type

- Text: Fira Sans. Numbers: Fira Code with `font-variant-numeric: tabular-nums`. Both are already used by the live app.
- Scale (px): 12, 13, 14 (body), 16, 20, 24. Table rows use 13 or 14. The stock header price uses 24.
- **Code on `main`:** the stock header price uses `text-lg` (18px), not 24. Not changed here. Open as a small fix when the stock tab sections are built.

### 2.6 Spacing and shape

- Spacing steps: 4, 8, 12, 16, 24, 32.
- Radius: 6px on cards, 4px on controls.
- Table row height: 32px (dense), 40px (touch, when the viewport is below 768px).

### 2.7 Motion

- Price-change flash: a tint on the changed cell, then fade out. The code (`LtpCell` in `ScreenerTable.tsx`) uses a 700ms tint, so the spec's 600ms figure is out of date.
- Under `prefers-reduced-motion: reduce`, the flash is replaced by a static 2px left bar in the gain or loss colour. No layout shift in either case. **Not built on `main`:** the code keeps the colour tint under reduced motion and has no bar. See section 10.

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
| `ResizablePanels` | custom | Left panel and main area, split by a drag handle. Slice 1 (decision 6). On `main` |
| `WatchlistPanel` | custom | Left panel listing watchlist symbols. Slice 1 (decision 6). Empty state when no symbols. On `main` |
| `TabStrip` | custom | Open stock tabs. Ctrl-click or middle-click opens a stock in a new browser tab at its own URL |
| `ScreenerTable` | TanStack Table | Sortable, filterable, row virtualization, sticky header and first column, column hide and resize. On `main`; completion in progress |
| `ColumnFilterPopover` | shadcn/ui Popover (if confirmed) | Replaces the current filter popover. Current popover is `ui-v2/src/table/ColumnFilter.tsx` |
| `FilterBar` | custom | Scan filters, saved presets. On `main` (`ui-v2/src/filters/`) |
| `ChangeValue` | custom | Enforces sign, arrow and tabular numerals (section 3). Current formatting in `ui-v2/src/lib/format.ts` |
| `StockHeader` | custom | Price, change, distance from ATH, stance. On `main` (`StockPage.tsx`): symbol, company name, latest close and signed % change with arrow. Not built: distance from ATH and stance |
| `PriceChart` | lightweight-charts v5 | OHLC legend, moving averages, volume pane, timeframe bar, right price scale. No TradingView branding. Chart is on `main`, other features not confirmed |
| `EventTimeline` | custom | Reads the shared event record (section 6). Not built |
| `GuidelineCard` | custom | A label, plus its inputs and "what would change it". Not built |
| `FundamentalsPanel` | custom | Reads from the database only. Not built |
| `ConcallSummaryPanel` | custom | Reads from the database only (section 7). Not built |
| `OrderBookPanel` | custom | Backlog and contract awards from stored announcements. Not built |
| `StateView` | custom | One component for loading, empty, error, market-closed, pre-open, stale and reconnecting. On `main` (`ui-v2/src/shell/StateView.tsx`) |
| `Command` palette | shadcn/ui Command (if confirmed) | Ctrl/Cmd+K symbol search. Not on `main`. In progress in another session |
| `Sparkline` | custom SVG | Row sparkline in the table. Not confirmed on `main` |
| `SectorHeatmap` | custom | Built from scanner data. Gain and loss shown with sign and arrow, not colour alone. On `main` |

## 5. Screens

### 5.1 Home (scan table)

- Full-width `ScreenerTable` with the latest ATH run. On `main`.
- A header line shows the run date, the run's age, and the data-age stamp. The stamp reads the run's own timestamp, not the browser clock (audit item 6). On `main` (`DataAgeStamp.tsx`).
- Above the table: a shortlist of stocks with new events, and the event feed. **Not built.** Open after this batch (section 11).
- Columns: symbol (sticky), name, price, change, ATH date, distance from ATH, sparkline, sector, stance. Each column can be hidden or resized. Hide and resize are on `main`. Completion of the column set is in progress.

### 5.2 Stock tab

- Opens from a company name in the table. Closing a tab does not close others. On `main` (`TabStrip.tsx`, `StockPage.tsx`).
- One grid, in this order: header (price, change, distance from ATH, stance), chart, announcements and events, fundamentals, concall summaries, order book, guidelines with their inputs. On `main`: the header (price and change) and the chart only. The other sections are open (section 11).
- Each section shows its own `StateView` for loading, empty and error.

### 5.3 Portfolio

- Holdings list, with a guideline per holding and its inputs.
- Recent updates per holding.
- Three sources: Zerodha (Kite API, daily login step), Upstox API, CSV import with a column mapping per broker. One holdings model for all three.
- Holdings are never named in alerts (brief, Events and alerts).
- **Not built as a screen.** A `HoldingsPanel` is on `main` in the shell (`ui-v2/src/shell/HoldingsPanel.tsx`). It is not this screen. The screen is blocked on the Upstox data-sharing licence check (section 9, decision 1).

### 5.4 Events

- Company red flags and policy items, each with its source link.
- Filter by type and date.
- **Not built.** Open after this batch (section 11).

### 5.5 Settings and operations

- Existing master configuration and API key screens carried over. Write actions need an authentication decision first (section 9).
- **Not built** in UI v2. Open after this batch (section 11).

## 6. Event rule

- One event record per event. The timeline and the Telegram alert both read it.
- An alert names only the company and the event. It never names a holding.
- Policy items show category, severity, a one-line reason, affected companies and the original link. The LLM classifies, and you make the call.

## 7. Data rules

- The UI reads only from the database. It never calls a third-party site.
- The browser never connects to Postgres, Mongo or Upstox directly. All database reads and all live market-data feeds go through the Fastify API in `server/`. Live Upstox data is pulled by the server and passed to the browser over the API (for example a server-sent event stream). Set by you on 2026-11-09. On `main`: `ui-v2/src/live/useLiveTicks.ts` reads the SSE route.
- Fundamentals: the collector brings them into the database (decision 1, 2026-11-08).
- Concall content: the local LLM generates summaries from stored transcripts and presentations, using `docs/designs/concall-summary-template.md`. No site text is copied (decision 2).
- Order book: the company's backlog and contract awards, from stored announcements (decision 3).
- Market mood (breadth, volatility) is not available. It shows as "Not available", never a guess.
- End-of-day prices are the only data today. The timeframe bar shows intraday options as "Not available" until an intraday source exists.

## 8. States

Every data view uses `StateView` and handles these states:

| State | Shown when | Visual on `main` |
|---|---|---|
| Loading | A request is in flight | Skeleton rows in `StateView`, pulse only under `motion-safe`, no layout shift |
| No results | The query returns zero rows | On `main`: "No results match these filters." with a "Clear filters" action when filters are set, otherwise "No results for this run." (`ScreenerTable.tsx`) |
| API error | The request fails | `StateView` alert in `--loss`, with the message. Retry button where the screen has one. Never shown as "No runs yet" (audit item 7) |
| Market closed | Outside NSE/BSE hours | Caution banner above the Home table with the last close time (`App.tsx`) |
| Pre-open | 09:00 to 09:15 IST | Caution banner above the Home table (`App.tsx`) |
| Stale data | The run is older than the expected trading days | Caution banner above the Home table with the age in trading days. Stale wins over pre-open. The stamp itself does not change colour |
| Reconnecting | The live feed drops | Caution `StateView` above the table: "Live prices reconnecting. Showing the last saved prices." (`ScreenerTable.tsx`). Live feed is on `main` (decision 1) |

Colour is never the only signal in these states. Each one carries a text message.

## 9. Open decisions

1. **WebSocket for live tickers. Answered 2026-11-09: Upstox market-data feed.** Live, reconnecting and pre-open states depend on it. Before use, the Upstox data-sharing licence terms must be checked (brief, Blocker 3). Cost is still unknown. The feed is on `main`, and the licence check is still open (section 11, Portfolio).
2. **Tailwind v4 and shadcn/ui. Answered 2026-11-09: Tailwind v4 + shadcn/ui.**
3. **Authentication for write endpoints. Answered 2026-11-09: local-only bind, no token.** The audit found that config and secret writes are open on all interfaces (audit item 1). The bind to 127.0.0.1 stops other machines on the network. It does not stop a web page open in the same browser from calling localhost. Accepted risk, recorded here so it is a known trade-off.
4. **Border and neutral contrast. Closed 2026-11-09.** `--neutral` passes. `--border` failed 3:1, so `--border-ui` was added for control outlines (section 2).
5. **Skills. Answered 2026-11-09: install shadcn/ui, Vercel agent-skills, and financial-ui-patterns and styles.** Install is pending. The brief says to remove them after implementation. Their rules are also written into this spec (sections 2 to 4).
6. **Watchlist and resizable panels. Answered 2026-11-09: slice 1.** Layout rules for slice 1:
   - At 768px and wider: a left panel (default 240px, min 200px, max 480px) and the main area. A vertical separator with `role="separator"` sits between them. Arrow keys move it 16px. Pointer drag works too. The width is saved in `localStorage` under `ms-watchlist-width`, with try/catch. Storage can fail, and the layout must still work without it.
   - Below 768px: the watchlist stacks above the main area, full width, with no resize handle.
   - Watchlist content: the panel takes a list of symbols as a prop. Slice 1 passes an empty list, so it shows "No symbols on the watchlist yet." No fake symbols. Adding and removing symbols belongs to the scan table slice, which brings the data source.
   - Persistence of the watchlist itself (localStorage or server) is an open question for that later slice.
7. **TypeScript, Vite and Vitest major versions. Answered 2026-11-09: option B.** TypeScript stays at 7.0.2. Vite is pinned to 7.3.7 and Vitest to 4.1.12, because Vite 8.3.6 and Vitest 5.1.0 were released days before the decision. `@vitejs/plugin-react` is pinned to 5.2.0, because 6.x requires Vite 8. All three are exact pins. Revisit after the Vite 8 and Vitest 5 lines have had more time in use.

## 10. WCAG AA checklist

Each box is ticked only when the evidence is on `main`. Re-checked 2026-11-09 against `origin/main` at `b1ab1e1`. Boxes are re-checked when the scan table and command palette merge.

- [x] Text and signal token pairs measured in light and dark, with dark composited over `#000000` (section 2).
- [x] `--border` against surfaces measured (decorative, fails 3:1 by design). `--neutral` on `--bg` measured. `--border-ui` added for controls and measured on all surfaces.
- [ ] Gain and loss have a sign and an arrow everywhere (section 3). **Open:** `HoldingsPanel` shows gain and loss as signed percentages with no arrow (`ui-v2/src/shell/HoldingsPanel.tsx`, `formatSignedPct`, used at lines 180 to 208). The other gain and loss sites on `main` use arrows: `ScreenerTable`, `StockPage`, `SectorHeatmap`, `WatchlistPanel`.
- [ ] Table rows are keyboard reachable. Enter and Space open the stock. Visible focus ring on every interactive element. **Partly on `main`:** the company cell is focusable with `tabIndex` 0, and Enter or Space opens the stock (`OpenStockCell` in `ScreenerTable.tsx`). The focus ring is the global `:focus-visible` rule in `index.css`. **Open:** rows are not keyboard reachable as rows, so arrow-key row movement is not built.
- [x] Sticky table header has a real scroll container (audit item 16). The table body is a `max-h-[60vh] overflow-auto` container, and header cells are `sticky top-0` (`ScreenerTable.tsx`). **Note:** the header background is translucent in dark, which is a separate issue in section 2.3.
- [ ] `prefers-reduced-motion` replaces the flash with the static bar. **Open:** `LtpCell` in `ScreenerTable.tsx` keeps a 700ms colour tint under reduced motion (`motion-reduce:transition-none` only removes the fade). No 2px bar is built.
- [x] Layout works at 375px wide with no horizontal page scroll, and the data-age stamp stays visible. Checked 2026-11-09 in the browser (commit `efc09fb`, "Fix top bar wrapping at phone width", an ancestor of `origin/main`).
- [x] Colour is never the only signal for state (stale, closed, pre-open, reconnecting, error). Each state carries a text message on `main` (section 8).

## 11. Next steps after approval

1. Build in slices, each approved before the next: tokens and shell, scan table, filter bar and presets, stock tab and chart, sector heatmap, states. Status of each is in section 0.
2. Run the old UI side by side until you approve the switch (brief, Constraints).
3. Audit and optimize: 5,000-row test and 1-second tick test.

### Open after this batch

These items remain after the command palette and scan table completion merge. Each is open against the code on `main`.

1. **Stock tab sections.** Events, fundamentals, concall summaries, order book, and guidelines with their inputs (section 5.2). Only the header and chart are on `main`.
2. **Home event feed and shortlist** above the table (section 5.1). Not built.
3. **Events screen** (section 5.4). Not built.
4. **Settings and operations screen** (section 5.5). Not built.
5. **Portfolio screen** (section 5.3). Blocked on the Upstox data-sharing licence check (section 9, decision 1). The shell's `HoldingsPanel` is separate and on `main`.
6. **Phase 6 audit.** The 5,000-row render test and the 1-second tick test (step 3 above). Not run.
7. **Checklist items still open** (section 10): gain and loss arrow in `HoldingsPanel`, keyboard row access, and the reduced-motion bar.
8. **Translucent sticky header** (section 2.3): give sticky header cells `--surface-solid`.
9. **Command palette** (Ctrl/Cmd+K). In progress in another session. The top bar's "Ctrl K" hint has no handler until it merges.
