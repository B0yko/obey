# web (Vue client)

Vue 3 with the Composition API. Source is in `src/`, unit tests in `tests/`, and the router
is configured in `src/router.ts`.

## Rules

* Don't leave `console.log` calls in `src/`; use the `debug` helper.
* New modules in `src/lib/` need a unit test in `tests/`.
* Do not use `v-html` in templates.
* Prefer small single-file components.

## Commands

```bash
npm run dev --workspace web
```
