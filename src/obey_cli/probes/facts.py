"""Facts about a repository that probe templates fill in: languages, package manager, test command, layout."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from obey_cli.discover import list_files

_LANG_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".mjs": "javascript",
    ".go": "go",
    ".rs": "rust",
}
_SKIP_PARTS = {"generated", "gen", "vendor", "dist", "build", "migrations", "node_modules", "__pycache__"}


@dataclass
class Facts:
    root: Path
    files: list[str]
    language: str  # python | typescript | javascript | go | rust | unknown
    package_manager: str | None  # pnpm | npm | yarn | bun | uv | poetry | pip | go | cargo
    test_command: str | None
    lint_command: str | None
    source_files: list[str] = field(default_factory=list)  # ordinary source files, most central first
    test_files: list[str] = field(default_factory=list)
    source_dir: str = "src"
    test_dir: str = "tests"
    migrations: list[str] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)

    @property
    def ext(self) -> str:
        return {"python": ".py", "typescript": ".ts", "javascript": ".js", "go": ".go", "rust": ".rs"}.get(
            self.language, ".txt"
        )


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def detect(root: Path) -> Facts:
    files = list_files(root)
    langs = Counter(_LANG_EXT[PurePosixPath(f).suffix] for f in files if PurePosixPath(f).suffix in _LANG_EXT)
    language = langs.most_common(1)[0][0] if langs else "unknown"
    if language == "javascript" and langs.get("typescript"):
        language = "typescript"
    names = set(files)
    pm = None
    pkg = json.loads(_read(root, "package.json") or "{}") if "package.json" in names else {}
    declared = str(pkg.get("packageManager", ""))
    for candidate, marker in (
        ("pnpm", "pnpm-lock.yaml"),
        ("yarn", "yarn.lock"),
        ("bun", "bun.lock"),
        ("bun", "bun.lockb"),
        ("npm", "package-lock.json"),
    ):
        if marker in names or declared.startswith(candidate + "@"):
            pm = candidate
            break
    if pm is None and "package.json" in names:
        pm = "npm"
    if pm is None:
        pyproject = _read(root, "pyproject.toml")
        if "uv.lock" in names or "[tool.uv]" in pyproject or "[dependency-groups]" in pyproject:
            pm = "uv"
        elif "poetry.lock" in names or "[tool.poetry]" in pyproject:
            pm = "poetry"
        elif pyproject or any(f.startswith("requirements") for f in names):
            pm = "uv" if "uv" in _read(root, "Makefile") else "pip"
        elif "go.mod" in names:
            pm = "go"
        elif "Cargo.toml" in names:
            pm = "cargo"
    test_cmd = lint_cmd = None
    makefile = _read(root, "Makefile")
    if re.search(r"^test:", makefile, re.M):
        test_cmd = "make test"
    if re.search(r"^lint:", makefile, re.M):
        lint_cmd = "make lint"
    scripts = pkg.get("scripts") or {}
    if test_cmd is None and "test" in scripts:
        test_cmd = f"{pm or 'npm'} test"
    if lint_cmd is None and "lint" in scripts:
        lint_cmd = f"{pm or 'npm'} run lint" if pm in (None, "npm") else f"{pm} lint"
    if test_cmd is None and language == "python":
        test_cmd = "uv run pytest" if pm == "uv" else "pytest"
    if test_cmd is None and language == "go":
        test_cmd = "go test ./..."
    if test_cmd is None and language == "rust":
        test_cmd = "cargo test"
    ext = {"python": ".py", "typescript": ".ts", "javascript": ".js", "go": ".go", "rust": ".rs"}.get(language, "")

    def is_test(f: str) -> bool:
        name = PurePosixPath(f).name
        return bool(re.match(r"test_.*\.py$|.*_test\.(py|go)$|.*\.(test|spec)\.[jt]sx?$", name)) or f.startswith(
            ("tests/", "test/")
        )

    sources = [
        f
        for f in files
        if f.endswith(ext)
        and not is_test(f)
        and not (set(PurePosixPath(f).parts) & _SKIP_PARTS)
        and not f.startswith(("scripts/", "tools/"))
        and PurePosixPath(f).name not in ("__init__.py", "main.ts")
    ]
    sources.sort(key=lambda f: (-len(_read(root, f)), f))
    tests = [f for f in files if is_test(f)]
    src_dir = Counter(PurePosixPath(f).parts[0] for f in sources if len(PurePosixPath(f).parts) > 1).most_common(1)
    test_dir = (
        "tests"
        if any(f.startswith("tests/") for f in files)
        else "test"
        if any(f.startswith("test/") for f in files)
        else (PurePosixPath(tests[0]).parent.as_posix() if tests else "tests")
    )
    migrations = sorted(
        f for f in files if "/migrations/" in f"/{f}" and f.endswith((".sql", ".py")) and not f.endswith("__init__.py")
    )
    generated = (
        sorted(
            f
            for f in files
            if "generated" in PurePosixPath(f).parts
            or re.search(r"(do not edit|generated by|auto-?generated)", _read(root, f)[:400], re.I)
        )
        if files
        else []
    )
    generated = [g for g in generated if not g.endswith((".md", "__init__.py")) and g not in ("AGENTS.md", "CLAUDE.md")]
    generated.sort(
        key=lambda g: (not re.search(r"(do not edit|generated by|generated from)", _read(root, g)[:400], re.I), g)
    )
    return Facts(
        root=root,
        files=files,
        language=language,
        package_manager=pm,
        test_command=test_cmd,
        lint_command=lint_cmd,
        source_files=sources,
        test_files=tests,
        source_dir=src_dir[0][0] if src_dir else "src",
        test_dir=test_dir,
        migrations=migrations,
        generated=generated,
    )
