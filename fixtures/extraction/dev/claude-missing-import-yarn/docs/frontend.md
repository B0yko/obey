# Front-end rules

The widget is rendered into a host page, so it has to behave well next to unknown markup.
Styles are scoped with CSS modules, and the build output is a single script in `web/dist/`.

## Rules

- Do not use `document.write` or assign to `innerHTML`.
- Prefer React Query over hand-rolled fetch effects.
- Every interactive element needs an accessible label.
