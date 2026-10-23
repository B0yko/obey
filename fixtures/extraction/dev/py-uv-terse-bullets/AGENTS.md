# Fernwatch

Fernwatch watches plant-sensor feeds and posts alerts. Python 3.12, uv, pytest.

## Layout

- `src/fernwatch/` library code
- `tests/` pytest suites
- `scripts/` one-off helpers

## Rules

- Use uv for installs and runs; never pip, poetry or pipenv.
- No `print()` in `src/`; use `logging`.
- No `# type: ignore`. Fix the type instead.
- Run `uv run pytest` before finishing.
- Ask before adding a dependency.
- Do not commit. Leave changes in the working tree.
- Keep functions short and single-purpose.
- Match the style of nearby code.
- Prefer plain functions over class hierarchies.
- Keep replies brief.

## Commands

```bash
uv sync
uv run pytest
uv run ruff check .
```
