# Contributing

Thanks for helping. obey measures coding agents, so changes to anything that decides a verdict need evidence.

## Set up

```bash
git clone https://github.com/B0yko/obey && cd obey
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Tests make no network calls (a fixture blocks sockets); tests that need Docker or a paid model are marked and skipped by
default.

## Rules for changes

- **Checkers and the rule engine** (`src/obey_cli/enforce/engine/obey_engine.py`) are shared by measurement and
  enforcement. Keep them standard-library only and Python 3.9 compatible, add a dev case under
  `fixtures/checkers/dev/`, and run `uv run python eval/run_eval.py`. Never edit `fixtures/*/heldout/`; if a held-out
  label is wrong, explain it in the set's `CHANGES.md`.
- **Extraction patterns** (`src/obey_cli/extract.py`): add or extend a dev case under `fixtures/extraction/dev/` with a
  `labels.yaml` and check precision does not drop.
- **Probe templates** (`src/obey_cli/probes/templates.py`): add a scripted obedient and disobedient session to
  `tests/test_probe_validation.py`.
- **Agent adapters**: record a stream with `eval/contract_check.py` or `eval/record_runs.py` and add it under
  `fixtures/streams/`; never commit API keys or local paths.
- **Hook targets**: keep merges JSON-preserving and idempotent; `tests/test_enforce_merge.py` must pass.

## Commits and pull requests

Conventional Commits (`feat:`, `fix:`, `docs:` …). One change per pull request, with tests. CI must be green.
