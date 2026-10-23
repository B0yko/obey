# Dependencies

Moorhen has a deliberately small dependency tree: Express, better-sqlite3 and a handful of
parsers. The audit report is generated weekly by CI.

## Rules

- Adding a dependency requires approval: every package increases the audit surface.
- Prefer the platform's built-in APIs over small utility packages.

Quality gates: @docs/policy/quality.md
