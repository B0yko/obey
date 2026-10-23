# Wrenfield Queue

Wrenfield Queue is a job-queue service written in TypeScript and run with Bun. It exposes a
small HTTP API (`src/api/`) and a worker (`src/worker/`). Tests live in `tests/`.

## Conventions

This repository is installed and run with Bun. npm, yarn and pnpm should not be used for
anything here; they would only add lockfiles nobody maintains.

`console.log` calls are not expected in committed code. Structured logging goes through
`src/log.ts`.

Anything in `src/gen/` is produced by `bun run gen` and should not be modified by hand.

Test files are expected to be named `<name>.test.ts`, and they belong in `tests/`.

Changes are normally committed by the maintainer, so it is best to leave them uncommitted.

Once the work is complete, running `bun run check` would be appreciated.

It would also be good to keep modules cohesive.

Error messages ought to be actionable.

## Example session

```bash
bun install
bun run gen
bun run check
```
