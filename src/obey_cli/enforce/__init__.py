"""Compile rules into hooks for each agent plus an agent-agnostic pre-commit check."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from obey_cli import __version__
from obey_cli.enforce.merge import Plan
from obey_cli.enforce.targets import EDIT_TYPES, SHELL_TYPES, STOP_TYPES, TARGETS

HOOK_DIR = ".obey/hooks"
TEMPLATES = Path(__file__).parent / "templates"
ENGINE = Path(__file__).parent / "engine" / "obey_engine.py"
MECHANICAL = SHELL_TYPES | EDIT_TYPES | STOP_TYPES
GITIGNORE = "backup/\nledger.jsonl\nruns/\nreport.*\n"


def compiled(rules: Sequence[dict[str, Any]]) -> dict[str, Any]:
    body = [{"id": r["id"], "text": r["text"], "source": r["source"], "checker": r["checker"]} for r in rules]
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {"obey_version": __version__, "rules_sha256": digest, "rules": body}


def select(
    config: dict[str, Any],
    *,
    report: dict[str, Any] | None = None,
    ids: Iterable[str] | None = None,
    threshold: float = 1.0,
) -> list[dict[str, Any]]:
    """Active rules with a mechanical checker; with a report, only those broken in some exercised run."""
    active = [
        r
        for r in config.get("rules", [])
        if r.get("status") == "active" and r.get("checker") and r["checker"]["type"] in MECHANICAL
    ]
    if ids is not None:
        wanted = set(ids)
        return [r for r in active if r["id"] in wanted]
    if report is None:
        return active
    broken = {
        s["rule_id"]
        for s in report.get("scores", [])
        if s.get("arm") == "rule" and s.get("compliance") is not None and s["compliance"] < threshold
    }
    return [r for r in active if r["id"] in broken]


def advisory(rules: Sequence[dict[str, Any]], targets: Sequence[str]) -> list[dict[str, str]]:
    """Rules a target cannot enforce mechanically (listed as advisory only)."""
    out = []
    for r in rules:
        kind = r["checker"]["type"]
        for name in targets:
            t = TARGETS[name]
            stop_only = kind in STOP_TYPES and kind not in (SHELL_TYPES | EDIT_TYPES)
            if (stop_only and not t.stop and name != "precommit") or (
                name == "precommit" and kind in ("command_required", "final_message", "no_push", "no_commit")
            ):
                out.append({"rule_id": r["id"], "target": name, "reason": f"{t.display} cannot block {kind}"})
    return out


def plan_enforce(root: Path, rules: Sequence[dict[str, Any]], targets: Sequence[str]) -> Plan:
    plan = Plan(root)
    plan.put(f"{HOOK_DIR}/obey_hook.py", (TEMPLATES / "obey_hook.py").read_text(encoding="utf-8"))
    plan.put(f"{HOOK_DIR}/obey_engine.py", ENGINE.read_text(encoding="utf-8"))
    plan.put(f"{HOOK_DIR}/rules.json", json.dumps(compiled(rules), indent=2) + "\n")
    plan.put(".obey/.gitignore", GITIGNORE)
    if "precommit" in targets:
        plan.put(".obey/pre-commit", (TEMPLATES / "pre_commit.py").read_text(encoding="utf-8"))
    elif (root / ".obey/pre-commit").exists():
        plan.put(".obey/pre-commit", None)
    for name in targets:
        TARGETS[name].write(plan, rules)
    for name, target in TARGETS.items():
        if name not in targets:
            target.remove(plan)
    return plan


def plan_remove(root: Path) -> Plan:
    plan = Plan(root)
    for target in TARGETS.values():
        target.remove(plan)
    for rel in (f"{HOOK_DIR}/obey_hook.py", f"{HOOK_DIR}/obey_engine.py", f"{HOOK_DIR}/rules.json", ".obey/pre-commit"):
        if (root / rel).exists():
            plan.put(rel, None)
    return plan


def in_sync(root: Path, rules: Sequence[dict[str, Any]], targets: Sequence[str]) -> list[str]:
    """Files whose content differs from what `obey enforce` would write now (empty when in sync)."""
    plan = plan_enforce(root, rules, targets)
    return sorted(plan.changes)


def installed_targets(root: Path) -> list[str]:
    found = []
    for name, target in TARGETS.items():
        for rel in target.files:
            path = root / rel
            if path.exists() and ".obey/hooks/obey_hook.py" in path.read_text(encoding="utf-8", errors="replace"):
                found.append(name)
                break
            if name == "precommit" and path.exists():
                found.append(name)
                break
    return found
