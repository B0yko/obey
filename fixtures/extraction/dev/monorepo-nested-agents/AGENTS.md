# Cobalt Harbor

A pnpm monorepo with two packages:

- `packages/web`: React front end
- `packages/api`: Fastify API

Each package has its own `AGENTS.md` with extra rules.

## Rules for the whole repo

- Use pnpm. Never run `npm` or `yarn` commands.
- Commit messages use Conventional Commits with the package as scope, e.g. `fix(api): ...`.
- Do not push; a maintainer pushes after review.
- Prefer small, reviewable changes.
- Do not refactor across packages unless asked.
