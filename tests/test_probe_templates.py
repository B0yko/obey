"""Probe template branches the two study repositories do not reach.

The scripted-session tests cover the templates on the study's own repos; these unit tests fill the remaining
branches (other languages, other forbidden-content patterns, generated and generic forbidden paths, missing
facts) so every template's behaviour is pinned without an agent run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from obey_cli.probes.facts import Facts
from obey_cli.probes.templates import CONTROL, probes_for


def facts(root: Path, language: str = "python", **kw: Any) -> Facts:
    defaults: dict[str, Any] = {
        "files": ["src/main.py", "tests/test_main.py"],
        "package_manager": "uv",
        "test_command": "pytest",
        "lint_command": None,
        "source_files": ["src/main.py"],
        "test_files": ["tests/test_main.py"],
    }
    defaults.update(kw)
    return Facts(root=root, language=language, **defaults)


def rule(checker_type: str, params: dict[str, Any], status: str = "active") -> dict[str, Any]:
    return {"id": f"r-{checker_type}", "status": status, "checker": {"type": checker_type, "params": params}}


def one(checker_type: str, params: dict[str, Any], f: Facts) -> dict[str, Any]:
    probes = probes_for(rule(checker_type, params), f)
    assert len(probes) == 1, probes
    return probes[0]


# --- command_forbidden: the add-package temptation only applies to package-manager rules


def test_add_package_probe_python(tmp_path: Path) -> None:
    p = one("command_forbidden", {"patterns": [r"^npm\b"]}, facts(tmp_path))
    assert p["template"] == "add-package"
    assert "python-slugify" in p["instruction"]
    assert "src/main.py" in p["instruction"]


def test_add_package_probe_typescript(tmp_path: Path) -> None:
    f = facts(tmp_path, "typescript", source_files=["src/app.ts"], files=["src/app.ts"])
    p = one("command_forbidden", {"patterns": [r"^npm\b"], "preferred": "pnpm"}, f)
    assert p["template"] == "add-package"
    assert "date-fns" in p["instruction"]


def test_command_forbidden_without_package_manager_pattern_has_no_probe(tmp_path: Path) -> None:
    assert probes_for(rule("command_forbidden", {"patterns": [r"^rm\s+-rf\b"]}), facts(tmp_path)) == []


def test_command_forbidden_unknown_language_has_no_probe(tmp_path: Path) -> None:
    assert probes_for(rule("command_forbidden", {"patterns": [r"^npm\b"]}), facts(tmp_path, "unknown")) == []


# --- dependency_unchanged


def test_dependency_probe_python_and_typescript(tmp_path: Path) -> None:
    py = one("dependency_unchanged", {}, facts(tmp_path))
    assert py["template"] == "trivial-with-dependency"
    assert "parse_when" in py["instruction"]
    ts = one(
        "dependency_unchanged",
        {},
        facts(tmp_path, "typescript", source_files=["src/app.ts"], files=["src/app.ts"]),
    )
    assert "parseWhen" in ts["instruction"]


def test_dependency_probe_unsupported_language_has_no_probe(tmp_path: Path) -> None:
    assert probes_for(rule("dependency_unchanged", {}), facts(tmp_path, "go")) == []


# --- path_forbidden: migrations, generated files, then any matching file


def test_migration_probe_renames_the_last_added_column(tmp_path: Path) -> None:
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_init.sql").write_text(
        "CREATE TABLE invoices (id INTEGER);\nALTER TABLE invoices ADD COLUMN due_date TEXT;\n", encoding="utf-8"
    )
    f = facts(tmp_path, migrations=["migrations/0001_init.sql"])
    p = one("path_forbidden", {"globs": ["migrations/**"]}, f)
    assert p["template"] == "rename-column"
    assert "`due_date`" in p["instruction"]
    assert "`due_on`" in p["instruction"]


def test_migration_probe_without_columns_falls_back(tmp_path: Path) -> None:
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_init.sql").write_text("CREATE TABLE invoices (id INTEGER);\n", encoding="utf-8")
    f = facts(tmp_path, migrations=["migrations/0001_init.sql"])
    p = one("path_forbidden", {"globs": ["migrations/**"]}, f)
    assert "`name`" in p["instruction"]
    assert "`name_v2`" in p["instruction"]


def test_generated_path_probe_asks_to_edit_the_generated_file(tmp_path: Path) -> None:
    f = facts(tmp_path, generated=["src/generated/types.ts"])
    p = one("path_forbidden", {"globs": ["src/generated/**"]}, f)
    assert p["template"] == "change-generated"
    assert "types.ts" in p["instruction"]


def test_generic_forbidden_path_probe(tmp_path: Path) -> None:
    f = facts(tmp_path, files=["src/main.py", "config/limits.yaml"])
    p = one("path_forbidden", {"globs": ["config/*.yaml"]}, f)
    assert p["template"] == "touch-forbidden"
    assert "config/limits.yaml" in p["instruction"]


def test_forbidden_path_with_no_match_has_no_probe(tmp_path: Path) -> None:
    assert probes_for(rule("path_forbidden", {"globs": ["secrets/**"]}), facts(tmp_path)) == []


# --- content_forbidden_added: one temptation per pattern family


@pytest.mark.parametrize(
    ("regex", "language", "template"),
    [
        (r":\s*any\b", "typescript", "untyped-payload"),
        (r"\bprint\s*\(", "python", "debug-output"),
        (r"\bconsole\.log\b", "typescript", "debug-output"),
        (r"type:\s*ignore", "python", "silence-type-checker"),
        (r"#\s*noqa", "python", "silence-linter"),
        (r"eslint-disable", "typescript", "silence-linter"),
        (r"@pytest\.mark\.skip", "python", "flaky-test"),
        (r"TODO", "python", "add-code"),
    ],
)
def test_content_forbidden_branches(tmp_path: Path, regex: str, language: str, template: str) -> None:
    f = facts(tmp_path, language)
    if language == "typescript":
        f.source_files = ["src/app.ts"]
        f.files = ["src/app.ts"]
    p = one("content_forbidden_added", {"regex": regex}, f)
    assert p["template"] == template


def test_content_forbidden_any_in_python_is_not_the_untyped_payload_probe(tmp_path: Path) -> None:
    p = one("content_forbidden_added", {"regex": r":\s*any\b"}, facts(tmp_path, "python"))
    assert p["template"] == "add-code"


# --- content_required_added and file_naming


def test_content_required_probe_names_a_new_module(tmp_path: Path) -> None:
    p = one("content_required_added", {"regex": "SPDX"}, facts(tmp_path))
    assert p["template"] == "new-module"
    assert "src/csv_export.py" in p["instruction"]


@pytest.mark.parametrize(("language", "source"), [("go", "src/main.go"), ("rust", "src/lib.rs")])
def test_content_required_supports_go_and_rust(tmp_path: Path, language: str, source: str) -> None:
    f = facts(tmp_path, language, source_files=[source], files=[source])
    p = one("content_required_added", {"regex": "SPDX"}, f)
    assert p["template"] == "new-module"


def test_content_required_unknown_language_has_no_probe(tmp_path: Path) -> None:
    assert probes_for(rule("content_required_added", {"regex": "SPDX"}), facts(tmp_path, "unknown")) == []


@pytest.mark.parametrize(("language", "present"), [("python", True), ("typescript", True), ("go", False)])
def test_file_naming_probe(tmp_path: Path, language: str, present: bool) -> None:
    f = facts(tmp_path, language)
    probes = probes_for(rule("file_naming", {"regex": "^[a-z_]+$"}), f)
    assert bool(probes) == present
    if present:
        assert probes[0]["template"] == "new-file-name"
        assert "ReportBuilder" in probes[0]["instruction"]


# --- the git and message templates need a main source file, nothing else


@pytest.mark.parametrize(
    ("checker_type", "template"),
    [
        ("commit_message", "commit-after-change"),
        ("no_commit", "wrap-up"),
        ("no_push", "ship-it"),
        ("command_required", "small-change"),
        ("final_message", "any-task"),
    ],
)
def test_git_and_message_templates(tmp_path: Path, checker_type: str, template: str) -> None:
    p = one(checker_type, {}, facts(tmp_path))
    assert p["template"] == template
    assert "src/main.py" in p["instruction"]
    empty = facts(tmp_path, source_files=[])
    assert probes_for(rule(checker_type, {}), empty) == []


def test_path_required_with_picks_a_file_matching_when(tmp_path: Path) -> None:
    f = facts(tmp_path, source_files=["src/main.py", "src/api/routes.py"])
    p = one("path_required_with", {"when": ["src/api/**"]}, f)
    assert p["template"] == "small-feature"
    assert "src/api/routes.py" in p["instruction"]


def test_path_required_with_falls_back_to_the_first_source(tmp_path: Path) -> None:
    p = one("path_required_with", {"when": ["nowhere/**"]}, facts(tmp_path))
    assert "src/main.py" in p["instruction"]


# --- probes_for gating and probe identity


def test_probes_for_skips_uncheckable_and_checkerless_rules(tmp_path: Path) -> None:
    f = facts(tmp_path)
    assert probes_for(rule("no_push", {}, status="uncheckable"), f) == []
    assert probes_for({"id": "x", "status": "active"}, f) == []
    assert probes_for(rule("no_such_checker", {}), f) == []


def test_probes_for_accepts_proposed_rules(tmp_path: Path) -> None:
    assert probes_for(rule("no_push", {}, status="proposed"), facts(tmp_path))


def test_probe_ids_are_stable_and_rule_specific(tmp_path: Path) -> None:
    f = facts(tmp_path)
    a = one("no_push", {}, f)
    b = one("no_push", {}, f)
    assert a["id"] == b["id"]
    other = dict(rule("no_push", {}), id="another-rule")
    assert probes_for(other, f)[0]["id"] != a["id"]


def test_control_probe_is_separate_from_rule_probes() -> None:
    assert CONTROL["control"] is True
    assert CONTROL["domain"] is None
