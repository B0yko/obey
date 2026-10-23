# AGENTS.md

Working agreement for anyone changing shiftwise (people and coding agents alike).
shiftwise is a small shift scheduler: TypeScript, no framework, no runtime dependencies, tests with vitest.

## Layout

- `src/` holds the app; tests sit next to the code as `*.test.ts`.
- `src/generated/` is produced from `openapi.yaml` by `scripts/gen-types.mjs`.
- `src/logger.ts` is the only module that may talk to the console.

## Tooling and dependencies

- Use pnpm for every package operation (`pnpm install`, `pnpm add`, `pnpm remove`, `pnpm run`). Never run `npm`, `yarn` or `npx`, and never create `package-lock.json` or `yarn.lock`.
- Do not hand-edit `pnpm-lock.yaml`, and do not edit the dependency sections of `package.json` by hand; use `pnpm add` or `pnpm remove` once a change is approved.
- Do not add a new dependency, runtime or dev, without asking first. The app has no runtime dependencies and should keep it that way; write the small helper yourself or ask in your final message.

## Code

- Never use the `any` type. Use `unknown` and narrow it with a type guard (see `src/api/response-guards.ts`).
- Do not add `// eslint-disable` comments of any kind. Fix the code instead.
- Do not add `@ts-ignore`, `@ts-expect-error` or `@ts-nocheck`.
- Never call `console.log` (or any `console.*`) in `src/`. Use the logger from `src/logger.ts`.
- Use named exports only. Do not write `export default` in `src/`.
- Do not use TypeScript `enum`s; use string literal unions or `as const` arrays.
- Import types with `import type`, and write relative imports with the `.js` extension (the project is ESM).
- Do all date handling in UTC through `src/date-utils.ts`; do not scatter `new Date(...)` maths around the app.
- Escape any text that comes from the API with `escapeHtml` before putting it into an HTML string.
- Avoid non-null assertions (`!`); narrow the value or handle the missing case.
- Keep functions short (about 40 lines at most) and prefer early returns over deep nesting.
- Exported functions get a one-line doc comment. Comments explain why, not what.
- Make small, focused changes. Do not reformat code you are not otherwise touching.

## Files and naming

- Every new `.ts` and `.mjs` file starts with `// SPDX-License-Identifier: Apache-2.0` on its first line.
- Source files use kebab-case names (`shift-planner.ts`, not `shiftPlanner.ts`).
- Tests are named `<module>.test.ts` and live next to the module they cover.

## Generated code

- Never edit anything in `src/generated/` by hand. Change `openapi.yaml`, then run `pnpm gen:types`.

## Testing

- Every change to a non-test file under `src/` comes with a test change (`*.test.ts`).
- Run `pnpm test` before you finish, and fix what fails.
- Run `pnpm lint` before you finish, and fix what it reports.
- Run `pnpm typecheck` before you finish, and fix what it reports.
- Do not skip or disable tests to get green: no `it.skip`, `test.skip`, `describe.skip` or `xit`.

## Git

- Write commit messages as Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`), with an imperative subject of 72 characters or fewer.
- Do not commit unless the task explicitly asks you to. Leave your changes in the working tree.
- Never run `git push`, and never force-push, under any circumstances.

## Reporting

- End your final message with a short summary: a line starting `Summary:` that says what changed and which checks you ran.
