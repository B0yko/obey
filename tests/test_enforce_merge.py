"""Settings-merge safety: user entries survive, merges are idempotent, removal restores the original bytes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from obey_cli.enforce.merge import Plan, add_hooks, remove_obey
from obey_cli.enforce.targets import TARGETS

RULES: list[dict[str, Any]] = [
    {
        "id": "use-pnpm-1",
        "text": "Use pnpm.",
        "source": {"file": "AGENTS.md", "lines": [3, 3]},
        "checker": {"type": "command_forbidden", "params": {"patterns": ["^npm\\b"]}},
    },
    {
        "id": "no-any-2",
        "text": "No any.",
        "source": {"file": "AGENTS.md", "lines": [4, 4]},
        "checker": {"type": "content_forbidden_added", "params": {"regex": ":\\s*any\\b", "globs": ["**/*.ts"]}},
    },
    {
        "id": "tests-3",
        "text": "Run tests.",
        "source": {"file": "AGENTS.md", "lines": [5, 5]},
        "checker": {"type": "command_required", "params": {"pattern": "^pnpm test"}},
    },
]

USER_SETTINGS = {
    "claude": (
        ".claude/settings.json",
        {
            "permissions": {"allow": ["Bash(ls:*)"]},
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "./my-guard.sh"}]}],
                "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "prettier -w"}]}],
            },
            "model": "sonnet",
        },
    ),
    "codex": (".codex/hooks.json", {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify.sh"}]}]}}),
    "cursor": (".cursor/hooks.json", {"version": 1, "hooks": {"afterFileEdit": [{"command": "./fmt.sh"}]}}),
    "gemini": (
        ".gemini/settings.json",
        {
            "theme": "GitHub",
            "hooks": {
                "BeforeTool": [{"matcher": "write_file", "hooks": [{"type": "command", "command": "./audit.sh"}]}]
            },
        },
    ),
}


def _apply(root: Path, fn: Any) -> None:
    plan = Plan(root)
    fn(plan)
    plan.apply()


def _write_user(root: Path, rel: str, data: dict[str, Any], indent: int) -> bytes:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, indent=indent) + "\n").encode()
    path.write_bytes(raw)
    return raw


@pytest.mark.parametrize("name", sorted(USER_SETTINGS))
@pytest.mark.parametrize("indent", [2, 4])
def test_user_entries_preserved_idempotent_and_removable(tmp_path: Path, name: str, indent: int) -> None:
    rel, data = USER_SETTINGS[name]
    original = _write_user(tmp_path, rel, data, indent)
    target = TARGETS[name]
    _apply(tmp_path, lambda p: target.write(p, RULES))
    merged = json.loads((tmp_path / rel).read_text())
    # Every user key and hook entry is still there, in order.
    assert remove_obey(merged) == data
    assert ".obey/hooks/obey_hook.py" in json.dumps(merged)
    once = (tmp_path / rel).read_bytes()
    _apply(tmp_path, lambda p: target.write(p, RULES))
    assert (tmp_path / rel).read_bytes() == once  # idempotent
    assert (tmp_path / ".obey/backup" / (rel + ".orig")).read_bytes() == original
    _apply(tmp_path, target.remove)
    assert (tmp_path / rel).read_bytes() == original  # byte-exact restore


@pytest.mark.parametrize("name", ["claude", "codex", "cursor", "gemini", "copilot", "opencode"])
def test_created_files_are_deleted_on_remove(tmp_path: Path, name: str) -> None:
    target = TARGETS[name]
    _apply(tmp_path, lambda p: target.write(p, RULES))
    created = [rel for rel in target.files if (tmp_path / rel).exists()]
    assert created, name
    _apply(tmp_path, target.remove)
    assert not any((tmp_path / rel).exists() for rel in target.files)


def test_shared_matcher_group_keeps_user_hook(tmp_path: Path) -> None:
    data = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "./mine.sh"},
                        {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.obey/hooks/obey_hook.py" claude'},
                    ],
                }
            ]
        }
    }
    assert remove_obey(data) == {
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "./mine.sh"}]}]}
    }


def test_add_hooks_replaces_previous_obey_entries() -> None:
    entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 .obey/hooks/obey_hook.py claude"}]}
    twice = add_hooks(add_hooks({}, {"PreToolUse": [entry]}), {"PreToolUse": [entry]})
    assert twice == {"hooks": {"PreToolUse": [entry]}}


def test_nothing_outside_the_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for target in TARGETS.values():
        _apply(repo, lambda p, t=target: t.write(p, RULES))
    assert list(home.iterdir()) == []
    plan = Plan(repo)
    plan.put("../escape.json", "{}")
    with pytest.raises(ValueError, match="outside the repository"):
        plan.apply()
    assert not (tmp_path / "escape.json").exists()


def test_refuses_non_object_json(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/settings.json").write_text("[1, 2]\n")
    with pytest.raises(ValueError, match="not a JSON object"):
        _apply(tmp_path, lambda p: TARGETS["claude"].write(p, RULES))
