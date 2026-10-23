# Lumen Suite

A Yarn workspaces monorepo: `apps/dashboard` (a React app) and `libs/ui` (a component
library). Both have their own `AGENTS.md`.

## Do

- Use yarn for every command, for example `yarn install` or `yarn workspace dashboard build`.
- Keep changes scoped to one workspace where possible.
- Write commit bodies that explain why the change was made.

## Don't

- Don't push. A maintainer pushes after review.
- Don't rename workspaces.
