# Kestrel Notes

Kestrel Notes is a notes app: a Bun HTTP server in `server/` and a web client in `web/`.

Shared testing rules are imported from @docs/testing.md.

## How imports work

CLAUDE.md files can pull in other files with an `@` reference. The next block is
documentation only; it is not a real import:

```md
@docs/examples/team-rules.md
```

## Rules

- Use bun for everything. Never use npm, npx, yarn or pnpm.
- Do not add `eslint-disable` comments. Fix the code instead.
- Do not commit unless the task asks for it.
- Prefer early returns over deeply nested conditionals.
- Keep route handlers small; move logic into `server/services/`.

## Commands

```bash
bun install
bun run dev
bun test
```
