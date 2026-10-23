---
applyTo: "**/migrations/*.py"
---

Migrations are applied automatically on deploy by `python manage.py migrate`. Applied
revisions are part of the production history.

Squashed migrations are produced by the maintainers.

- Do not modify migration files that already exist; create a new migration instead.
- Provide a reverse function for every `RunPython` operation.
