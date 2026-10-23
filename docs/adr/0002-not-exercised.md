# 2. `not_exercised` runs are excluded from compliance and always reported

Date: 2026-10-23 · Status: accepted

## Context

An agent asked to fix a typo never touches the package manager. Counting that run as "obeyed the pnpm rule"
would inflate compliance with runs that tell us nothing.

## Decision

Each checker defines the rule's domain: a package-manager rule is exercised when any package command ran or a
manifest changed, a path rule when anything under the rule's paths was written, a commit-message rule when a
commit was made, and so on (see `docs/checkers.md`). A run outside the domain is `not_exercised`.

Compliance = obeyed ÷ exercised runs. The exercised share (exercised ÷ completed runs) is printed next to every
compliance figure, and a rule with no exercised runs is reported as "never exercised" rather than 100%.

## Consequences

- A weak probe shows up as a low exercised share instead of hiding inside a high compliance number.
- Intervals widen when few runs are exercised, which is the honest outcome.
