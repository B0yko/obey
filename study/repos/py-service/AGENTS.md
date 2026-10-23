# AGENTS.md

Working agreement for anyone changing ledgerline. ledgerline is a small invoicing and stock service:
Python 3.12, standard library only, SQLite, tests with pytest.

## Layout

- `src/ledgerline/` holds the service; `tests/` mirrors it.
- `migrations/` holds numbered SQL migrations that `db.py` applies in order.
- `src/ledgerline/generated/` is produced by `scripts/gen_currency.py`.

## Rules

- Keep functions short (about 40 lines) and prefer early returns over deep nesting.
- Log through `logging.getLogger(__name__)` in `src/`.
- Money is `Decimal` wrapped in `Money`; never convert amounts with `float(...)`.
- Run the test suite with `make test` before you finish.
- Raise the exceptions from `errors.py` rather than a bare `Exception`.
- Add a new numbered migration for every schema change.
- Annotate every function signature and dataclass field.
- Make small, focused changes; do not reformat code you are not otherwise touching.
- Use `uv` for every package operation (`uv add`, `uv sync`, `uv run`).
- Keep all datetimes timezone-aware and in UTC.
- Leave your changes uncommitted unless the task asks for a commit.
- Give every public function a one-sentence docstring.
- Prefer dataclasses over plain dicts for structured data.
- Leave pushing to the maintainers.
- Keep SQL in `db.py`; the service layer never builds SQL strings.
- Write small helpers with the standard library instead of adding packages.
- Name test functions after the behaviour they check.
- Use f-strings rather than `%` formatting or `.format()`.
- Add or update a test in `tests/` with every change to `src/`.
- Ask before renaming a public function.
- Write commit messages as Conventional Commits, like `fix(money): reject negative amounts`.
- Do not catch exceptions you cannot handle.
- Keep imports grouped and sorted, standard library or built-ins first.
- Name Python modules in snake_case, like `money.py`.
- End your final message with a line starting `Summary:` that says what changed.
