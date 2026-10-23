# shiftwise

A small shift scheduler for small teams. It loads the team and the week's shifts from a JSON API,
checks conflicts and weekly hours, and renders a rota table. TypeScript, no framework, no runtime
dependencies.

## Layout

```
src/main.ts            browser entry point
src/shift-planner.ts   conflicts, weekly hours, validation of new shifts
src/date-utils.ts      UTC date helpers
src/render-table.ts    renders the weekly table as an HTML string
src/api/client.ts      client for the team API (unknown JSON checked by src/api/response-guards.ts)
src/logger.ts          the only module that touches the console
src/generated/         types generated from openapi.yaml by scripts/gen-types.mjs
```

Tests live next to the code as `src/**/*.test.ts`.

## Development

```
pnpm install
pnpm test         # vitest run
pnpm lint         # eslint .
pnpm typecheck    # tsc --noEmit
pnpm build        # tsc -p .  (output in dist/, loaded by index.html)
pnpm gen:types    # regenerate src/generated/api-types.ts from openapi.yaml
```

Serve the folder with any static server and point `data-api-base` in `index.html` at your API.

See `AGENTS.md` for the working agreement for contributors and coding agents.

This directory is part of the parent repository and is licensed under Apache-2.0 with it.
