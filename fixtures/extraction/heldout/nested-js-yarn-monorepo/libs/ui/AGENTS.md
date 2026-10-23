# libs/ui

Shared components, published internally. Stories are in `stories/`.

- Do name component files in PascalCase (`Button.tsx`, `DataTable.tsx`).
- Don't import from `apps/`; this library must not depend on applications.
- Don't add runtime dependencies; `react` is a peer dependency only.
- Do keep components stateless where possible.

## Commands

```bash
yarn workspace ui build
yarn workspace ui storybook
```
