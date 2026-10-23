# Tidewater pipeline

Nightly batch pipeline that ingests tide-gauge CSV exports, cleans them with pandas and
writes Parquet files for the reporting team. Python 3.11. Dependencies are listed in
`requirements.in` and pinned into `requirements.txt` with pip-tools.

## Rules

1. Never use conda or mamba: the production image is built from `requirements.txt` only.
2. Do not write to `data/raw/`: raw exports are immutable and are our only audit trail.
3. Avoid `inplace=True` in pandas calls under `src/`, because it hides copies and makes the
   transforms hard to test.
4. When you change a transform in `src/tidewater/transforms/`, update or add a test in
   `tests/transforms/`, since reporting depends on exact output.
5. New dependencies need approval: every package ends up in the nightly image and we
   pay for the build time.
6. In your final message, list the commands you ran under a line `Commands run:`, because
   reviewers cannot see your terminal.
7. Do not run `git commit` unless the task says so; releases are tagged by hand.
8. Keep transforms pure functions where you can; side effects belong in `src/tidewater/io/`.
9. Prefer vectorised operations over row loops.

## Layout

- `data/raw/` incoming CSV exports
- `data/staging/` cleaned Parquet
- `src/tidewater/` pipeline code
- `tests/` pytest suites
