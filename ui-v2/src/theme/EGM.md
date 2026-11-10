# theme

## Overview
Light and dark theme provider for the client.

## Interface
- `ThemeProvider.tsx`: `ThemeProvider`, `useTheme`, `Theme`.

## Invariants
- The provider is the only place the active theme is set.

## Side Effects
- Sets `data-theme` on `document.documentElement`.
- Reads and writes the saved theme choice in `localStorage`.

## Verification
- Run: `npm test` in `ui-v2/`.
