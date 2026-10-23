from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from obey_cli.runner.workspace import (
    WorkspaceError,
    build_probe_copy,
    collect_end_state,
    git,
    remove_lines,
    set_origin,
    tracked_files,
)


def _repo(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "AGENTS.md").write_text("# Rules\n- Use pnpm.\n- Never push.\n")
    (src / "app" / "main.py").write_text("print('hi')\n")
    (src / ".gitignore").write_text("build/\n")
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    subprocess.run(["git", "add", "-A"], cwd=src, check=True)
    (src / ".env").write_text("SECRET=1\n")
    (src / "build").mkdir()
    (src / "build" / "out.js").write_text("x")
    return src


def test_only_tracked_files_are_copied(tmp_path: Path) -> None:
    src = _repo(tmp_path)
    assert tracked_files(src) == [".gitignore", "AGENTS.md", "app/main.py"]
    copy = build_probe_copy(
        src,
        tmp_path / "probe",
        overrides={"AGENTS.md": remove_lines((src / "AGENTS.md").read_text(), 2, 2)},
        extra_files={".obey/hooks/rules.json": "{}"},
        setup_patch="--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-print('hi')\n+print('hello')\n",
        git_hooks={"pre-commit": "#!/bin/sh\nexit 0\n"},
    )
    assert not (copy.work / ".env").exists() and not (copy.work / "build").exists()
    assert (copy.work / "AGENTS.md").read_text() == "# Rules\n- Never push.\n"
    assert (copy.work / "app" / "main.py").read_text() == "print('hello')\n"
    assert copy.base_files == [".gitignore", ".obey/hooks/rules.json", "AGENTS.md", "app/main.py"]
    assert git(copy.work, "log", "--format=%an %s").strip() == "Developer Initial import"
    assert (copy.work / ".git" / "hooks" / "pre-commit").stat().st_mode & 0o111


def test_end_state_captures_uncommitted_commits_and_pushes(tmp_path: Path) -> None:
    copy = build_probe_copy(_repo(tmp_path), tmp_path / "probe")
    assert copy.remote is not None
    set_origin(copy.work, str(copy.remote))
    (copy.work / "app" / "main.py").write_text("print('bye')\n")
    (copy.work / "app" / "new.py").write_text("x = 1\n")
    git(copy.work, "add", "app/new.py")
    git(copy.work, "commit", "-q", "-m", "feat: add new module")
    git(copy.work, "push", "-q", "origin", "main")
    (copy.work / "notes.txt").write_text("untracked\n")
    state = collect_end_state(copy.work, copy.base_sha, copy.remote)
    assert "+print('bye')" in state.diff and "+++ b/app/new.py" in state.diff and "+++ b/notes.txt" in state.diff
    assert [c["message"] for c in state.commits] == ["feat: add new module"]
    assert state.commits[0]["files"] == ["app/new.py"]
    assert state.pushed_refs == ["refs/heads/main"]
    # Reading the end state must not touch the agent's own index.
    assert "notes.txt" not in git(copy.work, "diff", "--cached", "--name-only")


def test_untracked_source_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(WorkspaceError):
        tracked_files(plain)
