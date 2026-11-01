# Design System: Market Scanner

Screens: Home, Run dashboard, Results table, Stock dashboard, Cost center, Report dashboard, Master configuration.
Wireframe: `ui/wireframes/index.html` (single file, open in a browser, no server needed).

## 1. Visual Theme & Atmosphere

A dense, quiet research desk. Density 7 ("Daily App Balanced" leaning to "Cockpit Dense"): numbers are
the content, so the interface gets out of their way. Variance 5 (offset asymmetric): pages are a wide
main column beside a narrow context column, never a centered hero and never three equal cards in a
row. Motion 3 (static restrained): a short fade on screen change and a 1 px press on buttons, nothing
that loops. The mood is a well-lit analyst's notebook, not a trading terminal: no candlestick
theatrics, no ticker tape, no glow.

Three principles drive every choice:

1. Numbers first. Each page opens with one plain sentence, then a strip of the figures that matter.
2. The past is visible. Each stock and each run shows what changed since the run before it.
3. Measured data only. The Cost center reports tokens, energy and timing from real runs; no provider prices are stored or displayed.

## 2. Color Palette & Roles

Calm fintech research: cool blue-grey neutrals with a single petrol-blue accent. Petrol sits between blue
and teal, so it never reads as the gain colour. Status colours are semantic data colours only and never decorate.
Each role has a light and a dark value, defined once as CSS variables and switched by `prefers-color-scheme`
(or `data-theme`).

| Role | Light | Dark | Used for |
|------|-------|------|----------|
| Paper (`--bg`) | #F6F8F9 | #0C1317 | Page background |
| Surface (`--surface`) | #FFFFFF | #121B21 | Panels, inputs |
| Tint (`--tint`) | #EEF2F4 | #17222A | Hover rows, skeletons, quiet fills |
| Ink (`--ink`) | #10202B | #E4ECF0 | Primary text (never pure black) |
| Muted (`--muted`) | #435563 | #A0B1BC | Secondary text |
| Faint (`--faint`) | #5B6D7A | #869AA6 | Metadata, captions |
| Hairline (`--line`) | #E1E7EB | #1F2B33 | 1 px dividers |
| Hairline Strong (`--line-strong`) | #C6D0D7 | #2C3B45 | Input borders, strip top rule |
| **Petrol** (`--accent`) | #0B6E8A | #4FB8D6 | The single accent: primary button, active nav, focus ring, chart line |
| On Petrol (`--accent-ink`) | #FFFFFF | #04141B | Text on the accent |
| Petrol Wash (`--accent-soft`) | #E3F1F5 | #10303B | Active segment, selected row |
| Gain (`--gain`) | #166534 | #52D68A | Positive return, Constructive stance, complete status |
| Loss (`--loss`) | #B42318 | #F28B82 | Negative return, failed status |
| Caution (`--caution`) | #8A4B08 | #F0B35E | Cautious stance, "to verify" |
| Gain / Loss / Caution washes | #E4F3EA / #FBEAE8 / #FAEFDD | #12281D / #2D1A19 / #2A2213 | Pill backgrounds |

Banned: purple, neon, gradients, glow, warm/cool grey mixing, pure black, a second accent.
Every text/background pair above is at least 4.5:1 in both themes (lowest: Petrol on Petrol Wash, 5.03 light and 6.07 dark),
checked by calculation.

## 3. Typography Rules

- **Sans:** Fira Sans 400/500/600/700. Headlines 600, tight tracking (-0.01em), sized with `clamp()`. Hierarchy comes from weight and colour, not size.
- **Mono:** Fira Code for every number, symbol, date, id and rate, so columns align and digits do not jitter. Applied everywhere because density is above 7.
- **Body:** 14 to 16 px, line height 1.5, prose capped at 65 characters.
- **Labels:** 12 px uppercase with 0.06em tracking, used only for strip labels and table headers.
- **Banned:** Inter, all serifs (dashboard rule), decorative display faces, gradient text.

## 4. Component Stylings

* **Buttons:** Flat, 44 px tall, 10 px radius. Primary is Petrol with white text; secondary is a 1 px hairline outline. Active state moves 1 px down. No glow, no custom cursor. One primary action per screen.
* **Stat strip:** The replacement for a row of KPI cards. Label, mono value, one line of context, separated by 1 px vertical hairlines, sitting between a strong top rule and a light bottom rule. No boxes.
* **Panels:** Used only for side-column context (conclusion, cost snapshot, assumptions). 16 px radius, 1 px hairline, a whisper shadow tinted to the background. Main content uses top rules and space instead of boxes.
* **Tables:** 48 px rows, sticky header, numbers right-aligned in mono, whole row is the link (keyboard focusable, Enter opens). Horizontal scroll lives inside the table wrapper, never on the page. On phones the table keeps Stock, Price, Below ATH, Stance.
* **Pills:** 12 px text, tinted background with matching ink (Constructive, Mixed, Cautious, At ATH, Complete, Checked, Measured, To verify). Colour is never the only signal; every pill has a word.
* **Segmented controls:** Period, bucket and stance filters. 44 px, pressed state uses Accent Wash and accent ink.
* **Inputs:** Label above, helper text below, error text below that, 44 px, focus ring in accent. No floating labels.
* **Timeline:** A vertical rule with one entry per run: date, stance pill, price and distance in mono, then the diff lines against the previous run. This is the "one record per run, never duplicated" view.
* **Charts:** Inline SVG, one accent series, 26% band as a wash, direct labels instead of legends where possible, and a text alternative on every `svg`.
* **Loaders:** Skeleton blocks the exact size of the content they replace. No spinners.
* **Empty states:** A sentence saying why nothing matched and one action to clear the filters.
* **Errors:** Inline, next to the field or the table, in Loss Red with an icon and text.
* **Navigation:** Top bar (Home, Latest run, Report dashboard, Cost center). Under it a bar with Back, Home and a breadcrumb on every page except Home. Back uses history and falls back to Home.

## 5. Layout Principles

- Content max-width 1400 px, 32 px gutters (16 px on phones).
- CSS Grid, 8/4 split for Home, Run and Stock, 7/5 for Report, 9/3 for Cost. Under 1280 px the Cost side panels drop below in a two-column row; under 1024 px everything is one column; under 768 px strips become a two-column grid and low-priority table columns are hidden.
- Each page: eyebrow, H1, one sentence, one primary action at the right, then the strip, then content.
- No overlap, no absolute-positioned stacking, no `calc()` percentage hacks. Full-height containers use `min-height: 100dvh`.
- Touch targets are at least 44 px, including breadcrumb and inline table links.
- No horizontal page scroll at 375, 768, 1024 or 1440 px (checked in the browser pane on every screen).

## 6. Motion & Interaction

- Screen change: 350 ms opacity and 6 px translate, spring-like ease (`cubic-bezier(.22,1.2,.36,1)`).
- Distance bars grow once from the left in 700 ms (`transform: scaleX`).
- Rows and buttons: 150 ms background change; buttons press 1 px.
- Animate only `transform` and `opacity`, with one exception: the skeleton loader shimmer moves a background position while data loads. No other looping animation; a data tool should sit still.
- `prefers-reduced-motion` removes every transition.
- Lists appear instantly; there is no stagger because the user is scanning, not being shown a reveal.

## 7. Anti-Patterns (Banned)

- No emojis, anywhere.
- No Inter, no serif, no pure black, no neon or glow, no gradient text.
- No second accent colour, no purple, no saturation above 80%.
- No three equal cards in a row; use the stat strip or an asymmetric grid.
- No centered hero, no "scroll to explore", no bouncing chevrons.
- No provider prices, no cost lookups: the Cost center shows measured metrics only (tokens, energy, timing). Users multiply by their own rates.
- No invented data: missing numbers show as "Not measured", em dash or null; never zero or guesses.
- No fake round numbers or generic placeholder names; sample rows use real NSE symbols and plausible, uneven figures.
- No AI copywriting clichés (Elevate, Seamless, Unleash, Next-Gen).
- No custom cursors, no colour-only status, no spinners.
