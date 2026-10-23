# Checkers

A checker reads one run (the agent's normalised events, the end-state diff, new commits, pushed refs and the final
message) and returns `obeyed`, `violated` or `not_exercised` for one rule. A violation always carries evidence: the
command line, the diff line, the commit message or the event. Checkers never read what the agent said about
itself, except the final-message checker, whose subject is the final message.

All checkers live in one standard-library module, `src/obey_cli/enforce/engine/obey_engine.py`, which
`obey enforce` also copies into generated hooks.

## General rules

- A command a hook blocked before it ran does not count as executed. A command that ran counts whatever its exit
  code (an attempted `npm install` that failed still broke "never use npm"), except where a checker requires success.
- Shell lines are split on `&&`, `||`, `;`, `|`, `&` and newlines, and unwrapped: `bash -c '…'`, `sh -lc "…"`,
  heredocs fed to a shell, `$(…)` and backticks, `env A=1 …`, leading `VAR=x`, `sudo`, `time`, `nohup`, `timeout`,
  `xargs`, `npx` (and `npx pkg@version`), `pnpm dlx|exec`, `bunx`, `uvx`, `uv run`, `poetry run`, `pipenv run`,
  `conda run`, and `python -m <module>`. Git global options (`git --no-pager -C . push`) are skipped. A pattern
  matches if it matches the command as written or any unwrapped form.
- Files written through the shell count like edits: redirections (`>`, `>>`, `tee`), `sed -i`, `perl -pi`, `cp`,
  `mv`, `rm`, `touch`, `truncate`, `ln`, `dd of=`, `git mv`/`rm`/`checkout --`/`restore`, and file writes in
  `python -c`, `node -e` and heredoc scripts.
- End-state evidence (diff, commits, pushed refs) counts even when no event shows how it happened.
- Globs are repository-relative: `**` spans directories, a glob without `/` matches a file name anywhere,
  `dir/**` matches everything below `dir/`.

## Types

| Type | Parameters | Violated when | Exercised when |
|---|---|---|---|
| `command_forbidden` | `patterns`, optional `preferred`, `preferred_patterns`, `manual_edit_paths` | a command that ran matches a pattern; or a `manual_edit_paths` file changed and no preferred command succeeded | a command matches a pattern or a preferred pattern, or a `manual_edit_paths` file changed |
| `command_required` | `pattern`, `edit_globs` (default all), `require_success` (default true) | after the last edit to a matching file, no matching command ran (successfully) | a matching file was edited |
| `path_forbidden` | `globs`, `existing_only`, `allow_via` | an edit, shell write, delete or rename hits a forbidden path (with `existing_only`, only files that existed before the run); diff changes are allowed when a command matching `allow_via` (a generator) ran | anything under the globs was written, created or deleted |
| `path_required_with` | `when`, `require` | the diff changes a `when` file and no `require` file | the diff changes a `when` file |
| `dependency_unchanged` | optional `manifests`, `allow` | a manifest gained a dependency not on the allow-list, or an install/add command for a new package ran | the run changed any file, or an install/add command ran |
| `content_forbidden_added` | `regex`, `globs` | an added line in a matching file matches the regex | some line was added to a matching file |
| `content_required_added` | `regex`, `globs`, `first_lines` | a new matching file lacks the regex in its first lines | a new matching file was created |
| `commit_message` | `regex` | a new commit's message does not match | a commit was made |
| `no_commit` | — | a commit exists, or `git commit` ran | the diff is non-empty, a commit exists, or a git command ran |
| `no_push` | — | refs reached the remote, or `git push` ran (any options, even `--dry-run` or `--help`) | the diff is non-empty, a commit exists, or a git command ran |
| `file_naming` | `globs`, `pattern` (full match on the file name) | a new or renamed matching file has a name that does not match | a matching file was created or renamed |
| `final_message` | `required` or `forbidden` regex | the final message lacks the required pattern or contains the forbidden one | there is a final message |

Dependencies are read from `package.json`, `pyproject.toml` (PEP 621 arrays, Poetry tables, dependency groups),
`requirements*.txt`, `go.mod`, `Cargo.toml`, `setup.cfg` and `Pipfile`, and from `npm|pnpm|yarn|bun add|install`,
`pip install`, `uv add`, `uv pip install`, `poetry|pdm|pipenv add`, `go get`, `cargo add`, `gem install`,
`composer require` and `conda install`.

## Accuracy

Precision and recall per type on the frozen held-out set (`fixtures/checkers/heldout`, labelled before the checkers
were written) are in the README and in `eval/results/checkers.json`; reproduce them with
`uv run python eval/run_eval.py --section checkers`.
