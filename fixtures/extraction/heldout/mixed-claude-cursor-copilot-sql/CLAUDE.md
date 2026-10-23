# Tidal Warehouse

Transformation layer for the analytics warehouse: SQL models that a scheduler runs every
night. SQL style rules are in @docs/sql-style.md.

## Rules

- Never run `dbt run --full-refresh`; it drops the history tables.
- Do not commit.
- Mention which models you touched in your final message.
