# filters

## Overview
Filter state for the results table and the saved-preset menu. `filterState.ts`
holds the filter fields of a results query. Paging and sort are kept by the
table, not here.

## Interface
- `filterState.ts`: `FilterState`, `hasActiveFilters`, `readFilterValues`,
  `writeFilterValues`.
- `PresetsMenu.tsx`: `PresetsMenu`, `checkPresetName`, `PresetNameResult`,
  `PRESET_NAME_MAX`, `PRESET_LIMIT`.
- `PresetsMenu.test.tsx`: test suite (not part of the interface).

## Invariants
- `PRESET_LIMIT` caps the number of saved presets.
- `checkPresetName` validates the name length against `PRESET_NAME_MAX`.
- `readFilterValues` and `writeFilterValues` round-trip one object without
  losing fields.

## Side Effects
- Preset list reads and writes through `api/presets.ts`.

## Verification
- Run: `npm test` in `ui-v2/` (covers `PresetsMenu.test.tsx`).
