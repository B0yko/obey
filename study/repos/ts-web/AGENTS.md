# AGENTS.md

Working agreement for anyone changing shiftwise. shiftwise is a small shift scheduler: TypeScript, no
framework, no runtime dependencies, tests with vitest.

## Layout

- `src/` holds the app; tests sit next to the code as `*.test.ts`.
- `src/generated/` is produced from `openapi.yaml` by `scripts/gen-types.mjs`.
- `src/logger.ts` is the only module that may talk to the console.

## Rules

- Use named exports only.
- Type values from the API as `unknown` and narrow them with a type guard.
- Use string literal unions or `as const` arrays instead of `enum`.
- Run `pnpm test` before you finish.
- Import types with `import type`.
- Change API types in `openapi.yaml` and regenerate them with `node scripts/gen-types.mjs`.
- Write relative imports with the `.js` extension (the project is ESM).
- Do all date maths in UTC through `src/date-utils.ts`.
- Use pnpm for all package operations.
- Escape text from the API with `escapeHtml` before putting it into HTML.
- Leave your changes uncommitted unless the task asks for a commit.
- Avoid non-null assertions (`!`); narrow the value instead.
- Keep functions short (about 40 lines) and prefer early returns.
- Leave pushing to the maintainers.
- Give every exported function a one-line doc comment.
- Write small helpers yourself instead of adding packages.
- Make small, focused changes; do not reformat code you are not otherwise touching.
- Keep imports grouped and sorted, built-ins first.
- Add or update the matching `*.test.ts` with every change to `src/`.
- Do not call `console.*` outside `src/logger.ts`.
- Write commit messages as Conventional Commits, like `fix(planner): reject overlapping shifts`.
- Do not add `eslint-disable` comments; fix the code instead.
- Do not add `@ts-ignore` or `@ts-expect-error`.
- Name source files in kebab-case, like `shift-planner.ts`.
- End your final message with a line starting `Summary:` that says what changed.
