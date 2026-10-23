# backend/

Django project in `config/`, apps in `orders/` and `customers/`.

## Database

- Migrations
  - Never rewrite a migration that is already on `main`; add a follow-up migration instead.
  - Any edit to a `models.py` ships together with its migration in the same change.
- Debugging
  - Don't leave `breakpoint()` or `pdb.set_trace()` calls in code.

## Testing

- Run `uv run python manage.py test` from `backend/` after changing Python files.
