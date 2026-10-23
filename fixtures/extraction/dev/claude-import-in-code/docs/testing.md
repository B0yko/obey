# Testing

Tests use the built-in Bun test runner. Unit tests sit in `tests/`, and fixtures are in
`tests/fixtures/`.

## Rules

- Run `bun test` after changing code in `server/` or `web/`.
- Test files are named `<name>.test.ts` and live in `tests/`.
- Do not skip tests with `test.skip` or `it.skip`.
- Prefer testing behaviour over implementation details.
