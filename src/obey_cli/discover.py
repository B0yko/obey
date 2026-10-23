"""Find the agent instruction files in a repository and work out what each one applies to."""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from obey_cli.parse_md import ParsedFile, parse

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    "target",
    ".obey",
    ".obey-work",
}
MAX_IMPORT_DEPTH = 4

# Which agents read which file kinds, as documented by each vendor (see docs/agents.md).
LOADED_BY: dict[str, tuple[str, ...]] = {
    "agents_md": ("claude-code", "codex", "opencode", "cursor", "gemini", "copilot"),
    "claude_md": ("claude-code", "opencode"),
    "claude_import": ("claude-code",),
    "claude_local_md": ("claude-code",),
    "gemini_md": ("gemini",),
    "cursor_mdc": ("cursor",),
    "copilot_repo": ("copilot",),
    "copilot_path": ("copilot",),
}

# How each agent resolves several AGENTS.md files on the way from the repository root to the edited file.
NESTED_SEMANTICS: dict[str, str] = {
    "codex": "concatenates AGENTS.md from the repository root down to the working directory; later files win",
    "opencode": "reads the nearest AGENTS.md walking up from the working directory",
    "claude-code": "loads CLAUDE.md (or AGENTS.md) from the working directory upwards at start and nested files "
    "when it reads files in their directories",
    "cursor": "applies the nearest AGENTS.md to files below its directory",
    "gemini": "loads context files from the working directory upwards and from subdirectories",
    "copilot": "uses the nearest AGENTS.md in the directory tree",
}


@dataclass
class InstructionFile:
    path: str  # repository-relative POSIX path
    kind: str
    scope_paths: list[str]
    loaded_by: tuple[str, ...]
    sha256: str
    parsed: ParsedFile
    imported_from: str | None = None
    activation: str = "always"  # always | globs | agent_requested | manual
    notes: list[str] = field(default_factory=list)


def classify(rel: str) -> str | None:
    p = PurePosixPath(rel)
    name = p.name
    parts = p.parts
    if name == "AGENTS.md":
        return "agents_md"
    if name == "CLAUDE.md":
        return "claude_md"
    if name == "CLAUDE.local.md":
        return "claude_local_md"
    if name == "GEMINI.md":
        return "gemini_md"
    if name.endswith(".mdc") and len(parts) >= 3 and parts[-3:-1] == (".cursor", "rules"):
        return "cursor_mdc"
    if rel == ".github/copilot-instructions.md":
        return "copilot_repo"
    if name.endswith(".instructions.md") and parts[:2] == (".github", "instructions"):
        return "copilot_path"
    return None


def list_files(root: Path) -> list[str]:
    """Repository-relative paths, from `git ls-files` when possible so ignored files never count."""
    if (root / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                capture_output=True,
                check=True,
                timeout=60,
            ).stdout.decode("utf-8", "replace")
            return sorted(p for p in out.split("\0") if p and not _skipped(p))
        except (OSError, subprocess.SubprocessError):
            pass
    found: list[str] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not _skipped(rel):
            found.append(rel)
    return sorted(found)


def _skipped(rel: str) -> bool:
    return any(part in SKIP_DIRS for part in PurePosixPath(rel).parts[:-1])


def _scope_for_dir(directory: str) -> list[str]:
    return ["**"] if directory in ("", ".") else [f"{directory}/**"]


def _split_globs(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        items = [str(v) for v in value]
    else:
        items = [g for g in (s.strip() for s in str(value).split(",")) if g]
    return [g.strip().strip("\"'") for g in items if g.strip()]


def _anchor(globs: list[str], base: str) -> list[str]:
    if base in ("", "."):
        return globs
    return [g if g.startswith(base + "/") else f"{base}/{g}" for g in globs]


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def discover(root: Path, include_local: bool = False) -> list[InstructionFile]:
    """Return every instruction file under `root`, with CLAUDE.md imports resolved."""
    root = root.resolve()
    result: list[InstructionFile] = []
    seen: set[str] = set()
    for rel in list_files(root):
        kind = classify(rel)
        if kind is None or rel in seen or (kind == "claude_local_md" and not include_local):
            continue
        data = (root / rel).read_bytes()
        parsed = parse(data.decode("utf-8", "replace"))
        directory = PurePosixPath(rel).parent.as_posix()
        activation = "always"
        notes: list[str] = []
        if kind == "cursor_mdc":
            base = PurePosixPath(rel).parent.parent.parent.as_posix()
            globs = _split_globs(parsed.frontmatter.get("globs"))
            always = str(parsed.frontmatter.get("alwaysApply", "")).lower() == "true"
            if always:
                scope = _scope_for_dir(base)
            elif globs:
                scope, activation = _anchor(globs, base), "globs"
            elif parsed.frontmatter.get("description"):
                scope, activation = _scope_for_dir(base), "agent_requested"
                notes.append("applied when the agent decides the description is relevant")
            else:
                scope, activation = _scope_for_dir(base), "manual"
                notes.append("applied only when referenced with @rule")
        elif kind == "copilot_path":
            globs = _split_globs(parsed.frontmatter.get("applyTo"))
            scope = globs or ["**"]
            activation = "globs" if globs else "always"
        elif kind == "copilot_repo" or (directory == ".claude" and kind == "claude_md"):
            scope = ["**"]
        else:
            scope = _scope_for_dir(directory)
        item = InstructionFile(
            path=rel,
            kind=kind,
            scope_paths=scope,
            loaded_by=LOADED_BY[kind],
            sha256=_sha256(data),
            parsed=parsed,
            activation=activation,
            notes=notes,
        )
        result.append(item)
        seen.add(rel)
        if kind in ("claude_md", "claude_local_md"):
            result.extend(_resolve_imports(root, item, seen, depth=1))
    return result


def _resolve_imports(root: Path, parent: InstructionFile, seen: set[str], depth: int) -> list[InstructionFile]:
    if depth > MAX_IMPORT_DEPTH:
        return []
    out: list[InstructionFile] = []
    base = PurePosixPath(parent.path).parent
    for target, _line in parent.parsed.imports:
        if target.startswith("~") or target.startswith("/"):
            parent.notes.append(f"import @{target} points outside the repository; not followed")
            continue
        rel = (base / target).as_posix()
        resolved = (root / rel).resolve()
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError:
            parent.notes.append(f"import @{target} points outside the repository; not followed")
            continue
        if rel in seen:
            continue
        if not resolved.is_file():
            parent.notes.append(f"import @{target} not found")
            continue
        data = resolved.read_bytes()
        child = InstructionFile(
            path=rel,
            kind="claude_import",
            scope_paths=list(parent.scope_paths),
            loaded_by=LOADED_BY["claude_import"],
            sha256=_sha256(data),
            parsed=parse(data.decode("utf-8", "replace")),
            imported_from=parent.path,
        )
        seen.add(rel)
        out.append(child)
        out.extend(_resolve_imports(root, child, seen, depth + 1))
    return out


def scope_matches(scope_paths: list[str], path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, g) or (g.endswith("/**") and path.startswith(g[:-2])) for g in scope_paths)
