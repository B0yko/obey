# 1. Deterministic checkers; LLM extraction only as reviewed proposals

Date: 2026-10-23 · Status: accepted

## Context

A compliance number is only as good as the judge behind it. An LLM judge drifts between model versions, costs
money per verdict, and can be argued with by the transcript it reads. Most rules people write in AGENTS.md
("use pnpm", "never edit migrations/", "no `any`") are about observable actions: commands, paths, added lines,
commits.

## Decision

Every verdict comes from a deterministic checker that reads the normalised run (commands, file events, diff,
commits, final message). A checker returns `obeyed`, `violated` or `not_exercised`, and a violation always carries
evidence (the command line, the diff hunk, the commit message).

Rule extraction maps instruction text to checkers with a pattern library. An optional `--llm` pass handles
candidates the patterns do not map; its output is validated against a JSON schema and written with
`status: proposed`. Nothing an LLM proposes is measured or enforced until a person changes the status to `active`.

Rules that need taste ("write clean code") are `uncheckable`, with a reason, and are never scored.

## Consequences

- Results are reproducible from the recorded runs with no model calls.
- Checker precision and recall are measured on a frozen held-out set, and a checker type below the release gate is
  excluded from the study.
- Coverage is limited to what can be observed. The report says how many rules are uncheckable.
