# tools/

Scripts here are allowed to print to stdout; they are not library code. They are invoked
as `uv run python tools/<name>.py`.

- New scripts start with `# SPDX-License-Identifier: MIT`.
- Script names use snake_case, for example `check_links.py`.
- Do not add dependencies for a single script; use the standard library.
- Every script that writes files needs a `--dry-run` flag.

Current scripts: `check_links.py`, `gen_nav.py` and `gen_reference.py`.
