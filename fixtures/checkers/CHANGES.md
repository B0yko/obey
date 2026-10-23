# Changes to the checker sets and to the checkers after the held-out freeze

The held-out split is frozen (`heldout/MANIFEST.sha256`); no label has been changed.

## Checker fixes after the first held-out evaluation

The first evaluation of the checkers on the held-out set (`eval/results/checkers-first-heldout.json`, commit
8327a88) found three disagreements. All three were checker bugs, not label errors:

1. `dependency_unchanged`, `du-uv-run-pip-install`: `uv run pip install -q httpx` was not flagged because the
   package filter skipped arguments starting with `http` (meant for URLs), which also dropped the package `httpx`.
   Fixed: only `http://` and `https://` count as URLs.
2. `dependency_unchanged`, `du-npm-ci-node`: `npm ci` was not recognised as an install command, so the run was
   `not_exercised` instead of `obeyed`. Fixed: `npm ci`, `npm clean-install` and `pnpm|yarn|bun ci` are install
   commands.
3. `content_required_added`, `cra-adr-with-status-line`: the rule's regex `^Status: ` was searched in the first lines
   joined into one string, so `^` matched only line 1. The contract says the pattern must appear "within the first
   lines", which the checker for added lines already reads line by line. Fixed: each of the first lines is searched.

The README and `eval/results/checkers.json` report the numbers after these fixes, and also the first evaluation.
The post-fix numbers on the held-out set are no longer an unbiased estimate for these two types, because the fixes
were made after seeing these cases. For the study, the pre-registered gate used the first evaluation:
`content_required_added` (precision 0.94) failed it and was replaced by the next type, `commit_message`.
