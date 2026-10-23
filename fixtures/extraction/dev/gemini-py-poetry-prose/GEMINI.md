# Pinecast

Pinecast turns a folder of audio files and a YAML description into a podcast RSS feed. It is
a Python 3.11 package with a small command-line front end. Most of the logic lives in
`src/pinecast/`, and the tests are in `tests/`.

## How we work

Packages are installed and locked with Poetry, so do not use `pip install` in this repository,
not even inside the virtual environment that Poetry creates; it leaves `poetry.lock` out of
date. You may add test and lint tooling (`pytest`, `pytest-cov` and `ruff`) when you need it,
but any other new dependency needs approval first, because the feed generator is installed on
small servers and every extra package matters.

Library code must not call `print()`; use the standard `logging` module so that the CLI can
control verbosity. Every new module under `src/pinecast/` should start with
`from __future__ import annotations` within its first five lines, which keeps annotations
lazy and avoids import cycles.

When you are done, do not use emojis in your final message. The maintainers read these in a
plain terminal. Commit subjects must start with a capital letter and must not end with a
period.

Try to leave the code a little tidier than you found it, and avoid clever one-liners.
