# packages/web

React 18 and Vite. Components live in `src/components/`.

- Name component files in PascalCase, for example `src/components/InvoiceTable.tsx`.
- Do not use `dangerouslySetInnerHTML`. Render text instead.
- Keep components small and presentational where possible.
- Co-locate styles with the component.

## Commands

```bash
pnpm --filter web dev
pnpm --filter web test
```
