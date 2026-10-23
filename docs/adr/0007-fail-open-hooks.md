# 7. Generated hooks fail open, visibly

Date: 2026-10-23 · Status: accepted

## Context

A hook that crashes on malformed input, a missing `rules.json` or an unexpected payload shape could block every
tool call and leave the user with an unusable agent.

## Decision

Hooks deny only when the rule engine positively finds a violation. Any internal error (unreadable rules, a
payload the hook cannot parse, an exception in the engine) allows the action and prints a warning that names the
error, through the agent's warning channel where it has one (for example `systemMessage` in Claude Code) and
stderr otherwise.

## Consequences

- A bug in obey cannot lock a user out of their agent.
- A broken hook silently enforcing nothing would be worse than a loud one, so the warning is always visible and
  `obey lint` checks that the enforcement files are in sync with `obey.yaml`.
- Fail-open behaviour is part of the hook contract tests.
