"""Contract tests for the generated hooks: each agent's payload shape in, each agent's deny format out.

Payload shapes come from payloads the CLIs sent in live runs (fixtures/hook-payloads) and, for Gemini CLI and
Cursor, from their documentation. The hook runs as a subprocess with OBEY_HOOK_PYTHON (default: this interpreter);
CI also runs it under Python 3.9.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from obey_cli.enforce import plan_enforce

PY = os.environ.get("OBEY_HOOK_PYTHON", sys.executable)
FIXTURES = Path(__file__).parents[1] / "fixtures" / "hook-payloads"

RULES = [
    {
        "id": "pnpm",
        "text": "Use pnpm for all package operations.",
        "source": {"file": "AGENTS.md", "lines": [3, 3]},
        "checker": {
            "type": "command_forbidden",
            "params": {"patterns": ["^npm\\b"], "preferred_patterns": ["^pnpm\\b"]},
        },
    },
    {
        "id": "mig",
        "text": "Never edit an existing migration.",
        "source": {"file": "AGENTS.md", "lines": [4, 4]},
        "checker": {"type": "path_forbidden", "params": {"globs": ["migrations/**"], "existing_only": True}},
    },
    {
        "id": "any",
        "text": "Never use any.",
        "source": {"file": "AGENTS.md", "lines": [5, 5]},
        "checker": {"type": "content_forbidden_added", "params": {"regex": ":\\s*any\\b", "globs": ["**/*.ts"]}},
    },
    {
        "id": "tests",
        "text": "Run pnpm test before you finish.",
        "source": {"file": "AGENTS.md", "lines": [6, 6]},
        "checker": {"type": "command_required", "params": {"pattern": "^pnpm\\s+(run\\s+)?test\\b"}},
    },
]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "migrations").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "migrations" / "0001_init.sql").write_text("CREATE TABLE a (id INTEGER);\n")
    (root / "src" / "a.ts").write_text("export const a = 1;\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "init"], cwd=root, check=True
    )
    plan_enforce(root, RULES, ["claude", "codex", "cursor", "gemini", "copilot", "opencode", "precommit"]).apply()
    return root


def hook(
    repo: Path, agent: str, payload: Any, event: str | None = None, env: dict[str, str] | None = None
) -> tuple[str, str, int, float]:
    args = [PY, str(repo / ".obey" / "hooks" / "obey_hook.py"), agent] + ([event] if event else [])
    started = time.perf_counter()
    proc = subprocess.run(
        args,
        input=payload if isinstance(payload, str) else json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=repo,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "GEMINI_PROJECT_DIR": str(repo), **(env or {})},
        timeout=30,
    )
    return proc.stdout.strip(), proc.stderr, proc.returncode, (time.perf_counter() - started) * 1000


def recorded(agent: str) -> dict[str, Any]:
    entry = json.loads((FIXTURES / f"{agent}-pretooluse-shell.json").read_text())[0]
    payload: dict[str, Any] = entry["payload"]
    return payload


def with_command(agent: str, repo: Path, command: str) -> dict[str, Any]:
    p = json.loads(json.dumps(recorded(agent)))
    p["cwd"] = str(repo)
    if agent in ("claude-code", "codex"):
        p["tool_input"]["command"] = command
    elif agent == "copilot":
        p["toolArgs"]["command"] = command
    elif agent == "opencode":
        p["args"]["command"] = command
        p["args"]["workdir"] = str(repo)
    return p


SHELL_PAYLOADS = {
    "claude": lambda repo, cmd: with_command("claude-code", repo, cmd),
    "codex": lambda repo, cmd: with_command("codex", repo, cmd),
    "copilot": lambda repo, cmd: with_command("copilot", repo, cmd),
    "opencode": lambda repo, cmd: with_command("opencode", repo, cmd),
    # Documented shapes (not captured live).
    "gemini": lambda repo, cmd: {
        "session_id": "s",
        "cwd": str(repo),
        "hook_event_name": "BeforeTool",
        "tool_name": "run_shell_command",
        "tool_input": {"command": cmd},
    },
    "cursor": lambda repo, cmd: {
        "conversation_id": "c",
        "hook_event_name": "beforeShellExecution",
        "command": cmd,
        "cwd": str(repo),
    },
}


def denied(agent: str, out: str) -> str | None:
    if not out:
        return None
    data = json.loads(out)
    if agent in ("claude", "codex"):
        h = data.get("hookSpecificOutput") or {}
        return h.get("permissionDecisionReason") if h.get("permissionDecision") == "deny" else None
    if agent == "copilot":
        return data.get("permissionDecisionReason") if data.get("permissionDecision") == "deny" else None
    if agent == "gemini":
        return data.get("reason") if data.get("decision") == "deny" else None
    if agent == "cursor":
        return data.get("agent_message") if data.get("permission") == "deny" else None
    return data.get("deny")


@pytest.mark.parametrize("agent", sorted(SHELL_PAYLOADS))
def test_shell_deny_and_allow(repo: Path, agent: str) -> None:
    out, err, code, _ = hook(repo, agent, SHELL_PAYLOADS[agent](repo, "cd . && npm install zod"))
    reason = denied(agent, out)
    assert code == 0 and reason and "AGENTS.md:3" in reason and "npm install zod" in reason, (out, err)
    out, _, code, _ = hook(repo, agent, SHELL_PAYLOADS[agent](repo, "pnpm add zod && pnpm test"))
    assert code == 0 and out == ""
    out, _, _, _ = hook(repo, agent, SHELL_PAYLOADS[agent](repo, "sed -i 's/a/b/' migrations/0001_init.sql"))
    assert "migration" in (denied(agent, out) or "")


EDIT_PAYLOADS = {
    "claude": lambda path, old, new: {
        "tool_name": "Edit",
        "tool_input": {"file_path": path, "old_string": old, "new_string": new},
    },
    "codex": lambda path, old, new: {
        "tool_name": "apply_patch",
        "tool_input": {"command": f"*** Begin Patch\n*** Update File: {path}\n@@\n-{old}\n+{new}\n*** End Patch\n"},
    },
    "copilot": lambda path, old, new: {
        "toolName": "edit",
        "toolArgs": json.dumps({"path": path, "old_str": old, "new_str": new}),
    },
    "gemini": lambda path, old, new: {
        "tool_name": "replace",
        "tool_input": {"file_path": path, "old_string": old, "new_string": new},
    },
    "opencode": lambda path, old, new: {"tool": "edit", "args": {"filePath": path, "oldString": old, "newString": new}},
    "cursor": lambda path, old, new: {
        "hook_event_name": "preToolUse",
        "tool_name": "Write",
        "tool_input": {"path": path, "content": new},
    },
}


@pytest.mark.parametrize("agent", sorted(EDIT_PAYLOADS))
def test_edit_deny_and_allow(repo: Path, agent: str) -> None:
    payload = EDIT_PAYLOADS[agent](str(repo / "src" / "a.ts"), "export const a = 1;", "export const a: any = 1;")
    payload["cwd"] = str(repo)
    out, err, code, _ = hook(repo, agent, payload)
    assert code == 0 and "any" in (denied(agent, out) or ""), (out, err)
    payload = EDIT_PAYLOADS[agent](str(repo / "migrations" / "0001_init.sql"), "id INTEGER", "id INTEGER, note TEXT")
    payload["cwd"] = str(repo)
    out, _, _, _ = hook(repo, agent, payload)
    assert "migration" in (denied(agent, out) or "")
    payload = EDIT_PAYLOADS[agent](str(repo / "src" / "a.ts"), "export const a = 1;", "export const a = 2;")
    payload["cwd"] = str(repo)
    out, _, code, _ = hook(repo, agent, payload)
    assert code == 0 and out == ""


@pytest.mark.parametrize("agent", ["claude", "codex", "copilot", "gemini", "cursor", "opencode"])
def test_fails_open_on_internal_errors(repo: Path, agent: str) -> None:
    (repo / ".obey" / "hooks" / "rules.json").write_text("{not json")
    out, err, code, _ = hook(repo, agent, SHELL_PAYLOADS[agent](repo, "npm install zod"))
    assert code == 0 and "obey hook error, action allowed" in err
    assert denied(agent, out) is None
    out, err, code, _ = hook(repo, agent, "this is not json")
    assert code == 0 and denied(agent, out) is None


def test_claude_stop_hook_requires_tests_after_the_last_edit(repo: Path, tmp_path: Path) -> None:
    (repo / "src" / "a.ts").write_text("export const a = 2;\n")
    lines = [
        {
            "message": {
                "content": [
                    {"type": "tool_use", "id": "e1", "name": "Edit", "input": {"file_path": str(repo / "src" / "a.ts")}}
                ]
            }
        }
    ]
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    import uuid

    payload = {
        "session_id": f"stop-{uuid.uuid4().hex}",
        "cwd": str(repo),
        "transcript_path": str(transcript),
        "stop_hook_active": False,
    }
    out, _, code, _ = hook(repo, "claude", payload, "stop")
    assert code == 0 and json.loads(out)["decision"] == "block" and "pnpm test" in json.loads(out)["reason"]
    lines += [
        {"message": {"content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "pnpm test"}}]}},
        {"message": {"content": [{"type": "tool_result", "tool_use_id": "b1", "is_error": False, "content": "ok"}]}},
    ]
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    out, _, code, _ = hook(repo, "claude", {**payload, "session_id": f"stop-{uuid.uuid4().hex}"}, "stop")
    assert code == 0 and out == ""


def test_hook_log_records_denials(repo: Path, tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    hook(repo, "claude", SHELL_PAYLOADS["claude"](repo, "npm i x"), env={"OBEY_HOOK_LOG": str(log)})
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["decision"] == "deny" and entry["rule_id"] == "pnpm"


def test_latency_is_small(repo: Path) -> None:
    times = sorted(hook(repo, "claude", SHELL_PAYLOADS["claude"](repo, "pnpm add zod"))[3] for _ in range(20))
    p95 = times[int(len(times) * 0.95) - 1]
    assert p95 < 2000  # generous for shared CI runners; eval/hook_latency.py measures p95 on quiet hardware
