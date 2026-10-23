# 3. Probes are temptations, not samples of natural usage

Date: 2026-10-23 · Status: accepted

## Context

Waiting for natural sessions to touch a given rule is slow, and most sessions never do. We want to know whether a
rule holds when breaking it is the easy path.

## Decision

For each rule, a probe template creates a small task in a copy of the user's repository where the shortest route
breaks the rule: add a package (pnpm rule), rename a column (migration rule), type an untyped payload (`any`
rule), finish a change and report back (tests-before-done rule). Templates are filled from facts detected in the
repository and need no LLM; `--llm` may only adapt their wording. Control probes are neutral tasks.

Each template ships with a scripted obedient patch and a scripted disobedient patch that must score `obeyed` and
`violated` on the demo repositories; CI runs this validation.

## Consequences

- Reported numbers are "probe compliance": compliance on tempting tasks. Reports and the study say so next to the
  number, because natural-usage compliance may be higher.
- The exercised share per checker type measures how well probes do their job.
