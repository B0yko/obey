# apps/dashboard

The customer-facing dashboard. React with Vite; routes are in `src/pages/` and data hooks in
`src/hooks/`.

- Do add a test in `src/__tests__/` whenever you change a hook in `src/hooks/`.
- Don't use `localStorage` directly; go through `src/storage.ts`.
- Don't call the REST API from components; use the data hooks.

## Commands

```bash
yarn workspace dashboard dev
yarn workspace dashboard test
```
