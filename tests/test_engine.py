from __future__ import annotations

import pytest

from obey_cli.enforce.engine import obey_engine as e


def views(cmd: str) -> list[list[str]]:
    return [s["views"] for s in e.segments(cmd)]


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("cd web && npm i lodash", "npm i lodash"),
        ("bash -c 'npm install x'", "npm install x"),
        ("env CI=1 npx -y npm@10 i", "npm i"),
        ("uv run --with x python -m pip install y", "pip install y"),
        ("git --no-pager -C . push origin main", "git push origin main"),
        ("FOO=1 BAR=2 sudo -u ci time npm ci", "npm ci"),
        ("echo $(npm view zod version)", "npm view zod version"),
        ("bash <<'EOF'\nnpm install a\nEOF", "npm install a"),
        ("pnpm dlx create-vite app", "create-vite app"),
    ],
)
def test_segments_unwrap(cmd: str, expected: str) -> None:
    assert any(expected in v for vs in views(cmd) for v in vs)


def test_quotes_and_comments_do_not_split() -> None:
    assert views('echo "a && b; c" # npm install') == [["echo a && b; c"]]


@pytest.mark.parametrize(
    ("cmd", "targets"),
    [
        ("sed -i 's/a/b/' migrations/0001.sql", ["migrations/0001.sql"]),
        ("sed -i '' -e 's/a/b/' x.txt y.txt", ["x.txt", "y.txt"]),
        ("cat >> migrations/0002.sql <<EOF\nALTER TABLE x;\nEOF", ["migrations/0002.sql"]),
        ("echo hi | tee -a notes.md", ["notes.md"]),
        ("python3 -c \"open('gen/x.py','w').write('')\"", ["gen/x.py"]),
        ("mv a.sql migrations/0001.sql", ["a.sql", "migrations/0001.sql"]),
        ("cp new.sql migrations/0001.sql", ["migrations/0001.sql"]),
        ("rm -rf dist", ["dist"]),
        ("git checkout -- src/generated/api.ts", ["src/generated/api.ts"]),
        ("sed -n '1,5p' migrations/0001.sql", []),
        ("cat migrations/0001.sql > /dev/null", []),
    ],
)
def test_shell_write_targets(cmd: str, targets: list[str]) -> None:
    assert [t["path"] for t in e.shell_write_targets(cmd)] == targets


@pytest.mark.parametrize(
    ("globs", "path", "hit"),
    [
        (["migrations/**"], "migrations/0001.sql", True),
        (["migrations/**"], "app/migrations/0001.sql", False),
        (["**/migrations/**"], "app/migrations/0001.sql", True),
        (["*.py"], "src/deep/x.py", True),
        (["src/**/*.ts"], "src/a.ts", True),
        (["src/**/*.ts"], "src/x/y/a.ts", True),
        (["src/*.ts"], "src/x/a.ts", False),
        (["package-lock.json"], "web/package-lock.json", True),
    ],
)
def test_glob_match(globs: list[str], path: str, hit: bool) -> None:
    assert e.glob_match(globs, path) is hit


def test_parse_diff_statuses() -> None:
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n x\n-y\n+z\n"
        + e.new_file_diff("new.ts", "one\ntwo\n")
        + "diff --git a/old.sql b/new.sql\nsimilarity index 100%\nrename from old.sql\nrename to new.sql\n"
    )
    files = {f["path"]: f for f in e.parse_diff(diff)}
    assert files["a.py"]["status"] == "modified" and files["a.py"]["added"] == [(2, "z")]
    assert files["new.ts"]["status"] == "added" and [t for _, t in files["new.ts"]["added"]] == ["one", "two"]
    assert files["new.sql"]["status"] == "renamed" and files["new.sql"]["old_path"] == "old.sql"


def _manifest_diff(path: str, context: list[str], added: list[str], removed: list[str] = ()) -> str:  # type: ignore[assignment]
    body = "".join(f" {c}\n" for c in context) + "".join(f"-{r}\n" for r in removed) + "".join(f"+{a}\n" for a in added)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n{body}"


@pytest.mark.parametrize(
    ("path", "context", "added", "removed", "new"),
    [
        ("pyproject.toml", ["[project]", "dependencies = ["], ['    "httpx>=0.27",'], [], ["httpx"]),
        ("pyproject.toml", ["[tool.ruff.lint]", "select = ["], ['    "UP",'], [], []),
        ("pyproject.toml", ["[project]", "dependencies = ["], ['    "httpx>=0.28",'], ['    "httpx>=0.27",'], []),
        ("package.json", ['  "dependencies": {'], ['    "date-fns": "^4.1.0",'], [], ["date-fns"]),
        ("package.json", ['  "scripts": {'], ['    "lint": "eslint ."'], [], []),
        ("requirements.txt", [], ["rich==13.7.1"], [], ["rich"]),
        ("go.mod", ["require ("], ["\tgithub.com/google/uuid v1.6.0"], [], ["github.com/google/uuid"]),
        ("Cargo.toml", ["[dependencies]"], ['anyhow = "1"'], [], ["anyhow"]),
        ("Cargo.toml", ["[package]"], ['edition = "2021"'], [], []),
    ],
)
def test_new_dependencies(path: str, context: list[str], added: list[str], removed: list[str], new: list[str]) -> None:
    run = {"diff": _manifest_diff(path, context, added, removed)}
    assert [n for n, _ in e.new_dependencies_from_diff(run, e.DEFAULT_MANIFESTS)] == new


@pytest.mark.parametrize(
    ("cmd", "names"),
    [
        ("pnpm add -D vitest", ["vitest"]),
        ("npm ci", []),
        ("pip install -r requirements.txt", []),
        ("uv run pip install -q httpx", ["httpx"]),
        ("go get github.com/google/uuid@latest", ["github.com/google/uuid"]),
        ("npm install @scope/pkg@2", ["@scope/pkg"]),
    ],
)
def test_install_packages(cmd: str, names: list[str]) -> None:
    (seg,) = e.segments(cmd)
    assert e.install_packages(seg) == (True, names)


RULES = [
    {
        "id": "pnpm",
        "text": "Use pnpm.",
        "source": {"file": "AGENTS.md", "lines": [3, 3]},
        "checker": {
            "type": "command_forbidden",
            "params": {
                "patterns": ["^npm\\b"],
                "preferred_patterns": ["^pnpm\\b"],
                "manual_edit_paths": ["package-lock.json"],
            },
        },
    },
    {
        "id": "mig",
        "text": "Never edit migrations.",
        "source": {"file": "AGENTS.md", "lines": [4, 4]},
        "checker": {"type": "path_forbidden", "params": {"globs": ["migrations/**"], "existing_only": True}},
    },
    {
        "id": "any",
        "text": "No any.",
        "source": {"file": "AGENTS.md", "lines": [5, 5]},
        "checker": {"type": "content_forbidden_added", "params": {"regex": ":\\s*any\\b", "globs": ["**/*.ts"]}},
    },
    {
        "id": "push",
        "text": "Never push.",
        "source": {"file": "AGENTS.md", "lines": [6, 6]},
        "checker": {"type": "no_push", "params": {}},
    },
    {
        "id": "cc",
        "text": "Conventional Commits.",
        "source": {"file": "AGENTS.md", "lines": [7, 7]},
        "checker": {"type": "commit_message", "params": {"regex": "^(feat|fix|docs|chore)(\\(.+\\))?: \\S"}},
    },
    {
        "id": "deps",
        "text": "No new dependencies.",
        "source": {"file": "AGENTS.md", "lines": [8, 8]},
        "checker": {"type": "dependency_unchanged", "params": {"allow": ["vitest"]}},
    },
    {
        "id": "names",
        "text": "kebab-case files.",
        "source": {"file": "AGENTS.md", "lines": [9, 9]},
        "checker": {"type": "file_naming", "params": {"globs": ["src/**/*.ts"], "pattern": "[a-z0-9-]+\\.ts"}},
    },
]


@pytest.mark.parametrize(
    ("action", "rule_id"),
    [
        ({"kind": "shell", "command": "bash -lc 'npm install zod'"}, "pnpm"),
        ({"kind": "shell", "command": "pnpm add zod"}, "deps"),
        ({"kind": "shell", "command": "pnpm add -D vitest"}, None),
        ({"kind": "shell", "command": "sed -i 's/a/b/' migrations/0001.sql"}, "mig"),
        ({"kind": "write", "path": "migrations/0004_new.sql", "content": "ALTER TABLE x;", "exists": False}, None),
        ({"kind": "edit", "path": "migrations/0001.sql", "old": "a", "new": "b", "exists": True}, "mig"),
        ({"kind": "edit", "path": "src/a.ts", "old": "let x = 1", "new": "let x: any = 1", "exists": True}, "any"),
        ({"kind": "edit", "path": "src/a.ts", "old": "let x: any = 1", "new": "let x = 1", "exists": True}, None),
        ({"kind": "write", "path": "src/ReportBuilder.ts", "content": "export {}", "exists": False}, "names"),
        ({"kind": "shell", "command": "git -C . push origin main"}, "push"),
        ({"kind": "shell", "command": "git commit -m 'Add parser'"}, "cc"),
        ({"kind": "shell", "command": "git commit -m 'feat: add parser'"}, None),
        ({"kind": "edit", "path": "package-lock.json", "old": "a", "new": "b", "exists": True}, "pnpm"),
    ],
)
def test_evaluate_action(action: dict[str, object], rule_id: str | None) -> None:
    decision = e.evaluate_action(RULES, action)
    assert (decision or {}).get("rule_id") == rule_id
    if decision:
        assert decision["reason"].startswith("obey: this breaks the rule") and "AGENTS.md:" in decision["reason"]


def test_transcript_events_mark_hook_denials() -> None:
    transcript = "\n".join(
        [
            '{"message": {"content": [{"type": "tool_use", "id": "a", "name": "Edit", "input": {"file_path": "/r/src/x.py"}}]}}',
            '{"message": {"content": [{"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "make test"}}]}}',
            '{"message": {"content": [{"type": "tool_result", "tool_use_id": "b", "is_error": false, "content": "ok"}]}}',
            '{"message": {"content": [{"type": "tool_use", "id": "c", "name": "Bash", "input": {"command": "npm i"}}]}}',
            '{"message": {"content": [{"type": "tool_result", "tool_use_id": "c", "is_error": true, '
            '"content": "PreToolUse:Bash hook error: denied"}]}}',
        ]
    )
    events = e.events_from_transcript(transcript, "/r")
    assert events[0] == {"type": "edit", "path": "src/x.py", "seq": 0}
    assert events[1]["exit_code"] == 0 and events[2].get("denied") is True
    rule = {"type": "command_required", "params": {"pattern": "^make\\s+test\\b"}}
    assert e.check(rule, {"events": events, "diff": ""})["verdict"] == "obeyed"
