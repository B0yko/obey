# Testing rules

The suite is split into `tests/unit/` and `tests/integration/`. Integration tests need Docker
and are normally run by CI.

## Rules

- Run `poetry run pytest` before you finish any change to `src/`.
- When you change `src/orchard/`, add or update a test under `tests/`.
- Name test files `test_<module>.py`.
- Tests must not call real network endpoints.

Release rules are in @docs/agent/release.md.
