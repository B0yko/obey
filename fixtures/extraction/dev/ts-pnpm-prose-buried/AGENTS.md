# Tallyforge web app

Tallyforge is a small invoicing dashboard written in TypeScript and React. It talks to
a REST backend that lives in another repository, so everything here is front-end code,
a few build scripts and the generated API client. The project uses pnpm workspaces even
though there is only one package today, because the design system will be split out later.

## Working in this repo

Dependencies are managed with pnpm and only pnpm. The lockfile is `pnpm-lock.yaml`, and
mixing in npm or yarn creates a second lockfile that someone then has to clean up, so
please don't run `npm install` or `yarn add` here, even for a quick experiment.

The API client in `src/generated/` is produced by `pnpm codegen` from the OpenAPI
document. Never edit anything inside that directory by hand, because the next codegen run
wipes it. If the client looks wrong, fix the OpenAPI document or the codegen config and
regenerate it.

On code style: TypeScript runs in strict mode and we want it to stay that way.
Do not introduce `any`; reach for `unknown` and narrow it, or write a proper type.
Likewise, `console.log` has no place in committed code. The app has a `logger` helper in
`src/lib/logger.ts` that respects log levels.

We review diffs quickly, so keep each change small and focused.
Follow the patterns you see in neighbouring files instead of inventing new ones.

Commit messages follow Conventional Commits (`feat:`, `fix:`, `chore:` and so on, with an
optional scope in parentheses). Pushing is handled by a human after review, so do not run
`git push`, not even to a feature branch.
