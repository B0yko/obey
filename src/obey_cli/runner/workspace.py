"""Build the repository copy an agent works in, and read back what it did.

Only tracked files enter a probe copy (`git ls-files` plus the probe's setup patch), so `.env` files, local
secrets and ignored build output never reach the sandbox or the model provider. The copy gets a fresh git
history with one neutral commit and, in container mode, a local bare `origin` so pushes can be detected.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Developer",
    "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Developer",
    "GIT_COMMITTER_EMAIL": "dev@example.com",
    "GIT_AUTHOR_DATE": "2026-01-05T09:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-05T09:00:00+00:00",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
MAX_DIFF_BYTES = 2_000_000


class WorkspaceError(RuntimeError):
    pass


def git(cwd: Path, *args: str, env: Mapping[str, str] | None = None, check: bool = True) -> str:
    # HOME points at the copy so the user's global git configuration (signing, hooks, aliases) never applies.
    full_env = {**os.environ, **GIT_ENV, "HOME": str(cwd), **(env or {})}
    proc = subprocess.run(["git", *args], cwd=cwd, env=full_env, capture_output=True, check=False, timeout=120)
    if check and proc.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace')[:500]}")
    return proc.stdout.decode("utf-8", "replace")


def tracked_files(repo: Path) -> list[str]:
    """Tracked paths relative to `repo` (which may be a subdirectory of a git repository)."""
    if shutil.which("git") is None:
        raise WorkspaceError("git is not installed")
    probe = subprocess.run(["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"], capture_output=True)
    if probe.returncode != 0:
        raise WorkspaceError(f"{repo} is not inside a git repository; obey copies tracked files only")
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--", "."], capture_output=True, check=True)
    return sorted(p for p in out.stdout.decode("utf-8", "replace").split("\0") if p)


@dataclass
class ProbeCopy:
    root: Path  # parent directory: work/ and .remote/ live inside
    work: Path
    base_sha: str
    base_files: list[str]
    remote: Path | None


def build_probe_copy(
    source: Path,
    dest: Path,
    *,
    overrides: Mapping[str, str | None] | None = None,
    extra_files: Mapping[str, str] | None = None,
    setup_patch: str | None = None,
    with_remote: bool = True,
    files: Sequence[str] | None = None,
    git_hooks: Mapping[str, str] | None = None,
) -> ProbeCopy:
    """Copy tracked files of `source` into `dest/work`, apply overrides and the setup patch, commit once.

    `overrides` replaces (str) or removes (None) files by relative path, for example an instruction file with one
    rule removed. `extra_files` adds files (generated enforcement) before the base commit.
    """
    work = dest / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for rel in files if files is not None else tracked_files(source):
        src = source / rel
        if src.is_symlink() or not src.is_file():
            continue
        target = work / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    for rel, content in {**(overrides or {}), **(extra_files or {})}.items():
        target = work / rel
        if content is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(work, "init", "-q", "-b", "main")
    if setup_patch:
        patch = dest / "setup.patch"
        patch.write_text(setup_patch, encoding="utf-8")
        git(work, "apply", "--whitespace=nowarn", str(patch))
        patch.unlink()
    git(work, "add", "-A")
    git(work, "commit", "-q", "--no-verify", "-m", "Initial import")
    base_sha = git(work, "rev-parse", "HEAD").strip()
    base_files = sorted(p for p in git(work, "ls-files", "-z").split("\0") if p)
    for name, content in (git_hooks or {}).items():
        hook = work / ".git" / "hooks" / name
        hook.write_text(content, encoding="utf-8")
        hook.chmod(0o755)
    remote: Path | None = None
    if with_remote:
        remote = dest / ".remote" / "origin.git"
        remote.parent.mkdir(parents=True, exist_ok=True)
        git(dest, "init", "-q", "--bare", str(remote))
    return ProbeCopy(root=dest, work=work, base_sha=base_sha, base_files=base_files, remote=remote)


def set_origin(work: Path, url: str) -> None:
    git(work, "remote", "add", "origin", url)


@dataclass
class EndState:
    diff: str
    commits: list[dict[str, object]] = field(default_factory=list)
    pushed_refs: list[str] = field(default_factory=list)
    diff_truncated: bool = False


def collect_end_state(work: Path, base_sha: str, remote: Path | None = None) -> EndState:
    """Diff of everything that changed since the base commit (committed or not), plus new commits and pushes."""
    index = work.parent / ".obey-index"
    env = {"GIT_INDEX_FILE": str(index)}
    git(work, "read-tree", base_sha, env=env)
    git(work, "add", "-A", "--", ".", env=env)
    diff = git(work, "diff", "--cached", "--binary", "--no-color", "--no-ext-diff", base_sha, env=env)
    index.unlink(missing_ok=True)
    truncated = len(diff) > MAX_DIFF_BYTES
    if truncated:
        diff = diff[:MAX_DIFF_BYTES]
    commits: list[dict[str, object]] = []
    shas = [s for s in git(work, "rev-list", "--all", "--reverse", f"^{base_sha}", check=False).split() if s]
    for sha in shas:
        message = git(work, "log", "-1", "--format=%B", sha).rstrip("\n")
        files = [f for f in git(work, "show", "--name-only", "--format=", sha).splitlines() if f]
        commits.append({"sha": sha, "message": message, "files": files})
    pushed: list[str] = []
    if remote is not None and remote.exists():
        pushed = [r for r in git(remote, "for-each-ref", "--format=%(refname)").splitlines() if r]
    return EndState(diff=diff, commits=commits, pushed_refs=pushed, diff_truncated=truncated)


def remove_lines(text: str, start: int, end: int) -> str:
    """Drop 1-based lines start..end (inclusive), e.g. to build the no-rule baseline of an instruction file."""
    lines = text.splitlines(keepends=True)
    return "".join(lines[: start - 1] + lines[end:])
