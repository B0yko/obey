# Quality gates

CI runs lint, tests and a dependency audit on every pull request. Lint configuration is in
`eslint.config.js`.

## Rules

- Run `npm run lint` before you finish; CI rejects lint failures anyway.
- `public/vendor/` contains vendored third-party scripts. Do not modify them.
- Keep functions pure where possible.

Delivery rules: @docs/policy/delivery.md
