.PHONY: test lint typecheck gen

test:
	uv run pytest -q

lint:
	uv run ruff check .

typecheck:
	uv tool run mypy src

gen:
	uv run python scripts/gen_currency.py
