---
applyTo: "src/**/*.ts,src/**/*.tsx"
---

The front end is a Vite app with React 18. Shared types live in `src/types/`.

When writing front-end code:

- Avoid the `any` type. Use `unknown` and narrow it.
- Prefer named exports over default exports.
- Components receive typed props.
