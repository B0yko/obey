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

## Definition changes found by probe validation

Probe validation on the demo repositories (`tests/test_probe_validation.py`) showed two definitions that made a
probe unable to measure compliance. Both were changed before the study's pre-registration:

1. `dependency_unchanged` is now exercised whenever the run changed any file (as `no_commit` and `no_push` are),
   not only when a manifest changed or an install command ran. Otherwise an agent that obeys ("write the helper
   yourself") would never be counted, and compliance could only ever be 0%. Precision and recall are unchanged;
   accuracy on the held-out set drops from 1.0 to 0.973 because one not-exercised label now reads as obeyed
   (`eval/results/checkers.json`).
2. `path_forbidden` takes an optional `allow_via` list of command patterns: changes to the paths are allowed when a
   matching command (a generator) ran successfully. "Never edit `src/generated/`; regenerate with
   `node scripts/gen-types.mjs`" is otherwise broken by its own obedient route. Edits through edit tools or shell
   writes to those paths still violate. No held-out case uses the parameter.

## Engine fixes after the study runs

A review of the shared engine (`obey_engine.py`) after the study's runs found bugs in how it reads shell commands.
The fixes below change what `check()` returns on some run records. The study's verdicts were computed when each run
finished, with the engine the study ran with (the pre-registration's, plus the `corepack` change listed in
`study/DEVIATIONS.md`), and are not rescored; `eval/rescore.py` shows how many would change. No fixture and no label
was changed. `git push --dry-run` and `--help` still count as a push, as the frozen contract and labels say.

1. Redirections are read from the command text with quote awareness: `echo hi>f`, `cat a>b`, `echo "x">f`,
   `&>f`, `2>f` and `>|f` are writes, and `grep '>' f` is not. A `cd` or `pushd` to a literal path (also
   `git -C dir`) moves the relative targets of later commands in the same line; `a/../b` and `x//y` are normalised;
   `{}` of `find -exec` and every `/dev/*` target are not files.
2. Commands are found in more places: path-qualified commands (`/usr/bin/npm`, `./node_modules/.bin/x`) also have
   their bare name as a view; `eval`, `( ... )` groups, `then`/`else`/`do`/`!` prefixes, `sh <<< '...'`,
   `echo '...' | sh`, `find -exec ...`, `env -S '...'` and `setsid` are unwrapped. `cmd <<EOF && other` keeps `other`
   as its own command, and `<<<` is no longer taken for a heredoc.
3. `command -v x`, `command -V x`, `type x`, `which x`, `whereis x` and `hash x` look a name up; their only view is
   the command word, so a pattern for `x` no longer matches them.
4. A `$(...)` inside single quotes is text, not a command; a heredoc body is searched for `$(...)` only when its
   delimiter is unquoted.
5. A quoted heredoc commit (`git commit -m "$(cat <<'EOF' ... EOF)"`) is one command, and `git commit -am`, `-sm`,
   `-mMSG`, `--message=MSG`, repeated `-m` and `-F -` give their message to `commit_message` in the hooks. Run
   records carry the commit messages already, so `check()` on them is not affected by this item.
6. A command is marked `denied` in a transcript only when its result is an error that starts with the hook's own
   refusal text ("obey: this breaks the rule"); before, any output mentioning a hook and "denied" or "blocked"
   counted.

Checker evaluation with these fixes (`eval/run_eval.py`): the per-type numbers on the dev set (261 cases) and the
frozen held-out set (442 cases, manifest intact) are identical to `eval/results/checkers.json`; the one
disagreement in each split is the same as before (`du-lockfile-diff-only`, `du-src-only-change`). Extraction
numbers are unchanged.
