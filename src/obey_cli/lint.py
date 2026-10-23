"""obey lint: checks that need no agent runs, for CI.

1. obey.yaml is valid, and every active rule has a checker (rules that need judgement are `uncheckable`).
2. The instruction files are unchanged since obey.yaml was written (a hash mismatch means "re-extract").
3. Generated enforcement files match what `obey enforce` would write for the rules they were compiled from.
4. The badge JSON is present (lint writes it).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from obey_cli import config as cfg


@dataclass
class LintResult:
    ok: bool = True
    lines: list[str] = field(default_factory=list)

    def good(self, text: str) -> None:
        self.lines.append(f"ok    {text}")

    def bad(self, text: str) -> None:
        self.ok = False
        self.lines.append(f"FAIL  {text}")

    def note(self, text: str) -> None:
        self.lines.append(f"note  {text}")


def lint(root: Path, config_name: str = cfg.CONFIG_NAME, write_badge: bool = True) -> LintResult:
    from obey_cli.discover import discover
    from obey_cli.enforce import in_sync, installed_targets
    from obey_cli.report import badge

    res = LintResult()
    try:
        config = cfg.load(root / config_name)
    except cfg.ConfigError as exc:
        res.bad(str(exc))
        return res
    rules = config["rules"]
    active = [r for r in rules if r["status"] == "active"]
    res.good(
        f"{config_name} is valid: {len(rules)} rules, {len(active)} active, "
        f"{sum(r['status'] == 'uncheckable' for r in rules)} uncheckable"
    )
    missing = [r["id"] for r in active if not r.get("checker")]
    if missing:
        res.bad(f"active rules without a checker: {', '.join(missing)} (add one or mark them uncheckable)")
    proposed = [r["id"] for r in rules if r["status"] == "proposed"]
    if proposed:
        res.note(f"{len(proposed)} proposed rule(s) wait for review: set status active or disabled")
    no_probe = [r["id"] for r in active if not r.get("probes")]
    if no_probe:
        res.note(f"{len(no_probe)} active rule(s) have no probe yet (obey probe)")

    recorded = {s["file"]: s["sha256"] for s in config.get("sources") or []}
    current = {f.path: f.sha256 for f in discover(root)}
    changed = sorted(p for p in recorded if p in current and current[p] != recorded[p])
    gone = sorted(p for p in recorded if p not in current)
    new = sorted(p for p in current if p not in recorded)
    if changed or gone or new:
        detail = "; ".join(
            x
            for x in (
                f"changed: {', '.join(changed)}" if changed else "",
                f"removed: {', '.join(gone)}" if gone else "",
                f"new: {', '.join(new)}" if new else "",
            )
            if x
        )
        res.bad(f"instruction files differ from {config_name} ({detail}); run `obey extract`")
    else:
        res.good(f"{len(current)} instruction file(s) match {config_name}")

    targets = installed_targets(root)
    compiled_path = root / ".obey" / "hooks" / "rules.json"
    if targets:
        if not compiled_path.exists():
            res.bad("enforcement files exist but .obey/hooks/rules.json is missing; run `obey enforce`")
        else:
            compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
            by_id = {r["id"]: r for r in rules}
            stale = [
                r["id"]
                for r in compiled["rules"]
                if r["id"] not in by_id
                or by_id[r["id"]].get("status") != "active"
                or by_id[r["id"]].get("checker") != r["checker"]
            ]
            if stale:
                res.bad(f"enforced rules no longer match {config_name}: {', '.join(stale)}; run `obey enforce`")
            else:
                current_rules = [by_id[r["id"]] for r in compiled["rules"]]
                drift = in_sync(root, current_rules, targets)
                if drift:
                    res.bad(f"enforcement files out of date: {', '.join(drift)}; run `obey enforce`")
                else:
                    res.good(f"enforcement in sync for {', '.join(targets)} ({len(compiled['rules'])} rule(s))")
    else:
        res.note("no enforcement installed (obey enforce)")

    badge_path = root / "obey-badge.json"
    if write_badge:
        report_path = root / ".obey" / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        data = badge(report, rules_total=len(active))
        text = json.dumps(data) + "\n"
        if not badge_path.exists() or badge_path.read_text(encoding="utf-8") != text:
            badge_path.write_text(text, encoding="utf-8")
        res.good(f"badge written to obey-badge.json ({data['message']})")
    elif badge_path.exists():
        res.good("obey-badge.json present")
    else:
        res.bad("obey-badge.json missing (run `obey lint` without --no-badge, or `obey run`)")
    return res


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
