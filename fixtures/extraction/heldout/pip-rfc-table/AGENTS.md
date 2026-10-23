# Hawthorn ETL

Hawthorn ETL loads partner CSV drops into the reporting database. Python 3.11; source code
is in `etl/`, third-party code in `vendor/` and tests in `tests/`.

Requirement levels follow RFC 2119 (MUST, MUST NOT, SHOULD).

## Requirements

| ID | Level | Requirement |
|----|-------|-------------|
| R1 | MUST | Install packages only with `pip install -r requirements.txt`; ad-hoc `pip install <package>` is forbidden. |
| R2 | MUST NOT | Add or upgrade dependencies without maintainer approval. |
| R3 | MUST NOT | Modify anything under `vendor/`. |
| R4 | MUST NOT | Call `print()` in `etl/`. |
| R5 | MUST | Start every new file in `etl/` with the line `# Copyright (c) 2025 the Hawthorn authors`. |
| R6 | MUST | Begin commit messages with `feat:`, `fix:`, `docs:`, `chore:` or `refactor:`. |
| R7 | MUST | Put a line `Tests: passed`, `Tests: failed` or `Tests: not run` in the final message. |
| R8 | SHOULD | Keep loaders idempotent, so a re-run of the same drop is harmless. |
| R9 | SHOULD | Prefer small, composable transforms. |
