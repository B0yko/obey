# Agents: how obey runs them, isolates them and enforces rules in them

Versions checked on 2026-10-23. Agent CLIs change often; `obey doctor` prints the versions in your sandbox image,
and `eval/contract_check.py` re-runs the live checks below.

## Support matrix

| | Claude Code | Codex CLI | OpenCode | Copilot CLI | Gemini CLI | Cursor CLI |
|---|---|---|---|---|---|---|
| Version verified | 2.1.309 | 0.164.0 | 1.19.4 | 1.0.103 | 0.65.0 | v2026.10.22 (docs) |
| `obey run` adapter | yes | yes | yes | yes (BYOK) | yes (needs a paid Gemini API key) | no (see below) |
| Live run verified | yes | yes | yes | yes | no key, not run | no |
| Model endpoint via the obey gateway | Anthropic Messages | OpenAI Responses | OpenAI Chat Completions | OpenAI Chat Completions | Gemini API | none in the CLI |
| Instruction files it reads | CLAUDE.md, `.claude/CLAUDE.md`; AGENTS.md when there is no CLAUDE.md | AGENTS.override.md, AGENTS.md (root to working dir) | AGENTS.md (nearest), CLAUDE.md as a fallback | AGENTS.md, CLAUDE.md, GEMINI.md, `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md` | GEMINI.md (AGENTS.md only with `context.fileName`) | `.cursor/rules/*.mdc`, AGENTS.md, CLAUDE.md |
| Load probe (repository rule loaded) | passed | passed | passed | passed | not run | not run |
| Isolation probe (decoy global file ignored) | passed | passed | passed | passed | not run | not run |
| Enforcement file | `.claude/settings.json` | `.codex/hooks.json` | `.opencode/plugins/obey.ts` | `.github/hooks/obey.json` | `.gemini/settings.json` | `.cursor/hooks.json` |
| Blocks shell commands | yes, verified live | yes, verified live | yes, verified live | yes, verified live | contract tests | contract tests |
| Blocks file edits | yes | yes (`apply_patch`) | yes | yes | yes | yes (`preToolUse` Write/Delete) |
| Can block finishing (stop checks) | yes (`Stop`) | yes (`Stop`) | no: advisory | yes (`agentStop`) | yes (`AfterAgent`) | no: follow-up message only |

"Contract tests" means the generated hook was tested against payloads written from the agent's documentation, not
against the running CLI.

## How each agent is run

Each run happens in a fresh container (see the README, "Sandbox"). The repository copy is at `/srv/obey/work`,
outside the agent's home directory, so nothing in the home directory can be mistaken for a parent project's
instructions. Every agent talks to the model through obey's gateway with a dummy token; the gateway holds the key.

- **Claude Code:** `claude -p <task> --output-format stream-json --verbose --permission-mode bypassPermissions
  --include-hook-events --model <model>`, with `ANTHROPIC_BASE_URL` pointing at the gateway,
  `ANTHROPIC_AUTH_TOKEN` set to the dummy token, `ANTHROPIC_API_KEY=""`, an empty `CLAUDE_CONFIG_DIR`, and
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. The container user is not root (`bypassPermissions` refuses root).
- **Codex CLI:** `codex exec --json -C /srv/obey/work --dangerously-bypass-approvals-and-sandbox
  --skip-git-repo-check -m <model> <task>`, with a throwaway `CODEX_HOME` whose `config.toml` defines the gateway as
  a Responses-API provider and marks the work directory as trusted.
  - Codex's own `workspace-write` sandbox uses bubblewrap, which cannot create user namespaces inside an
    unprivileged container, so every command failed with it on. The container is the sandbox instead.
  - The provider has to be in user-level config: a project `.codex/config.toml` ignores `model_providers`.
  - With `--unsafe-local`, obey uses `--sandbox workspace-write` instead.
- **OpenCode:** `opencode run --format json --dir /srv/obey/work --auto -m openrouter/<model> <task>`, with
  `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME` and `XDG_STATE_HOME` moved to empty directories,
  `OPENCODE_DISABLE_CLAUDE_CODE=1` (so it does not read `~/.claude/CLAUDE.md`), `OPENCODE_DISABLE_MODELS_FETCH=1`,
  and the OpenRouter provider's base URL set to the gateway through `OPENCODE_CONFIG_CONTENT`.
- **Copilot CLI:** `copilot -p <task> --output-format json --allow-all-tools --no-ask-user -C /srv/obey/work
  --disable-client-telemetry`, with an empty `COPILOT_HOME` and bring-your-own-key variables
  (`COPILOT_PROVIDER_BASE_URL`, `COPILOT_PROVIDER_TYPE=openai`, `COPILOT_PROVIDER_API_KEY`, `COPILOT_MODEL`,
  `COPILOT_OFFLINE=true`). No GitHub login is used.
- **Gemini CLI:** `gemini -p <task> -o stream-json --approval-mode yolo -m <model>` with an empty `GEMINI_CLI_HOME`.
  Gemini CLI speaks only the Gemini API and accepts plain HTTP only on localhost, so the container forwards
  `127.0.0.1:8788` to the gateway's Gemini route. It needs a paid Gemini API key; obey's own study did not use it.
- **Cursor CLI:** not supported by `obey run` in this version: the CLI has no custom model endpoint, so the key would
  have to enter the container. `obey enforce` still generates Cursor hooks.

## Isolation, verified

`eval/contract_check.py` puts a decoy global instruction file where each agent would read one
(`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.config/opencode/AGENTS.md`, `~/.copilot/copilot-instructions.md`)
stating a different project codename, and asks the agent to quote every codename in its instructions. With the
isolation switches above, all four agents quoted only the repository's codename.

One finding on the way: with the work directory inside `$HOME`, Claude Code loaded the decoy
`~/.claude/CLAUDE.md` even with `CLAUDE_CONFIG_DIR` pointing elsewhere, because `~/.claude/CLAUDE.md` is also the
`.claude/CLAUDE.md` of a parent directory of the project. Moving the work directory out of `$HOME` fixed it. If you
run Claude Code in a project under your home directory, `CLAUDE_CONFIG_DIR` alone does not keep your personal
`~/.claude/CLAUDE.md` out.

## What obey reads from each stream

| | Shell commands and exit codes | File edits | Final message | Tokens and cost |
|---|---|---|---|---|
| Claude Code | `tool_use` Bash; exit code from the `tool_result` error text | Edit/Write/MultiEdit inputs | `result.result` | gateway ledger |
| Codex CLI | `command_execution` with `exit_code`; a command its hook blocked emits no item | `file_change` paths (content from the end-state diff) | last `agent_message` | gateway ledger |
| OpenCode | `tool_use` bash with `metadata.exit` | edit/write inputs | last `text` part | gateway ledger |
| Copilot CLI | `tool.execution_start` / `tool.execution_complete` | create/edit arguments | last `assistant.message` | gateway ledger |
| Gemini CLI | `tool_use` run_shell_command; exit code from `Exit Code: N` text | write_file/replace | assistant message deltas | gateway ledger |

Hook denials are also written by the generated hook to `$OBEY_HOOK_LOG`, which is how obey counts blocked attempts
for agents whose stream does not show them.

## Enforcement details

- **Claude Code:** `PreToolUse` entries (matcher `Bash`, and `Edit|Write|MultiEdit|NotebookEdit`) answer with
  `hookSpecificOutput.permissionDecision: "deny"` and a reason that cites the instruction file and line; a `Stop`
  entry blocks finishing for required commands, paired paths and required headers. `claude -p` runs project hooks
  without a trust prompt.
- **Codex CLI:** the same JSON shape in `.codex/hooks.json`. Project hooks load only in a trusted project and only
  after you review them with `/hooks`; headless runs need `trust_level = "trusted"` for the project in your
  `config.toml` and `--dangerously-bypass-hook-trust`. Codex itself calls hooks "a useful guardrail, not a complete
  enforcement boundary".
- **OpenCode:** a project plugin whose `tool.execute.before` calls the hook script and throws when it denies.
- **Copilot CLI:** `preToolUse` in `.github/hooks/obey.json`. In prompt mode, repository hooks load only with
  `--trust-folder` or `GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true`. Copilot fails closed when a hook crashes; obey's
  hook exits 0 with no output on internal errors so it still fails open.
- **Gemini CLI:** `BeforeTool` (matchers `run_shell_command|write_file|replace`) answering `{"decision": "deny"}`.
- **Cursor:** `beforeShellExecution` and `preToolUse` (Write|Delete) answering `{"permission": "deny"}`; its stop
  hook can only send a follow-up message, so stop-time rules are advisory for Cursor.
- **Any agent, and people:** `.obey/pre-commit` checks the staged diff and the commit message.
