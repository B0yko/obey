"""Per-agent enforcement targets: where each agent reads hooks from and what obey writes there.

Every target calls the same generated hook script, `.obey/hooks/obey_hook.py <agent> [stop]`, which uses the vendored
rule engine, so what a hook enforces is exactly what the checkers measure.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from obey_cli.enforce.merge import Plan, add_hooks, remove_obey

HOOK = ".obey/hooks/obey_hook.py"
# Rule types each event can enforce.
SHELL_TYPES = {"command_forbidden", "path_forbidden", "dependency_unchanged", "no_commit", "no_push", "commit_message"}
EDIT_TYPES = {
    "path_forbidden",
    "dependency_unchanged",
    "content_forbidden_added",
    "content_required_added",
    "file_naming",
    "command_forbidden",
}
STOP_TYPES = {"command_required", "path_required_with", "final_message", "content_required_added"}


@dataclass
class Target:
    name: str
    display: str
    files: tuple[str, ...]
    write: Callable[[Plan, Sequence[dict[str, Any]]], None]
    remove: Callable[[Plan], None]
    stop: bool  # can block finishing
    edit_block: bool  # can block file edits before they happen
    notes: str


def _types(rules: Sequence[dict[str, Any]]) -> set[str]:
    return {r["checker"]["type"] for r in rules}


def _cmd(script: str, agent: str, event: str | None = None, *, shell: bool = True) -> str:
    args = f" {agent}" + (f" {event}" if event else "")
    if not shell:
        return f"python3 {script}{args}"
    # A missing script must not block the agent (python3 exits 2, which agents read as "block"): skip quietly.
    return f'h={script}; [ -f "$h" ] || exit 0; python3 "$h"{args}'


# --------------------------------------------------------------------------------------------- Claude Code

CLAUDE_CMD = f'"$CLAUDE_PROJECT_DIR/{HOOK}"'


def claude_hooks(rules: Sequence[dict[str, Any]]) -> dict[str, list[Any]]:
    types = _types(rules)
    pre: list[Any] = []
    if types & SHELL_TYPES:
        pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": _cmd(CLAUDE_CMD, "claude")}]})
    if types & EDIT_TYPES:
        pre.append(
            {
                "matcher": "Edit|Write|MultiEdit|NotebookEdit",
                "hooks": [{"type": "command", "command": _cmd(CLAUDE_CMD, "claude")}],
            }
        )
    hooks: dict[str, list[Any]] = {}
    if pre:
        hooks["PreToolUse"] = pre
    if types & STOP_TYPES:
        hooks["Stop"] = [{"hooks": [{"type": "command", "command": _cmd(CLAUDE_CMD, "claude", "stop")}]}]
    return hooks


def _write_claude(plan: Plan, rules: Sequence[dict[str, Any]]) -> None:
    hooks = claude_hooks(rules)
    plan.merge_json(".claude/settings.json", lambda d: add_hooks(d, hooks) if hooks else remove_obey(d))


def _remove_json(rel: str, empty_keys: frozenset[str] | set[str] = frozenset()) -> Callable[[Plan], None]:
    """Remove obey's entries; a file left holding only `empty_keys` (such as Cursor's version) counts as empty."""

    def edit(d: dict[str, Any]) -> dict[str, Any]:
        out = remove_obey(d)
        return {} if set(out) <= set(empty_keys) else out

    def remove(plan: Plan) -> None:
        if (plan.root / rel).exists():
            plan.merge_json(rel, edit)

    return remove


# --------------------------------------------------------------------------------------------- Codex CLI

GIT_ROOT_CMD = f'"$(git rev-parse --show-toplevel 2>/dev/null || pwd)/{HOOK}"'


def codex_hooks(rules: Sequence[dict[str, Any]]) -> dict[str, list[Any]]:
    types = _types(rules)
    pre: list[Any] = []
    if types & SHELL_TYPES:
        pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": _cmd(GIT_ROOT_CMD, "codex")}]})
    if types & EDIT_TYPES:
        pre.append(
            {
                "matcher": "apply_patch|Edit|Write",
                "hooks": [{"type": "command", "command": _cmd(GIT_ROOT_CMD, "codex")}],
            }
        )
    hooks: dict[str, list[Any]] = {}
    if pre:
        hooks["PreToolUse"] = pre
    if types & STOP_TYPES:
        hooks["Stop"] = [{"hooks": [{"type": "command", "command": _cmd(GIT_ROOT_CMD, "codex", "stop")}]}]
    return hooks


def _write_codex(plan: Plan, rules: Sequence[dict[str, Any]]) -> None:
    hooks = codex_hooks(rules)
    plan.merge_json(".codex/hooks.json", lambda d: add_hooks(d, hooks) if hooks else remove_obey(d))


# --------------------------------------------------------------------------------------------- Cursor

CURSOR_CMD = HOOK  # Cursor runs project hooks from the project root; not known to use a shell


def cursor_hooks(rules: Sequence[dict[str, Any]]) -> dict[str, list[Any]]:
    types = _types(rules)
    hooks: dict[str, list[Any]] = {}
    if types & SHELL_TYPES:
        hooks["beforeShellExecution"] = [{"command": _cmd(CURSOR_CMD, "cursor", shell=False), "timeout": 10}]
    if types & EDIT_TYPES:
        hooks["preToolUse"] = [
            {"command": _cmd(CURSOR_CMD, "cursor", shell=False), "matcher": "Write|Delete", "timeout": 10}
        ]
    if types & STOP_TYPES:
        hooks["stop"] = [{"command": _cmd(CURSOR_CMD, "cursor", "stop", shell=False), "loop_limit": 3}]
    return hooks


def _write_cursor(plan: Plan, rules: Sequence[dict[str, Any]]) -> None:
    hooks = cursor_hooks(rules)

    def edit(d: dict[str, Any]) -> dict[str, Any]:
        if not hooks:
            return remove_obey(d)
        out = add_hooks(d, hooks)
        out.setdefault("version", 1)
        return {"version": out.pop("version"), **out}

    plan.merge_json(".cursor/hooks.json", edit)


# --------------------------------------------------------------------------------------------- Gemini CLI

GEMINI_CMD = f'"$GEMINI_PROJECT_DIR/{HOOK}"'


def gemini_hooks(rules: Sequence[dict[str, Any]]) -> dict[str, list[Any]]:
    types = _types(rules)
    tools = []
    if types & SHELL_TYPES:
        tools.append("run_shell_command")
    if types & EDIT_TYPES:
        tools += ["write_file", "replace"]
    hooks: dict[str, list[Any]] = {}
    if tools:
        hooks["BeforeTool"] = [
            {
                "matcher": "|".join(tools),
                "hooks": [{"name": "obey", "type": "command", "command": _cmd(GEMINI_CMD, "gemini"), "timeout": 5000}],
            }
        ]
    if types & STOP_TYPES:
        hooks["AfterAgent"] = [
            {
                "hooks": [
                    {
                        "name": "obey-stop",
                        "type": "command",
                        "command": _cmd(GEMINI_CMD, "gemini", "stop"),
                        "timeout": 10000,
                    }
                ]
            }
        ]
    return hooks


def _write_gemini(plan: Plan, rules: Sequence[dict[str, Any]]) -> None:
    hooks = gemini_hooks(rules)
    plan.merge_json(".gemini/settings.json", lambda d: add_hooks(d, hooks) if hooks else remove_obey(d))


# --------------------------------------------------------------------------------------------- Copilot CLI

COPILOT_CMD = HOOK  # the "bash" key runs in bash


def copilot_hooks(rules: Sequence[dict[str, Any]]) -> dict[str, list[Any]]:
    types = _types(rules)
    hooks: dict[str, list[Any]] = {}
    if types & (SHELL_TYPES | EDIT_TYPES):
        hooks["preToolUse"] = [{"type": "command", "bash": _cmd(COPILOT_CMD, "copilot"), "cwd": ".", "timeoutSec": 30}]
    if types & STOP_TYPES:
        hooks["agentStop"] = [
            {"type": "command", "bash": _cmd(COPILOT_CMD, "copilot", "stop"), "cwd": ".", "timeoutSec": 60}
        ]
    return hooks


def _write_copilot(plan: Plan, rules: Sequence[dict[str, Any]]) -> None:
    hooks = copilot_hooks(rules)
    if hooks:
        plan.put(".github/hooks/obey.json", json.dumps({"version": 1, "hooks": hooks}, indent=2) + "\n")
    else:
        plan.put(".github/hooks/obey.json", None)


def _remove_copilot(plan: Plan) -> None:
    plan.put(".github/hooks/obey.json", None)


# --------------------------------------------------------------------------------------------- OpenCode

OPENCODE_PLUGIN = """// Generated by obey (https://github.com/B0yko/obey). Remove with `obey enforce --remove`.
// Calls the shared rule engine before every tool runs; a thrown error blocks the tool.
export const ObeyGuard = async ({ directory, worktree }) => ({
  "tool.execute.before": async (input, output) => {
    const root = worktree || directory;
    let text = "";
    try {
      const proc = Bun.spawnSync(["python3", `${root}/.obey/hooks/obey_hook.py`, "opencode"], {
        cwd: root,
        stdin: new TextEncoder().encode(JSON.stringify({ tool: input.tool, args: output.args, cwd: root })),
      });
      text = new TextDecoder().decode(proc.stdout).trim();
    } catch (error) {
      console.warn(`obey: hook failed, allowing the tool: ${error}`);
      return;
    }
    if (!text) return;
    let verdict;
    try {
      verdict = JSON.parse(text);
    } catch {
      return;
    }
    if (verdict && verdict.deny) throw new Error(verdict.deny);
  },
});
"""


def _write_opencode(plan: Plan, rules: Sequence[dict[str, Any]]) -> None:
    plan.put(".opencode/plugins/obey.ts", OPENCODE_PLUGIN if _types(rules) & (SHELL_TYPES | EDIT_TYPES) else None)


def _remove_opencode(plan: Plan) -> None:
    plan.put(".opencode/plugins/obey.ts", None)


# --------------------------------------------------------------------------------------------- git pre-commit


def _write_precommit(plan: Plan, rules: Sequence[dict[str, Any]]) -> None:
    pass  # the .obey/pre-commit script is written with the shared files; see enforce.compile


def _remove_precommit(plan: Plan) -> None:
    pass


TARGETS: dict[str, Target] = {
    "claude": Target(
        "claude",
        "Claude Code",
        (".claude/settings.json",),
        _write_claude,
        _remove_json(".claude/settings.json"),
        stop=True,
        edit_block=True,
        notes="PreToolUse deny with hookSpecificOutput; Stop blocks finishing.",
    ),
    "codex": Target(
        "codex",
        "Codex CLI",
        (".codex/hooks.json",),
        _write_codex,
        _remove_json(".codex/hooks.json"),
        stop=True,
        edit_block=True,
        notes="Project hooks load only in a trusted project after the hook is reviewed with /hooks "
        '(headless: trust_level="trusted" plus --dangerously-bypass-hook-trust).',
    ),
    "cursor": Target(
        "cursor",
        "Cursor",
        (".cursor/hooks.json",),
        _write_cursor,
        _remove_json(".cursor/hooks.json", empty_keys={"version"}),
        stop=False,
        edit_block=True,
        notes="beforeShellExecution and preToolUse (Write|Delete) deny; the stop hook can only send a "
        "follow-up message, so stop checks are advisory.",
    ),
    "gemini": Target(
        "gemini",
        "Gemini CLI",
        (".gemini/settings.json",),
        _write_gemini,
        _remove_json(".gemini/settings.json"),
        stop=True,
        edit_block=True,
        notes="BeforeTool deny; AfterAgent deny forces a retry turn.",
    ),
    "copilot": Target(
        "copilot",
        "Copilot CLI",
        (".github/hooks/obey.json",),
        _write_copilot,
        _remove_copilot,
        stop=True,
        edit_block=True,
        notes="preToolUse deny; in -p mode repo hooks need --trust-folder or "
        "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true.",
    ),
    "opencode": Target(
        "opencode",
        "OpenCode",
        (".opencode/plugins/obey.ts",),
        _write_opencode,
        _remove_opencode,
        stop=False,
        edit_block=True,
        notes="tool.execute.before throws; OpenCode has no stop hook, so stop checks are advisory.",
    ),
    "precommit": Target(
        "precommit",
        "git pre-commit",
        (".obey/pre-commit",),
        _write_precommit,
        _remove_precommit,
        stop=False,
        edit_block=False,
        notes="Agent-agnostic: checks the staged diff and the commit message.",
    ),
}
