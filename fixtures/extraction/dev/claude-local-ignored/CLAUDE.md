# Brookline Forms

Brookline Forms is a form-builder backend (Flask, SQLAlchemy). Python 3.12 managed by uv.

Conventions are shared with the other repositories, so they live in @docs/conventions.md.

## Rules

- Use `uv` for dependency management. Do not use `pip`.
- Only `pytest`, `ruff` and `mypy` may be added as dependencies without approval.
- Do not use `print()` in `app/`; log with `app.logger`.
- A change in `app/` needs a matching change in `tests/`.
- Commit messages are Conventional Commits (type, optional scope, colon, summary).
- Be careful with schema changes.
- Explain the trade-offs when you choose between two designs.
