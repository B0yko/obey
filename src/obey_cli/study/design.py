"""The phrasing experiment's design: rendering AGENTS.md per condition, and the rule each run is scored against."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PHRASINGS = ("imperative", "prohibition", "reason")


@dataclass(frozen=True)
class Cell:
    repo: str
    slot: str
    condition: str  # baseline | imperative | prohibition | reason
    harness: str


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _one_line(text: str) -> str:
    return " ".join(text.split())


def render(repo: dict[str, Any], slot: str | None, condition: str) -> tuple[str, int | None]:
    """AGENTS.md for one run, and the 1-based line of the slot under test (None for the baseline).

    The slot under test takes `condition`'s phrasing (or is left out for `baseline`); every other slot uses its
    imperative phrasing; distractors never change.
    """
    lines = [*repo["header"].rstrip("\n").split("\n"), ""]
    target_line = None
    for key in repo["order"]:
        if key in repo["distractors"]:
            lines.append(f"- {_one_line(repo['distractors'][key])}")
            continue
        spec = repo["slots"][key]
        if key == slot:
            if condition == "baseline":
                continue
            lines.append(f"- {_one_line(spec[condition])}")
            target_line = len(lines)
        else:
            lines.append(f"- {_one_line(spec['imperative'])}")
    return "\n".join(lines) + "\n", target_line


def rule(design: dict[str, Any], repo_name: str, slot: str, condition: str) -> dict[str, Any]:
    repo = design["repos"][repo_name]
    spec = repo["slots"][slot]
    _, line = render(repo, slot, condition if condition != "baseline" else "imperative")
    text = _one_line(spec["imperative" if condition == "baseline" else condition])
    return {
        "id": f"{repo_name}--{slot}",
        "text": text,
        "source": {"file": "AGENTS.md", "lines": [line or 1, line or 1]},
        "scope": {"paths": ["**"], "agents": None},
        "checker": spec["checker"],
        "status": "active",
        "reason": None,
        "origin": "user",
        "probes": [
            {
                "id": f"{repo_name}--{slot}",
                "template": "study",
                "instruction": _one_line(spec["probe"]),
                "setup_patch": None,
                "domain": slot,
            }
        ],
    }


def cells(
    design: dict[str, Any],
    *,
    repos: list[str] | None = None,
    slots: list[str] | None = None,
    conditions: list[str] | None = None,
    harnesses: list[str] | None = None,
) -> list[Cell]:
    out = []
    for repo_name, repo in design["repos"].items():
        if repos and repo_name not in repos:
            continue
        for slot in repo["slots"]:
            if slots and slot not in slots:
                continue
            for condition in conditions or design["conditions"]:
                for harness in harnesses or design["harnesses"]:
                    out.append(Cell(repo_name, slot, condition, harness))
    return out
