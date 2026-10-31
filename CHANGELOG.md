# Changelog

All notable changes to this project are recorded here. Newest first.

## [Unreleased]

### Added
- `pyproject.toml` with project metadata and the pytest build gate (`testpaths = ["tests"]`). Run with `.venv\Scripts\python.exe -m pytest`.
- `CHANGELOG.md`.
- Shared glossary design, published as an RFC at `docs/designs/shared-glossary.md`. Implementation has not started.

### Changed
- `handoff.md`: ruflo cleanup closed. Decisions recorded under "Questions closed this session", item 8.

### Removed
- `.claude/proven-config.json` (named ruflo). The `statusLine` entry and `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS` were removed from `.claude/settings.json`. This folder is git-ignored, so these changes are local only.
