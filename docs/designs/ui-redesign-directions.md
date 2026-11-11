# UI redesign: Phase 3 directions

Date: 2026-11-08. Superseded: the user chose Option D on 2026-11-09 (see `docs/designs/ui-redesign-spec.md`). The options are kept for the record. Brief: `docs/designs/ui-redesign-brief.md`.

Effort is relative: S (days), M (weeks), L (more than a month), for one developer.

Each option uses the same data and rules. They differ in layout and density.

## Option A: Dense terminal

- **Style:** dark by default, dense rows, keyboard-first, very little decoration.
- **Palette:** near-black slate background, emerald gain, rose loss, amber caution. Tokens still semantic and colour-blind-safe.
- **Fonts:** Fira Code for numbers, Fira Sans for text. Both already in use.
- **Layout:** left watchlist (scan results), centre chart, right event feed for the selected stock. Panels resizable.
- **Pros:** fast to scan 5,000 rows. Fits a trader's habits. Shows the most data on one screen.
- **Cons:** dense screens tire you, especially in a fearful market. Light mode is an afterthought. Harder for a new user.
- **Effort:** L.

## Option B: Clean dashboard

- **Style:** cards, generous spacing, light by default, calm colours.
- **Palette:** soft off-white background, deep teal accent, muted gain and loss. Closest to the current app.
- **Fonts:** Fira Sans for text, Fira Code for numbers.
- **Layout:** Home shows the latest run, the event feed, and a shortlist. Stock pages are a sequence of sections: summary, chart, timeline, events, guidelines.
- **Pros:** calm, easy to read, suits a second-opinion visit. Lowest effort. Easiest to build in slices.
- **Cons:** shows less per screen. A long table still needs virtualization. Side-by-side comparison of stocks is harder.
- **Effort:** S to M.

## Option C: Table and chart split (recommended on 2026-11-08; not chosen)

- **Style:** structured, clear hierarchy, calm by default, dark and light.
- **Palette:** same semantic tokens as the others. Neutral slate with one accent.
- **Fonts:** Fira Sans and Fira Code.
- **Layout:** left side is the scan table, virtualized and sortable (about 40% width). Right side is the selected stock: price chart, company timeline with events, guidelines with their inputs. Portfolio is a separate tab that reuses the same right-side panel.
- **Pros:** matches your flow exactly: pick from the scan report, then see the chart, the events, and the timeline together. The same event appears in the alert and the timeline without switching screens. Scales to 5,000 rows.
- **Cons:** more layout work. Needs a clear mobile fallback (stacked, table first, then detail). Panel resizing adds complexity.
- **Effort:** M to L.

## Option D: Screener table with a full stock page (your proposal)

- **Style:** dense, screener-like tables plus a trading-style chart. Dark by default, light available. Same semantic tokens and sign-plus-arrow rule as the others.
- **Palette and fonts:** same tokens as C. Fira Code for numbers, Fira Sans for text.
- **Layout:**
  - Home is the scan table: sortable, filterable, virtualized, with sticky first column.
  - Clicking a company name opens a stock tab. Tabs sit in a strip at the top, so several stocks can stay open and be switched between. Ctrl-click or middle-click opens the stock in a new browser tab at its own URL.
  - The stock page is one dense screen with sections in a grid: header (price, change with sign and arrow, distance from ATH, stance), chart, announcements and event timeline, fundamentals, concall summaries, order book, and guidelines with their inputs.
- **Event rule:** the timeline and the Telegram alert read the same event record, so they always match.
- **Pros:** you reach a conclusion without leaving the page. Matches your screener + TradingView + concall.in pattern. Several stocks can be compared through tabs.
- **Cons:** the stock page is the hardest screen to build. It needs data sources that do not exist yet (see below). Tabs add state to manage.
- **Effort:** L.
- **Data gaps (must be decided before Phase 4):**
  - Reference pages (layout and fields only, no scraping): screener.in company page for fundamentals; concall.in tabs (overview, summary, Q&A, transcript, annual report summary) for concall; a TradingView-style chart layout (OHLC legend, moving averages, volume pane, timeframe bar, right price scale). Built with lightweight-charts; TradingView branding is not copied.
  - Order book here means the company's order backlog and contract awards from exchange announcements, not market depth. The app already stores announcements, so this section can use them.
  - Fundamentals and concall content come from third-party sites whose terms need a check before any pull. Option: build fundamentals from exchange filings already stored, and generate concall summaries from transcripts with the local LLM rather than copying site text.

## Comparison

| | A: Dense terminal | B: Clean dashboard | C: Table and chart split |
|---|---|---|---|
| Fits your flow (scan, then detail) | Good | Fair | Best |
| Fear control, calm screen | Weak | Strong | Good |
| Rows visible at once | Most | Fewest | Most of the table, with detail |
| Mobile | Weak | Good | Needs fallback |
| Effort | L | S to M | M to L |

## Recommendation

**Option C.** Your workflow is to pick a stock from the report and then check its chart, events, and timeline together. Option C keeps those three on one screen. It also keeps the table fast enough for 5,000 rows.

Mitigate its cost by building in slices: tokens and shell first, then the table, then the detail panel. Option B's layout can serve as the mobile fallback.

## Spec rules that apply to every option

- Tabular numerals, sign and arrow on every change, INR lakh and crore format.
- Gain and loss never shown by colour alone.
- WCAG AA contrast in light and dark mode.
- `prefers-reduced-motion` respected for flashes.
- Semantic tokens only. No hard-coded colours.

## Your pick

Which option do you want: A, B, or C? If you pick C, I'll move to Phase 4: the design tokens, component list, screen-by-screen changes, and formatting rules, for your approval.
