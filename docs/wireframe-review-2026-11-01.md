# Wireframe review, 1 Nov 2026

Approved by the user on 2026-11-01 (all 17 decisions, all 5 proposals). Removed from the wireframe review screen on 2026-11-01; kept here as the record.

Decision 10 was reversed on the same day. The entry below shows the wording as approved and then the final form. The changes are listed in CHANGELOG.md, and open work is tracked in handoff.md.

## Design decisions for approval (17 items)

Each item shows what it is, the recommended default, and the glossary term it links to. All 17 were approved as recommended.

1. **Verdict wording for stocks you do not own.** The four verdicts are BUY, HOLD, EXIT, REJECT. For a stock you do not own, HOLD and EXIT both mean "not a buy", and the page says so. Your spec has no fifth value for this.
   Recommended: Keep four verdicts. HOLD and EXIT read as not a buy when nothing is held.
2. **Governance points required for a buy.** A buy is blocked while debt (4), pledged shares (5) or exceptional items (18) are Not assessed, and the reason is shown. Other points can stay Not assessed.
   Recommended: Block on points 4, 5 and 18. Every other point is shown but does not block.
3. **A 3 of 3 stock with a required point missing.** It is shown as HOLD with the reason "buy blocked", and counted under Not assessed in the strip. It is not shown as BUY.
   Recommended: Show HOLD with a visible buy-blocked reason.
4. **All-time high tolerance.** "At the high" means the latest close is within 2% of the highest close in the data.
   Recommended: 2% on a closing basis.
5. **Profit high is within the data window.** Profit history is about 13 quarters and 12 years, so the profit rule says "highest within the data window", never "lifetime".
   Recommended: Use "within the data window" wherever the rule is worded.
6. **Exit price proposal rule.** Proposal is the lower of the 200-day EMA and 80% of the buy price, kept within 5% to 30% trade risk. Because it takes the lower, the 80% figure usually wins, so the proposal is mostly a 20% stop. A tighter alternative is the higher of the two.
   Recommended: Keep the plan's rule and always show it beside the number. Your own exit price overrides it.
   Note: the long-term average in this rule is changed to the 200 DMA (simple) by decision 10 below.
7. **Largest allocation.** A cap on any one position, as a share of Net Asset Value. Without it a very tight exit asks for a huge position.
   Recommended: 15% of Net Asset Value, editable in the calculator.
8. **Trim advice.** Your rules say when to add and when to exit but not when to trim. The calculator shows Trim only as arithmetic against the target size.
   Recommended: Show Trim as information, not as a rule signal.
9. **Verdict for a stock you hold at 3 of 3.** BUY means new money may be added. A held stock at 3 of 3 shows BUY.
   Recommended: Show BUY, with Phase 4 saying hold and add.
10. **200-day EMA, not the simple average.** As first approved: the scanner today computes a 200-day simple average, and the spec says exponential. Recommended: use the exponential average.
    Reversed on 1 Nov 2026. Final form: the long-term line is the 200 DMA (simple) only, with no EMA on it. The 50 EMA stays for the medium term. The 200 DMA is the simple average of the last 200 daily closes and stays 200 days on weekly and monthly charts. The exit line is worked out from the 200 DMA.
11. **Holdings outside the universe.** They are tested on what can be computed (price, 200-day EMA, 52-week return) and the rest is Not assessed. They are never dropped.
    Recommended: Test them and mark them Not in universe.
    Note: "200-day EMA" in this item reads as 200 DMA after decision 10.
12. **Rank cut on the Stocks list.** Eligible stocks (governance passed, 2 of 3 or better) are ranked by 52-week return. A rank cut line separates them from the rest, which are shown only under All evaluated.
    Recommended: Cut at the eligibility line, not at a fixed count.
13. **Holdings input: upload first.** You do not want to paste or hand-build a file each time, and brokers export different Excel layouts, so the importer finds the key columns itself. The position-sizing calculator needs only two totals, Investment Value and Net Asset Value. A broker login needs a Kite Connect key and a daily login, which the scanner does not have today.
    Recommended: Upload first: an Excel or CSV file with a column mapper, saved per header layout so the next file with the same headers imports with no questions. Broker login and testing on sample broker exports are a next phase. A totals-only path is always there and feeds the position-sizing calculator.
14. **Mutual funds and ETFs in an import.** Broker files mix funds and ETFs with shares. The strategy scores individual stocks only, but your funds still count toward how much you hold in total and how much risk you carry.
    Recommended: Count mutual funds and ETFs for total allocation and risk management. Do not score them with the strategy.
15. **Chart defaults and events.** These set what the stock chart shows when it opens. Putting every event on the chart lets you see what was happening when the price moved.
    Recommended: Candlestick on a white background, with a 50 EMA and a 200 DMA (daily moving averages on every timeframe). Daily is the default, with Weekly and Monthly. RSI 14, and volume with delivery. All events sit on the chart: results, dividends, splits and bonus, filings, and verdict changes. Compare with the Nifty 500 and the sector index.
16. **Glossary tooltips on the label text.** The (i) buttons add clutter. A dotted underline on the label shows that a term has an explanation and keeps every screen clean.
    Recommended: Open the tooltip on hover or focus of the label text (dotted underline) instead of an (i) button. Every complicated title keeps a glossary entry.
17. **Interface build.** The wireframe uses hand-written CSS that mirrors Tailwind tokens, so it stays one offline file. The real interface is a separate build.
    Recommended: Build it in Node.js with Tailwind and TradingView Lightweight Charts. Wireframe first, then your sign-off, then code. No custom image is pushed to a registry.

## Decided by you (recorded, not open)

- The calculator sizes against Net Asset Value. Investment Value is the secondary tab. Net Asset Value is Investment Value plus notional profit, or minus notional loss.
- No sin-business filter anywhere. The sin filter is dropped.
- No positions board and no portfolio management. You manage your own positions. The system gives entry and exit signals, and a sizing calculator only.
- Scope is the universe. Holdings are checked against the exit rules after the table is built, and are not stored beyond the session.
- Fundamentals are labelled "Company financials" and index data is labelled "Exchange index data". The third-party fundamentals connector is removed. Index data comes from the price-data feed already in use.
- No order placement and no buy or sell buttons.
- The strategy drives scoring and ranking. The old analyst stance stays as a context column only.
- The WhatsApp bot is the next phase.

## Calculator function contract

One pure function, ready to port to Python.

`sizePosition(input)` returns `output`. It touches no page state, no clock and no network, so the same arithmetic can be ported one to one and reused by the future API.

Input fields: investmentValue (number), notionalPnL (number), cashAvailable (number or null), holdingsCount (integer or null), symbol (string, label only), buyPrice (number, above 0), exitPrice (number, below buyPrice), riskPct (number, default 1.2), capPct (number, default 15), sizeAgainst ("nav" or "investment", default "nav"), heldQuantity (integer or null), averageCost (number or null), maxPositions (integer, default 15).

Output fields: valid, errors, warnings, netAssetValue, riskBase, riskBudget, tradeRiskPct, rawAmount, capAmount and capped, cashLimited, targetQuantity, action ("buy", "add", "hold", "trim" or "not_adding"), quantityToBuy and quantityToTrim, finalQuantity, amountToInvest and positionCost, allocationPctOfNav, lossAtExit and lossAtExitPctOfNav, comparison (nav and investment, each with riskBase, riskBudget, rawAmount, amount, quantity and capped).

## UI implementation notes (for the build, not for approval)

- Chart library: TradingView Lightweight Charts. Open source, runs in the browser, and is fed by our own API. No external data fetch from the browser.
- Chart features drawn in this wireframe: candlesticks on a white background, a 50 EMA and a 200 DMA on every timeframe, Daily as the default with Weekly and Monthly, RSI 14, a volume histogram with delivery, crosshair with a date and price readout, an all-time-high price line, Nifty 500 and sector index comparison rebased to 100, range buttons and a linear or log scale.
- Events on the chart: results, dividends, splits and bonus, filings and verdict changes, each shown on its date.
- Architecture: a Node.js app on top of the Python analytics API. The Node app holds no rules; the verdict, score and sizing come from the API.
- Styling: the wireframe uses hand-written CSS that mirrors Tailwind tokens, so it stays one offline file. The real build uses Tailwind.
- Holdings import is upload first: an Excel or CSV file with a column mapper that is saved per header layout. Totals only is always available. Broker login is a next phase.
- Keyboard: arrow keys move the chart crosshair; Enter opens a focused table row; Escape closes an open tooltip; the segmented controls and the base tabs use arrow keys.
- Tooltips: a glossary tooltip opens when you hover or focus the label text, which has a dotted underline. There are no (i) buttons. On touch screens a tap opens it.
- Tooltip text comes from the glossary endpoint, which reads the same glossary as the Excel header comments, so the two cannot drift apart.

## Proposals for approval (5)

Each proposal was approved as recommended ("Yes").

- **P1. Sticky verdict header on the stock page.** The verdict, score and Back stay pinned while you scroll through the 18 governance points and the four phases. Yes.
- **P2. Compare two stocks.** Pick any two stocks and see their three rules, governance counts and relative price chart side by side. Useful when two BUY candidates compete for the same cash. Yes, after the first release.
- **P3. Saved filters.** Remember the verdict, sector and score filters you last used on the Strategy table, in your own browser only. Yes. Browser storage only, no account.
- **P4. Exit watch count in the navigation.** A small count beside Review Holding showing how many loaded holdings trigger an exit rule, with the word in the accessible name. Empty until holdings are loaded this session. Yes.
- **P5. Sortable columns and a column chooser.** Click a header to sort. A Columns menu shows or hides columns, so the dense table can be trimmed on small screens. Yes, with the current column set as the default.
