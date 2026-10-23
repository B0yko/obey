# Basalt Handbook

An MkDocs site (`docs/`) plus a few Python helper scripts (`tools/`). Python is managed
with uv.

## Rules

- Use uv for Python. Do not run `pip`.
- Run `uv run mkdocs build --strict` before finishing any change under `docs/`.
- Do not commit.
- Write for readers who are new to the project.

## Where things are

- `docs/` pages
- `tools/` scripts that generate or check pages
- `mkdocs.yml` navigation
