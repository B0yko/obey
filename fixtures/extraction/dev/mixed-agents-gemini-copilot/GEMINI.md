# Gemini notes

The project rules are in `AGENTS.md`. The points below are extra for this tool.

- Do not use `print()` in `billing/`.
- Commit messages look like `type(scope): summary` with a lower-case type.
- Keep answers short.

## Background

The invoice PDFs are rendered with WeasyPrint from HTML templates, and the Django project
settings are in `fennel/settings.py`.
