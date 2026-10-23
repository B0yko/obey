# Saltmarsh pipeline

Saltmarsh is a set of batch jobs that load order data from partner APIs, normalise it and
publish daily aggregates. The code is split into `services/ingest/` (pulling data) and
`shared/` (schemas and helpers). Each directory has its own `AGENTS.md`.

## Ground rules

Everything is built with Poetry. Please do not run `pip install` or `pip freeze` in this
repository, because the lock file is the single source of truth for the Docker image and a
stray pip install silently diverges from it.

The golden files in `tests/golden/` are the expected outputs of the regression suite.
Do not modify them to make a test pass.

Before you wrap up a change to anything under `services/` or `shared/`, run the unit tests
with `poetry run pytest tests/unit`. The integration tests need credentials and are run by
CI only.

New third-party libraries need a conversation first: every dependency has to be vetted by
the platform team before it can go into the production image.

Your closing message should always include a line beginning with `Risk:` that says what
could go wrong in production, even if the answer is "nothing known".

Try to keep each job idempotent.
