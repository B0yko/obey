from __future__ import annotations

from pathlib import Path

from obey_cli.discover import discover, scope_matches


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_discovers_all_kinds(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "- Use pnpm.\n")
    _write(tmp_path, "packages/web/AGENTS.md", "- Never use any.\n")
    _write(tmp_path, "CLAUDE.md", "See @docs/a.md\n\n```\n@docs/never.md\n```\n")
    _write(tmp_path, "docs/a.md", "- Run tests. @b.md\n")
    _write(tmp_path, "docs/b.md", "- Do not push. @a.md\n")
    _write(tmp_path, "CLAUDE.local.md", "- Local only.\n")
    _write(tmp_path, "GEMINI.md", "- Use uv.\n")
    _write(
        tmp_path,
        ".cursor/rules/ts.mdc",
        "---\nglobs: src/**/*.ts, *.tsx\nalwaysApply: false\n---\n- No any.\n",
    )
    _write(tmp_path, ".github/copilot-instructions.md", "- Use pytest.\n")
    _write(tmp_path, ".github/instructions/py.instructions.md", '---\napplyTo: "**/*.py"\n---\n- No print.\n')
    _write(tmp_path, "node_modules/x/AGENTS.md", "- vendored\n")
    files = {f.path: f for f in discover(tmp_path)}
    assert set(files) == {
        "AGENTS.md",
        "packages/web/AGENTS.md",
        "CLAUDE.md",
        "docs/a.md",
        "docs/b.md",
        "GEMINI.md",
        ".cursor/rules/ts.mdc",
        ".github/copilot-instructions.md",
        ".github/instructions/py.instructions.md",
    }
    assert files["packages/web/AGENTS.md"].scope_paths == ["packages/web/**"]
    assert files["docs/b.md"].imported_from == "docs/a.md"
    assert files[".cursor/rules/ts.mdc"].scope_paths == ["src/**/*.ts", "*.tsx"]
    assert files[".cursor/rules/ts.mdc"].activation == "globs"
    assert files[".github/instructions/py.instructions.md"].scope_paths == ["**/*.py"]
    assert "claude-code" in files["AGENTS.md"].loaded_by


def test_local_file_opt_in(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.local.md", "- Local only.\n")
    assert discover(tmp_path) == []
    assert [f.path for f in discover(tmp_path, include_local=True)] == ["CLAUDE.local.md"]


def test_missing_and_outside_imports_are_noted(tmp_path: Path) -> None:
    _write(tmp_path, "CLAUDE.md", "@missing.md and @~/.claude/x.md and @../outside.md\n")
    (claude,) = discover(tmp_path)
    assert any("not found" in n for n in claude.notes)
    assert sum("outside the repository" in n for n in claude.notes) == 2


def test_scope_matches() -> None:
    assert scope_matches(["**"], "a/b.py")
    assert scope_matches(["packages/web/**"], "packages/web/src/x.ts")
    assert not scope_matches(["packages/web/**"], "packages/api/x.ts")
