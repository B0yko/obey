# server (Node API)

An Express-style API with a Postgres database. Handlers are in `src/handlers/`, SQL in
`src/sql/`, and configuration is read from environment variables in `src/config.ts`.

## Rules

* Add dependencies to `server/package.json` only after approval.
* Do not log request bodies.
* Handlers go in `src/handlers/`, one per file.

## Commands

```bash
npm run dev --workspace server
npm test --workspace server
```
