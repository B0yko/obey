---
applyTo: "apps/edge/**/*.ts"
---

Edge workers run in a restricted runtime without Node.js built-ins. The injected clock lives
in `apps/edge/src/clock.ts`.

Requirement keywords have the same meaning as in the root `AGENTS.md`.

- Test files MUST be named `<name>.test.ts`.
- Handlers SHOULD NOT call `Date.now()`; use the injected clock.
