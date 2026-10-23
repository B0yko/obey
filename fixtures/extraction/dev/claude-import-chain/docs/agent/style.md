# Style rules

These rules apply to everything under `src/orchard/`. Formatting is handled by ruff, so
formatting nits are not worth discussing in review.

## Rules

- Do not use wildcard imports (`from x import *`).
- Do not silence ruff with `# noqa` comments. Fix the finding.
- Name modules in snake_case, for example `retry_policy.py`.
- Write comments that explain intent.

Testing rules continue in @testing.md.
