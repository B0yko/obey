from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from obey_cli.discover import discover
from obey_cli.extract import extract


def rules_for(tmp_path: Path, text: str, name: str = "AGENTS.md") -> list[dict[str, Any]]:
    (tmp_path / name).write_text(text)
    return [x.as_rule() for x in extract(discover(tmp_path))]


@pytest.mark.parametrize(
    ("text", "ctype"),
    [
        ("- Use pnpm for every package command; never run `npm` or `yarn`.", "command_forbidden"),
        ("- Use `uv add` instead of `pip install` when you need a package.", "command_forbidden"),
        ("- Never run `git push`.", "no_push"),
        ("- Do not commit unless asked.", "no_commit"),
        ("- Commit messages must follow Conventional Commits.", "commit_message"),
        ("- Never edit files under `vendor/`; run `go mod vendor` instead.", "path_forbidden"),
        ("- Merged migrations should not be edited.", "path_forbidden"),
        ("- When you change `src/app/`, add or update a test under `tests/`.", "path_required_with"),
        ("- Do not add packages without approval.", "dependency_unchanged"),
        ("- Never use the `any` type.", "content_forbidden_added"),
        ("- No `print()` in `src/`; use logging.", "content_forbidden_added"),
        ("- Every new Python file starts with `# SPDX-License-Identifier: Apache-2.0`.", "content_required_added"),
        ("- Run `uv run pytest` before finishing.", "command_required"),
        ("- Name modules in snake_case.", "file_naming"),
        ("- End your final message with a line starting `Summary:`.", "final_message"),
    ],
)
def test_families(tmp_path: Path, text: str, ctype: str) -> None:
    (rule,) = rules_for(tmp_path, f"# Rules\n\n{text}\n")
    assert rule["status"] == "active"
    assert rule["checker"]["type"] == ctype


def test_taste_and_prose(tmp_path: Path) -> None:
    rules = rules_for(tmp_path, "# App\n\nComponents live in `src/components/`.\n\n- Write clean, readable code.\n")
    assert [(r["status"], r["checker"]) for r in rules] == [("uncheckable", None)]
    assert "judgement" in rules[0]["reason"]


def test_params_and_ids(tmp_path: Path) -> None:
    (pnpm, mig) = rules_for(tmp_path, "- Use pnpm; never npm.\n- Do not modify existing files in `db/migrations/`.\n")
    assert pnpm["checker"]["params"]["preferred"] == "pnpm"
    assert any(p.startswith("^npm") for p in pnpm["checker"]["params"]["patterns"])
    assert "package-lock.json" in pnpm["checker"]["params"]["manual_edit_paths"]
    assert mig["checker"]["params"] == {"globs": ["db/migrations/**"], "existing_only": True}
    assert pnpm["id"] != mig["id"] and pnpm["source"] == {"file": "AGENTS.md", "lines": [1, 1]}


def test_dont_heading_flips_bare_bullets(tmp_path: Path) -> None:
    (rule,) = rules_for(tmp_path, "## Don't\n\n- Use `console.log` in `src/`.\n")
    assert rule["checker"]["type"] == "content_forbidden_added"
    assert rule["checker"]["params"]["globs"][0].startswith("src/")


def test_scope_from_nested_file(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    (rule,) = rules_for(tmp_path, "- Never push.\n", name="web/AGENTS.md")
    assert rule["scope"]["paths"] == ["web/**"]


def test_llm_proposal_replaces_its_uncheckable_rule(tmp_path: Path) -> None:
    from obey_cli.extract import Extracted
    from obey_cli.rules import build_config

    (tmp_path / "AGENTS.md").write_text("- Keep message text in templates/, not in Go files.\n- Never push.\n")
    files = discover(tmp_path)
    (uncheckable,) = [x for x in extract(files) if x.status == "uncheckable"]
    proposal = Extracted(
        candidate=uncheckable.candidate,
        file=uncheckable.file,
        status="proposed",
        origin="llm",
        checker={"type": "content_forbidden_added", "params": {"regex": '"[^"]+ [^"]+"', "globs": ["**/*.go"]}},
        reason="proposed by --llm",
    )
    config, _ = build_config(tmp_path, proposals=[proposal])
    statuses = sorted(r["status"] for r in config["rules"])
    assert statuses == ["active", "proposed"]
