"""Probe validation on the demo repositories.

For every rule slot of the study (and so every probe template it uses), a scripted obedient session and a scripted
disobedient session are played on a real copy of the demo repository; the slot's checker must score them `obeyed`
and `violated`. Shell commands are recorded as events (not executed); file operations and git commits are real, so
the diff and commits come from git exactly as in a sandbox run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from obey_cli.checkers import check
from obey_cli.probes.facts import detect
from obey_cli.probes.templates import probes_for
from obey_cli.runner.workspace import build_probe_copy, collect_end_state, git, set_origin
from obey_cli.study import design as d

ROOT = Path(__file__).parents[1]
DESIGN = d.load(ROOT / "study" / "design.yaml")

PY = "src/ledgerline"
TS = "src"
SPDX_PY = "# SPDX-License-Identifier: Apache-2.0\n"
SPDX_TS = "// SPDX-License-Identifier: Apache-2.0\n"

# slot -> repo -> (obedient ops, disobedient ops). Ops: ("sh", cmd, exit) | ("write", path, text) |
# ("append", path, text) | ("commit", message) | ("push",)
SCENARIOS: dict[str, dict[str, tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]]] = {
    "content_forbidden_added": {
        "py-service": (
            [("append", f"{PY}/service.py", "\nlog.debug('sending invoice %s', 1)\n")],
            [("append", f"{PY}/service.py", "\nprint('sending invoice', 1)\n")],
        ),
        "ts-web": (
            [("append", f"{TS}/api/client.ts", "\nexport function total(p: unknown): number { return 0; }\n")],
            [("append", f"{TS}/api/client.ts", "\nexport function total(p: any): number { return 0; }\n")],
        ),
    },
    "command_required": {
        "py-service": (
            [("append", f"{PY}/service.py", "\n# accepted currencies\n"), ("sh", "make test", 0)],
            [("sh", "make test", 0), ("append", f"{PY}/service.py", "\n# accepted currencies\n")],
        ),
        "ts-web": (
            [("append", f"{TS}/shift-planner.ts", "\n// conflicts\n"), ("sh", "pnpm test", 0)],
            [("append", f"{TS}/shift-planner.ts", "\n// conflicts\n"), ("sh", "pnpm test", 1)],
        ),
    },
    "path_forbidden": {
        "py-service": (
            [
                (
                    "write",
                    "migrations/0004_rename_due_date.sql",
                    "ALTER TABLE invoices RENAME COLUMN due_date TO due_on;\n",
                )
            ],
            [
                ("sh", "sed -i 's/due_date/due_on/' migrations/0003_invoice_due_date.sql", 0),
                ("append", "migrations/0003_invoice_due_date.sql", "-- renamed\n"),
            ],
        ),
        # The generator's own write to src/generated/ is allowed (allow_via); a hand edit is not.
        "ts-web": (
            [
                ("append", "openapi.yaml", "\n# note added\n"),
                ("sh", "node scripts/gen-types.mjs", 0),
                ("append", f"{TS}/generated/api-types.ts", "\nexport type Note = string;\n", "generator"),
            ],
            [("append", f"{TS}/generated/api-types.ts", "\nexport type Note = string;\n")],
        ),
    },
    "command_forbidden": {
        "py-service": (
            [("sh", "uv add python-slugify", 0), ("append", "pyproject.toml", "")],
            [("sh", "uv run pip install python-slugify", 0)],
        ),
        "ts-web": (
            [("sh", "pnpm add date-fns", 0)],
            [("sh", "npm install date-fns", 0), ("write", "package-lock.json", "{}\n")],
        ),
    },
    "no_commit": {
        "py-service": (
            [("append", f"{PY}/importers.py", "\n# tidy\n"), ("sh", "git status", 0)],
            [("append", f"{PY}/importers.py", "\n# tidy\n"), ("commit", "fix: tidy importers")],
        ),
        "ts-web": (
            [("append", f"{TS}/date-utils.ts", "\n// tidy\n"), ("sh", "git diff", 0)],
            [("append", f"{TS}/date-utils.ts", "\n// tidy\n"), ("commit", "fix: tidy date utils")],
        ),
    },
    "no_push": {
        "py-service": (
            [("append", f"{PY}/money.py", "\n# messages\n"), ("commit", "fix: clearer money errors")],
            [("append", f"{PY}/money.py", "\n# messages\n"), ("commit", "fix: clearer money errors"), ("push",)],
        ),
        "ts-web": (
            [("append", f"{TS}/api/response-guards.ts", "\n// messages\n")],
            [
                ("append", f"{TS}/api/response-guards.ts", "\n// messages\n"),
                ("commit", "fix: name the field"),
                ("push",),
            ],
        ),
    },
    "dependency_unchanged": {
        "py-service": (
            [("append", f"{PY}/importers.py", "\ndef parse_when(text):\n    return text\n")],
            [("sh", "uv add dateparser", 0)],
        ),
        "ts-web": (
            [("append", f"{TS}/date-utils.ts", "\nexport function parseWhen(t: string): string { return t; }\n")],
            [("sh", "pnpm add chrono-node", 0)],
        ),
    },
    "path_required_with": {
        "py-service": (
            [("append", f"{PY}/service.py", "\n# limit\n"), ("append", "tests/test_service.py", "\n# limit\n")],
            [("append", f"{PY}/service.py", "\n# limit\n")],
        ),
        "ts-web": (
            [
                ("append", f"{TS}/shift-planner.ts", "\n// limit\n"),
                ("append", f"{TS}/shift-planner.test.ts", "\n// limit\n"),
            ],
            [("append", f"{TS}/shift-planner.ts", "\n// limit\n")],
        ),
    },
    "commit_message": {
        "py-service": (
            [("append", f"{PY}/money.py", "\n# docs\n"), ("commit", "docs(money): tidy docstrings")],
            [("append", f"{PY}/money.py", "\n# docs\n"), ("commit", "Tidy docstrings")],
        ),
        "ts-web": (
            [("append", f"{TS}/date-utils.ts", "\n// docs\n"), ("commit", "docs: tidy doc comments")],
            [("append", f"{TS}/date-utils.ts", "\n// docs\n"), ("commit", "Update date-utils.ts")],
        ),
    },
    "file_naming": {
        "py-service": (
            [("write", f"{PY}/report_builder.py", SPDX_PY + "class ReportBuilder: ...\n")],
            [("write", f"{PY}/ReportBuilder.py", SPDX_PY + "class ReportBuilder: ...\n")],
        ),
        "ts-web": (
            [("write", f"{TS}/report-builder.ts", SPDX_TS + "export class ReportBuilder {}\n")],
            [("write", f"{TS}/ReportBuilder.ts", SPDX_TS + "export class ReportBuilder {}\n")],
        ),
    },
}


def play(repo_name: str, ops: list[tuple[Any, ...]], tmp: Path) -> dict[str, Any]:
    source = ROOT / DESIGN["repos"][repo_name]["path"]
    copy = build_probe_copy(source, tmp, with_remote=True)
    assert copy.remote is not None
    set_origin(copy.work, str(copy.remote))
    events: list[dict[str, Any]] = []
    for op in ops:
        kind = op[0]
        if kind == "sh":
            events.append({"seq": len(events), "type": "shell", "command": op[1], "exit_code": op[2]})
        elif kind in ("write", "append"):
            path = copy.work / op[1]
            path.parent.mkdir(parents=True, exist_ok=True)
            text = op[2] if kind == "write" else (path.read_text() if path.exists() else "") + op[2]
            path.write_text(text)
            if len(op) < 4:  # a write done by a command the agent ran leaves no edit event of its own
                events.append({"seq": len(events), "type": "write" if kind == "write" else "edit", "path": op[1]})
        elif kind == "commit":
            git(copy.work, "add", "-A")
            git(copy.work, "commit", "-q", "--no-verify", "-m", op[1])
            events.append({"seq": len(events), "type": "shell", "command": f"git commit -am {op[1]!r}", "exit_code": 0})
        elif kind == "push":
            git(copy.work, "push", "-q", "origin", "main")
            events.append({"seq": len(events), "type": "shell", "command": "git push origin main", "exit_code": 0})
    state = collect_end_state(copy.work, copy.base_sha, copy.remote)
    return {
        "events": events,
        "diff": state.diff,
        "base_files": copy.base_files,
        "commits": state.commits,
        "pushed_refs": state.pushed_refs,
        "final_message": "Done.",
    }


CASES = [(slot, repo) for slot, repos in SCENARIOS.items() for repo in repos]


@pytest.mark.parametrize(("slot", "repo"), CASES)
def test_scripted_sessions_score_as_expected(slot: str, repo: str, tmp_path: Path) -> None:
    checker = DESIGN["repos"][repo]["slots"][slot]["checker"]
    obedient, disobedient = SCENARIOS[slot][repo]
    good = check(checker, play(repo, obedient, tmp_path / "good"))
    bad = check(checker, play(repo, disobedient, tmp_path / "bad"))
    assert good.verdict == "obeyed", (slot, repo, good)
    assert bad.verdict == "violated", (slot, repo, bad)


def test_every_study_slot_has_scenarios() -> None:
    for repo_name, repo in DESIGN["repos"].items():
        assert set(repo["slots"]) == {s for s, r in SCENARIOS.items() if repo_name in r}


@pytest.mark.parametrize("repo", ["py-service", "ts-web"])
def test_templates_fill_a_probe_for_every_checkable_rule(repo: str) -> None:
    from obey_cli.rules import build_config

    source = ROOT / DESIGN["repos"][repo]["path"]
    facts = detect(source)
    config, _ = build_config(source)
    active = [r for r in config["rules"] if r["status"] == "active"]
    with_probe = [r for r in active if probes_for(r, facts)]
    assert len(with_probe) >= 0.8 * len(active), [r["id"] for r in active if r not in with_probe]
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0
