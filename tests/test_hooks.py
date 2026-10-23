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


# --------------------------------------------------------------------------------------------- review fixes


def test_existing_only_looks_at_the_disk_for_shell_writes(repo: Path) -> None:
    def run(cmd: str, cwd: Path | None = None) -> str | None:
        payload = SHELL_PAYLOADS["claude"](repo, cmd)
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return denied("claude", hook(repo, "claude", payload)[0])

    assert run("echo 'select 1' > migrations/0009_new.sql") is None
    assert run("mkdir -p migrations/new") is None
    assert run("echo x > 0009_new.sql", repo / "migrations") is None
    assert "migration" in (run("echo x >> migrations/0001_init.sql") or "")
    assert "migration" in (run("cp src/a.ts migrations/0001_init.sql") or "")
    assert "migration" in (run("echo x>>migrations/0001_init.sql") or "")
    assert run("grep '>' migrations/0001_init.sql") is None
    # A relative path is taken against the payload's cwd, and a cd moves it.
    assert "migration" in (run("echo x >> 0001_init.sql", repo / "migrations") or "")
    assert "migration" in (run("cd migrations && echo x >> 0001_init.sql") or "")
    assert "migration" in (run("pushd migrations; sed -i s/a/b/ 0001_init.sql") or "")
    assert run("cd src && echo x >> 0001_init.sql") is None


def test_paths_through_symlinks_and_aliases_are_the_same_file(repo: Path, tmp_path: Path) -> None:
    (repo / "src" / "link").symlink_to("../migrations")
    alias = tmp_path / "alias"
    alias.symlink_to(repo)
    edit = EDIT_PAYLOADS["claude"]
    for path, cwd in [
        (repo / "src" / "link" / "0001_init.sql", repo),
        (alias / "migrations" / "0001_init.sql", repo),
        (repo / "migrations" / "0001_init.sql", alias),
        (alias / "migrations" / "0001_init.sql", alias),
    ]:
        payload = {**edit(str(path), "id INTEGER", "id INTEGER, note TEXT"), "cwd": str(cwd)}
        assert "migration" in (denied("claude", hook(repo, "claude", payload)[0]) or ""), (path, cwd)
    shell = SHELL_PAYLOADS["claude"](repo, "echo x >> src/link/0001_init.sql")
    assert "migration" in (denied("claude", hook(repo, "claude", shell)[0]) or "")
    # A nested .git does not make the nested directory the project.
    (repo / "src" / "vendor" / ".git").mkdir(parents=True)
    payload = {**edit(str(repo / "migrations" / "0001_init.sql"), "a", "b"), "cwd": str(repo / "src" / "vendor")}
    assert "migration" in (denied("claude", hook(repo, "claude", payload)[0]) or "")


def test_codex_patch_paths_are_relative_to_the_payload_cwd(repo: Path) -> None:
    patch = "*** Begin Patch\n*** Update File: 0001_init.sql\n@@\n-id INTEGER\n+id INTEGER, note TEXT\n*** End Patch\n"
    payload = {"tool_name": "apply_patch", "tool_input": {"command": patch}, "cwd": str(repo / "migrations")}
    assert "migration" in (denied("codex", hook(repo, "codex", payload)[0]) or "")
    payload["cwd"] = str(repo / "src")
    assert denied("codex", hook(repo, "codex", payload)[0]) is None


def test_a_list_valued_command_is_read_as_a_command_line(repo: Path) -> None:
    for argv in (["npm", "install", "zod"], ["bash", "-lc", "cd . && npm install zod"]):
        payload = {"tool_name": "shell", "tool_input": {"command": argv}, "cwd": str(repo)}
        assert "npm install zod" in (denied("codex", hook(repo, "codex", payload)[0]) or ""), argv
    payload = {"tool_name": "shell", "tool_input": {"command": ["pnpm", "add", "zod"]}, "cwd": str(repo)}
    assert denied("codex", hook(repo, "codex", payload)[0]) is None


def _transcript(path: Path, *events: tuple[str, str]) -> None:
    """A Claude Code transcript: ("edit", file) | ("bash", command, shown as run without error) | ("say", text)."""
    lines: list[dict[str, Any]] = []
    for i, (kind, value) in enumerate(events):
        if kind == "say":
            lines.append(
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": value}]}}
            )
            continue
        name, data = ("Edit", {"file_path": value}) if kind == "edit" else ("Bash", {"command": value})
        lines.append({"message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": data}]}})
        lines.append({"message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def _stop(repo: Path, transcript: Path | None, session: str, tmp: Path, agent: str = "claude") -> bool:
    payload: dict[str, Any] = {"session_id": session, "cwd": str(repo)}
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    out, err, code, _ = hook(repo, agent, payload, "stop", env={"TMPDIR": str(tmp)})
    assert code == 0, err
    return bool(out) and json.loads(out).get("decision") == "block"


def test_stop_counts_only_blocked_stops_and_resets_when_one_passes(repo: Path, tmp_path: Path) -> None:
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    transcript = tmp_path / "t.jsonl"
    edited = str(repo / "src" / "a.ts")
    (repo / "src" / "a.ts").write_text("export const a = 2;\n")
    # Passing stops (no edit yet) do not use up the allowance of a session...
    _transcript(transcript, ("say", "hello"))
    assert [_stop(repo, transcript, "s1", tmp) for _ in range(5)] == [False] * 5
    # ...so an edit without tests is blocked three times, then let through, and the count starts over.
    _transcript(transcript, ("edit", edited))
    assert [_stop(repo, transcript, "s1", tmp) for _ in range(5)] == [True, True, True, False, True]
    # A stop that passes resets the count.
    assert _stop(repo, transcript, "s1", tmp) is True
    _transcript(transcript, ("edit", edited), ("bash", "pnpm test"))
    assert _stop(repo, transcript, "s1", tmp) is False
    _transcript(transcript, ("edit", edited))
    assert [_stop(repo, transcript, "s1", tmp) for _ in range(4)] == [True, True, True, False]
    # Sessions are counted separately.
    assert _stop(repo, transcript, "s2", tmp) is True


def test_stop_ignores_the_users_own_uncommitted_work(repo: Path, tmp_path: Path) -> None:
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    transcript = tmp_path / "t.jsonl"
    (repo / "src" / "a.ts").write_text("export const a = 'the user was here';\n")
    (repo / "src" / "new.ts").write_text("export const b = 1;\n")
    _transcript(transcript, ("say", "just answering a question"))
    assert _stop(repo, transcript, "q1", tmp) is False
    # The agent's own edit of another file does count, and only that file.
    _transcript(transcript, ("edit", str(repo / "docs.md")))
    assert _stop(repo, transcript, "q2", tmp) is True
    # Whatever the agent edited in a file that the user had changed too is the agent's change.
    _transcript(transcript, ("edit", str(repo / "src" / "a.ts")), ("bash", "pnpm test"))
    assert _stop(repo, transcript, "q3", tmp) is False


def test_stop_without_a_transcript_does_not_require_commands(repo: Path, tmp_path: Path) -> None:
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    (repo / "src" / "a.ts").write_text("export const a = 2;\n")
    assert _stop(repo, None, "c1", tmp, agent="codex") is False
    other = tmp_path / "rollout.jsonl"  # a transcript in some other format: commands are still unknown
    other.write_text('{"type": "response_item", "payload": {}}\n')
    assert _stop(repo, other, "c2", tmp, agent="codex") is False


def test_stop_does_not_take_command_output_for_a_hook_denial(repo: Path, tmp_path: Path) -> None:
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    transcript = tmp_path / "t.jsonl"
    lines: list[dict[str, Any]] = [
        {
            "message": {
                "content": [
                    {"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": str(repo / "src" / "a.ts")}}
                ]
            }
        },
        {"message": {"content": [{"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "pnpm test"}}]}},
        {
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "b",
                        "is_error": False,
                        "content": "3 passed (hook blocked path, denied)",
                    }
                ]
            }
        },
    ]
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    (repo / "src" / "a.ts").write_text("export const a = 2;\n")
    assert _stop(repo, transcript, "d1", tmp) is False
    lines[2]["message"]["content"][0] = {
        "type": "tool_result",
        "tool_use_id": "b",
        "is_error": True,
        "content": 'PreToolUse:Bash hook error: obey: this breaks the rule "Use pnpm." (AGENTS.md:3).',
    }
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    assert _stop(repo, transcript, "d2", tmp) is True  # that run was refused, so the tests never ran


def test_pre_commit_blocks_when_installed_as_a_symlink(repo: Path) -> None:
    script = repo / ".obey" / "pre-commit"
    script.chmod(0o755)
    (repo / ".git" / "hooks" / "pre-commit").symlink_to("../../.obey/pre-commit")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def commit() -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, env=env, capture_output=True, text=True)

    (repo / "migrations" / "0001_init.sql").write_text("CREATE TABLE a (id INTEGER, note TEXT);\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    blocked = commit()
    assert blocked.returncode != 0 and "obey: commit blocked" in blocked.stderr, blocked.stderr
    assert "ModuleNotFoundError" not in blocked.stderr
    subprocess.run(["git", "reset", "-q", "migrations"], cwd=repo, check=True)
    (repo / "src" / "a.ts").write_text("export const a = 2;\n")
    subprocess.run(["git", "add", "src/a.ts"], cwd=repo, check=True)
    assert commit().returncode == 0
    # Run directly, from the repository, it gives the same answer.
    (repo / "migrations" / "0001_init.sql").write_text("CREATE TABLE a (id INTEGER, note TEXT, more TEXT);\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    direct = subprocess.run([PY, str(script)], cwd=repo, capture_output=True, text=True)
    assert direct.returncode == 1 and "obey: commit blocked" in direct.stderr
