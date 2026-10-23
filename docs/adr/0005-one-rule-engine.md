# 5. One rule engine shared by checkers and hooks

Date: 2026-10-23 · Status: accepted

## Context

If the hook that blocks `npm install` used a different matcher from the checker that measures it, a rule could be
"enforced" and still measured as broken, or the reverse.

## Decision

Command segmentation and unwrapping, shell write-target detection, glob matching and diff inspection live in a
single standard-library module, `obey_cli/enforce/engine/obey_engine.py`, that runs on Python 3.9 and later. The
checkers import it, and `obey enforce` vendors the same file into `.obey/hooks/` next to the generated hook
script, so the hooks need neither obey nor any third-party package at run time.

## Consequences

- What a hook enforces is exactly what the checker measures; evasion fixtures exercise both.
- The engine cannot use third-party libraries or newer syntax; CI runs its tests under Python 3.9.
