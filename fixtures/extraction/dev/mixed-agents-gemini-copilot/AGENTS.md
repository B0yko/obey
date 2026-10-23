# Fennel Billing

Invoice generation service. Python 3.12, Poetry, Django REST framework.

## Commands

```bash
poetry install
poetry run pytest
```

## Rules

- Use Poetry; do not run `pip install`.
- `templates/pdf/compiled/` is build output. Do not edit it.
- Run `poetry run pytest` before finishing.
- Put new invoice code in `billing/` and keep views thin.
