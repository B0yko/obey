# Thistledown

Thistledown is a booking widget: React front end in `web/`, Express API in `api/`.
Yarn 1 workspaces.

Front-end rules: @docs/frontend.md
Back-end rules: @docs/backend-rules.md

## General rules

- Use yarn. Do not run npm or pnpm.
- Never use `@ts-ignore` or `@ts-nocheck`; write a precise type instead.
- Run `yarn lint` before you finish.
- Never run `git push`.
- Your final message must start with `Changed:` followed by the files you touched.
- Ask before changing the public widget API.
