# packages/api

Fastify with Postgres. Routes are in `src/routes/`, tests in `test/`.

- Use the `logger` from `src/logger.ts`; do not use `console.log`.
- A change in `src/routes/` must come with a change in `test/`.
- Don't add runtime dependencies to this package without approval.
- Validate request bodies with the existing schemas rather than ad-hoc checks.

## Commands

```bash
pnpm --filter api dev
pnpm --filter api test
```
