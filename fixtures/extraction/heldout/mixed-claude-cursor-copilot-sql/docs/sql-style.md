# SQL style

These rules apply to every model under `models/` and are imported by `CLAUDE.md`.

## Rules

- Never use `SELECT *` in models.
- Prefer CTEs over nested subqueries.

## Formatting

Formatting is handled by `sqlfluff`, so line breaks and keyword case are not review topics.
