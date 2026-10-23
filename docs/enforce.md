# Enforcement

`obey enforce` compiles rules into hooks. By default it takes every active rule with a mechanical checker; with
`--from .obey/report.json` it takes only the rules an agent broke in that run.

```bash
obey enforce --dry-run                       # show the diff, write nothing
obey enforce                                 # all targets
obey enforce --targets claude,precommit      # some targets
obey enforce --from .obey/report.json        # only rules broken in the last run
obey enforce --remove                        # take obey's entries out again
```

## What it writes

| File | Purpose |
|---|---|
| `.obey/hooks/obey_hook.py` | The hook every agent calls: normalises the agent's payload, asks the engine, answers in the agent's deny format |
| `.obey/hooks/obey_engine.py` | The rule engine, the same file the checkers use (standard library, Python 3.9+) |
| `.obey/hooks/rules.json` | The compiled rules, each with its source file and line |
| `.obey/pre-commit` | Agent-agnostic git hook for the staged diff and the commit message |
| `.claude/settings.json` | Claude Code `PreToolUse` and `Stop` entries (merged) |
| `.codex/hooks.json` | Codex CLI `PreToolUse` and `Stop` entries (merged) |
| `.cursor/hooks.json` | Cursor `beforeShellExecution`, `preToolUse`, `stop` (merged) |
| `.gemini/settings.json` | Gemini CLI `BeforeTool` and `AfterAgent` (merged) |
| `.github/hooks/obey.json` | Copilot CLI `preToolUse` and `agentStop` (owned by obey) |
| `.opencode/plugins/obey.ts` | OpenCode plugin, `tool.execute.before` (owned by obey) |

Commit these files so everyone on the team gets the same enforcement. `.obey/.gitignore` keeps backups, reports and
the ledger out of git.

## What each hook blocks

| Rule type | Before the action (pre-tool) | At the end (stop hook or pre-commit) |
|---|---|---|
| `command_forbidden` | matching shell commands; hand edits of `manual_edit_paths` | lockfile changes in the staged diff |
| `path_forbidden` | edits, writes and deletes of matching paths, including shell writes | staged changes to matching paths |
| `dependency_unchanged` | install/add commands for new packages; manifest edits that add one | staged manifest changes |
| `content_forbidden_added` | edits and writes that add a matching line | staged added lines |
| `content_required_added` | new files without the required header | staged new files |
| `file_naming` | new files with a non-matching name | staged new files |
| `commit_message` | `git commit -m` with a non-matching message | the `commit-msg` hook |
| `no_commit`, `no_push` | `git commit`, `git push` | — |
| `command_required` | — | Stop hook (Claude Code reads the session transcript) |
| `path_required_with` | — | Stop hook, pre-commit |
| `final_message` | — | Stop hook (Claude Code, Codex, Gemini) |

Rules a target cannot enforce are listed as "advisory only" in the command's output.

A denial reads, for example:
`obey: this breaks the rule "Use pnpm for all package operations." (AGENTS.md:14). Found: npm install date-fns.`

## Safety of the merge

- Every key and entry you had stays, in its order. obey recognises its own entries by their command
  (`.obey/hooks/obey_hook.py`), so it adds no marker keys.
- Running `obey enforce` again replaces obey's entries; it never duplicates them.
- Before changing an existing file, obey saves it as `.obey/backup/<path>.orig`. `--remove` deletes obey's entries
  and, if nothing else changed, puts the original bytes back; files obey created are deleted.
- obey never writes outside the repository: not to `~/.claude`, `~/.codex`, `~/.cursor`, `~/.gemini` or
  `~/.copilot`, and not through a symlinked directory. Every path is checked before the first file is written, so a
  refusal leaves the repository as it was. The tests assert this for every target.
- The hook scripts under `.obey/` are written before the settings that call them, and removed after them.
- Settings files with comments (JSONC) are refused with an error instead of being rewritten without the comments.

## Failing open

If the hook hits an internal error (missing rules, a payload it cannot read, a bug), it allows the action and
prints a warning that names the error (`systemMessage` for Claude Code and Codex, stderr elsewhere). A broken obey
must never lock you out of your agent; `obey lint` tells you when the enforcement files are out of date. The
generated commands also skip quietly when `.obey/hooks/obey_hook.py` is missing (for Cursor, which may run the
command without a shell, the command is plain `python3 .obey/hooks/obey_hook.py cursor`).
See `docs/adr/0007-fail-open-hooks.md`.

## Trust prompts

Some agents load project hooks only after you trust them:

- Codex CLI: run `/hooks` once to review and trust them; for headless runs set `trust_level = "trusted"` for the
  project in `~/.codex/config.toml` and pass `--dangerously-bypass-hook-trust`.
- Copilot CLI in prompt mode: `--trust-folder` or `GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true`.
- Cursor: hooks run in trusted workspaces; headless runs need `--trust`.

## Measuring the effect

```bash
obey run --model anthropic/claude-haiku-5.5                  # before: writes .obey/report.json
cp .obey/report.json before.json
obey run --compare before.json --model anthropic/claude-haiku-5.5
```

`--compare` installs the hooks for the broken rules in each run's copy, re-runs their probes and reports compliance
before and after, plus evasions: runs where a hook blocked the direct route at least once and the rule was still
broken another way (for example a hand-edited lockfile after `npm install` was blocked).
