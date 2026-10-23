# Harborline shop

A Django 5 storefront with a small admin. Apps: `shop`, `accounts`, `payments`.

## Environment

- Dependencies are managed with Poetry.
  - Add packages with `poetry add`; do not call `pip install` or `pip3 install`.
- The database is PostgreSQL in CI and SQLite locally.

## Database and migrations

- Merged migrations should not be edited.
  - This applies to every app (`shop`, `accounts`, `payments`).
- Changes to any `models.py` must come with a new file in that app's `migrations/` folder.
- Raw SQL is discouraged: do not use `.raw()` or `.extra()` on querysets.

## Quality

- After changing Python files, run `poetry run python manage.py test`.
- Your final message must contain a line starting with `Tests:` that names the apps you tested.
- Keep views thin and move business logic into `services.py`.
- Docstrings should explain why, not what.
- Admin customisations should stay minimal.
