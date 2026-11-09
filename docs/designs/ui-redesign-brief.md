# UI redesign brief (Phase 2 output)

Date: 2026-11-08. Status: Phase 2 complete, pending your confirmation. Phase 1 audit: `docs/designs/ui-redesign-audit.md`.

## Purpose

A decision-support view for Indian equities (NSE/BSE, INR, IST). The app shows the data needed for a decision. It does not give a verdict. Each stock shows its data beside it, so you can make your own call.

## Your workflow today

1. Open the app. It lands on Home, showing the latest run.
2. Open the ATH scan report. ATH is the only strategy so far. Strategies will be added later, so the design must not assume ATH is the only one.
3. Work through the top results. For each, check technical structure and fundamentals, and look at recent company news and filings.
4. Review your portfolio. Decide whether a holding needs buy, add, hold, trim, sell, or rebalance. Check recent updates on each holding.

Steps 1 to 3 exist in the live app. Step 4 is new.

## When you use the app

- Not continuously. You open it for a second opinion, or for a heads-up before you start fresh.
- Often when the market feels too strong or too weak. The screen should help you stay calm and check your reasoning, not add to fear.

## Decision guidelines

- Each holding gets one or more guidelines: buy, add, hold, trim, sell, rebalance.
- Each guideline shows the inputs that produced it, and what would change it.
- No single label is shown without its evidence. A guideline is a prompt to check, not an instruction.

## Events and alerts

- **Company red flags:** filings about fraud, auditor issues, or default. These can be matched against the exchange announcements the app already stores.
- **Policy changes:** government or regulatory changes that could take away a company's core business or competitive advantage. Source: RSS feeds, classified by an LLM. The LLM returns a category, severity, one-line reason, affected companies, and the original link. You make the call.
- **Alerts:** pushed instantly to a private Telegram group. An alert names only the company and the event. It never names your holdings.
- **One event record** feeds both the Telegram alert and the company timeline. They always show the same event.
- **Timing:** the goal is to see an event before the price has absorbed it. Company alerts can arrive within minutes. Policy alerts depend on feed and LLM latency, so expect a few minutes of delay.

## Data and timing

- Today: end-of-day prices and exchange announcements. No intraday prices, no news feed, no macro data.
- Needed for the timing goal: intraday prices (from Zerodha or Upstox during market hours) and near-real-time announcements.
- Market mood (breadth, volatility) is not available yet. It will show as "not available", not as a guess.

## Portfolio sources

Keep all three open. Design one holdings model, with three inputs:

- Zerodha (Kite API). Access token expires daily, so this adapter needs a login step.
- Upstox API.
- CSV import. Columns differ by broker, so each import needs a column mapping.

## Secrets

- Telegram bot token: Docker Swarm secret `telegram_bot_token`. It is read once at startup from `/run/secrets/`, and never shown in the UI or logs.
- Other keys stay in the existing secrets store for now.
- The Docker MCP secret store is not used by this app.

## Constraints

- Keep all current filters, scan logic, API contracts, and routes.
- The old UI stays runnable until you approve the switch.
- Ask before any destructive change.
- Semantic color tokens only. No hard-coded colors in components.
- Flag assumptions. Do not guess.

## Stack (open)

- Brief asks for Next.js or Vite + React, TypeScript strict, Tailwind v4, shadcn/ui, TanStack Table with virtualization, TanStack Query, and lightweight-charts v5 only (no TradingView widgets or iframes).
- Open question: `handoff.md` says Node.js supersedes FastAPI, and `ui/BUILD_PLAN.md` says FastAPI. Confirm before Phase 4.

## Skills not installed

These are not installed. Per your instruction, install them for implementation (Phase 5) and remove them after completion. Until then, their rules are written into the spec:

- financial-ui-patterns and financial-ui-styles
- shadcn/ui
- frontend-design or design-register-commit
- Interface Design
- Vercel agent-skills (react-best-practices, web-design-guidelines)

`ui-ux-pro-max` is installed.

## Financial UI rules (written in, not from the skill)

- Tabular numerals for all prices and percentages.
- Gain and loss shown with a sign and an arrow, never colour alone.
- Indian number format: lakh and crore grouping, INR symbol.
- Colour-blind-safe gain, loss, and neutral tokens.
- Light and dark mode, both meeting WCAG AA contrast.
- Price change flashes must respect `prefers-reduced-motion`, and must not shift layout.

## Must-have screens (from the brief)

- Scan report (ATH): sortable, filterable, virtualized table; sticky header and first column.
- Stock detail: chart (lightweight-charts), company timeline with events, guidelines with their inputs, relative strength.
- Events: company red flags and policy items, each with its source link.
- Portfolio: holdings, guidelines per holding, recent updates per holding.
- Home: latest run, event feed, shortlist of stocks with new events.
- Market-closed, pre-open, stale-data, loading, no-results, API-error, and reconnecting states.

## Decisions (2026-11-08)

1. **Fundamentals:** the collector brings them into the database. The UI reads only from the database. No licensed provider for now.
2. **Concall content:** our local LLM generates the summaries, from transcripts and presentations we store. The prompt and template are ours (`docs/designs/concall-summary-template.md`). No site text is copied.
3. **Order book:** the company's order backlog and contract awards, from announcements already stored.
4. **Direction:** Option D (screener table with a full stock page), as described in `docs/designs/ui-redesign-directions.md`. Waiting for your confirmation.

## Open questions

1. Confirm the stack (Node.js or FastAPI).
2. Confirm the three portfolio sources stay open.
3. Name the policy feeds to start with, and how soon you need a policy item (same day, or a morning digest).
4. Confirm the Telegram alert format (company and event only).
