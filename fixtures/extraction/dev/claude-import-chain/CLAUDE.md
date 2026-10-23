# Orchard Relay

Orchard Relay forwards webhooks between internal services. Python 3.12, Poetry, FastAPI.

Code style rules are in @docs/agent/style.md, which pulls in the remaining rule files.

## Core rules

- Use Poetry for dependencies. Do not run `pip install`.
- Do not commit unless the task asks for it.
- Think about failure modes before writing retry logic.
- Keep the diff focused on the task.
