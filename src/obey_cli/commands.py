"""Implementations of the obey subcommands (argument parsing lives in cli.py)."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from obey_cli import config as cfg

DEFAULT_IMAGE = "obey-sandbox:0.1.0"


def out(text: str) -> None:
    print(text, flush=True)


def err(text: str) -> None:
    print(f"obey: {text}", file=sys.stderr, flush=True)


def _root(args: argparse.Namespace) -> Path:
    return Path(args.repo).resolve()


def _load(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    root = _root(args)
    return root, cfg.load(root / args.config)


# --------------------------------------------------------------------------------------------- probe


def cmd_probe(args: argparse.Namespace) -> int:
    from obey_cli.probes.facts import detect
    from obey_cli.probes.templates import probes_for

    root, config = _load(args)
    facts = detect(root)
    added = 0
    for rule in config["rules"]:
        if rule.get("probes") and not args.regenerate:
            continue
        probes = probes_for(rule, facts)
        if probes:
            rule["probes"] = probes
            added += 1
    cfg.save(root / args.config, config)
    active = [r for r in config["rules"] if r["status"] == "active"]
    with_probes = [r for r in active if r.get("probes")]
    out(
        f"probes for {len(with_probes)} of {len(active)} active rules ({added} new); language {facts.language}, "
        f"package manager {facts.package_manager or 'unknown'}, test command {facts.test_command or 'unknown'}"
    )
    for r in active:
        if not r.get("probes"):
            out(f"  no template fits: {r['id']} ({r['checker']['type']}); add a probe by hand in {args.config}")
    return 0


# --------------------------------------------------------------------------------------------- run


def _key() -> str:
    return os.environ.get("OBEY_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""


def _rule_scores_from_report(report: dict[str, Any]) -> list[Any]:
    from obey_cli.score import RuleScore

    fields = RuleScore.__dataclass_fields__
    return [RuleScore(**{k: v for k, v in s.items() if k in fields}) for s in report.get("scores", [])]


def _enforcement_files(rules: list[dict[str, Any]], targets: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Contents of the enforcement files obey would write for `rules`, plus git hook shims."""
    from obey_cli.enforce import plan_enforce

    with tempfile.TemporaryDirectory() as tmp:
        plan = plan_enforce(Path(tmp), rules, targets)
        files = {rel: after for rel, (_, after) in plan.changes.items() if after is not None}
    hooks = {}
    if "precommit" in targets:
        shim = '#!/bin/sh\nexec python3 "$(git rev-parse --show-toplevel)/.obey/pre-commit" "$@"\n'
        hooks = {"pre-commit": shim, "commit-msg": shim}
    return files, hooks


def cmd_run(args: argparse.Namespace) -> int:
    from obey_cli.report import badge, build_report
    from obey_cli.runner import agents
    from obey_cli.runner.core import RunSpec, execute
    from obey_cli.runner.ledger import Ledger
    from obey_cli.runner.orchestrate import estimate, execute_all, model_price, outcomes, plan_runs
    from obey_cli.score import score_outcomes

    root, config = _load(args)
    agent_cfg = (config.get("agents") or [{}])[0]
    agent_name = args.agent or agent_cfg.get("agent") or "claude-code"
    model = args.model or agent_cfg.get("model")
    if not model:
        err(
            "choose a model with --model (an OpenRouter model id such as anthropic/claude-haiku-5.5) "
            "or set agents: [{agent, model}] in obey.yaml"
        )
        return 2
    adapter = agents.get(agent_name)
    rules = [r for r in config["rules"] if r["status"] == "active" and r.get("probes")]
    if args.rules:
        wanted = set(args.rules.split(","))
        rules = [r for r in rules if r["id"] in wanted]
    if args.unsafe_local:
        refused = [r for r in rules if r["checker"]["type"] in ("no_commit", "no_push")]
        rules = [r for r in rules if r not in refused]
        for r in refused:
            err(f"--unsafe-local refuses {r['checker']['type']} probes: skipping {r['id']}")
    if not rules:
        err("no active rules with probes; run `obey extract` and `obey probe` first")
        return 1
    before = None
    enforced_files: dict[str, str] | None = None
    git_hooks: dict[str, str] = {}
    if args.compare:
        from obey_cli.enforce import select

        before = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        broken = select(config, report=before)
        rules = [r for r in rules if r["id"] in {b["id"] for b in broken}]
        if not rules:
            out("Nothing to compare: no rule was broken in the BEFORE report.")
            return 0
        enforced_files, git_hooks = _enforcement_files(broken, args.targets.split(","))
    planned = plan_runs(
        root,
        rules,
        trials=args.trials,
        baseline_trials=0 if args.no_baseline or args.compare else args.baseline_trials,
        enforced=enforced_files,
        enforced_hooks=git_hooks,
        only_enforced=bool(args.compare),
    )
    price = model_price(model) if not args.offline_price else {}
    est = estimate(planned, agent_name, price)
    out(f"{est['runs']} runs × ~${est['per_run_usd']:.4f} ≈ ${est['total_usd']:.2f} ({est['source']}; model {model})")
    if args.estimate:
        return 0
    key = _key()
    if not key:
        err("set OPENROUTER_API_KEY (or OBEY_API_KEY) to run agents; the key stays outside the sandbox")
        return 2
    ledger = Ledger(root / ".obey" / "ledger.jsonl", budget_usd=args.budget)
    if args.unsafe_local:
        from obey_cli.runner.local import WARNING, LocalSandbox

        err(WARNING)
        box: Any = LocalSandbox()
    else:
        from obey_cli.runner.sandbox import DockerSandbox, docker_available

        if not docker_available():
            err("Docker is not available. Start Docker (or colima), or use --unsafe-local (read the README first).")
            return 2
        image = args.image or (config.get("sandbox") or {}).get("image") or DEFAULT_IMAGE
        box = DockerSandbox(image)
    allow = list((config.get("sandbox") or {}).get("allow_hosts") or cfg.DEFAULT_ALLOW_HOSTS)
    remaining = ledger.remaining()
    batch = box.start_batch(
        key=key, model=model, price=price, allow_hosts=allow, run_cap=args.run_cap, budget=remaining
    )
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) if args.out else root / ".obey" / "runs" / stamp
    runs_file = out_dir / "runs.jsonl"
    timeout = int((config.get("sandbox") or {}).get("timeout_s") or 600)

    def run_one(run: Any) -> dict[str, Any]:
        spec = RunSpec(
            run_id=run.run_id,
            prompt=run.probe["instruction"],
            source=root,
            probe_id=run.probe["id"],
            rule_id=run.rule["id"],
            arm=run.arm,
            trial=run.trial,
            overrides=run.overrides,
            extra_files=run.extra_files,
            git_hooks=run.git_hooks,
            setup_patch=run.probe.get("setup_patch"),
            timeout_s=timeout,
        )
        return execute(adapter, spec, box=box, batch=batch, model=model)

    try:
        result = execute_all(
            planned,
            run_one,
            ledger=ledger,
            per_run_estimate=est["per_run_usd"],
            concurrency=args.concurrency,
            out=runs_file,
            progress=out,
        )
    finally:
        box.stop_batch(batch)
    if result.stopped:
        err(f"stopped early: {result.stopped}")
    by_id = {r["id"]: r for r in config["rules"]}
    scores = score_outcomes(outcomes(result.records, by_id))
    versions = {r.get("agent_version") for r in result.records if r.get("agent_version")}
    cost = sum(r["usage"]["cost_usd"] for r in result.records)
    report = build_report(
        config["rules"],
        scores,
        [{"agent": agent_name, "version": next(iter(versions), None), "model": model}],
        repository=root.name,
        cost_usd=cost,
        runs=len(result.records),
        before=_rule_scores_from_report(before) if before is not None else None,
    )
    _write_reports(root, out_dir, report)
    for line in report["summary"]:
        out(line + ".")
    out(f"Report: {out_dir / 'report.html'}  (cost ${cost:.2f} for {len(result.records)} runs)")
    (root / "obey-badge.json").write_text(json.dumps(badge(report)) + "\n", encoding="utf-8")
    return 0 if not result.stopped else 3


def _write_reports(root: Path, out_dir: Path, report: dict[str, Any]) -> None:
    import jsonschema

    from obey_cli.report import render_html, render_markdown
    from obey_cli.resources import schema

    jsonschema.validate(report, schema("report-v1.json"))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    (out_dir / "report.html").write_text(render_html(report), encoding="utf-8")
    latest = root / ".obey"
    latest.mkdir(exist_ok=True)
    (latest / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------- report


def cmd_report(args: argparse.Namespace) -> int:
    """Re-score recorded runs with the current checkers and render the report again."""
    from obey_cli.report import build_report, render_html, render_markdown
    from obey_cli.runner.orchestrate import outcomes
    from obey_cli.score import score_outcomes

    root, config = _load(args)
    runs_path = Path(args.runs)
    records = [json.loads(line) for line in runs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {r["id"]: r for r in config["rules"]}
    scores = score_outcomes(outcomes(records, by_id))
    agents_seen = sorted({(r["agent"], r.get("agent_version"), r.get("model")) for r in records}, key=lambda x: str(x))
    report = build_report(
        config["rules"],
        scores,
        [{"agent": a, "version": v, "model": m} for a, v, m in agents_seen],
        repository=root.name,
        cost_usd=sum(r["usage"]["cost_usd"] for r in records),
        runs=len(records),
    )
    fmt = args.format
    if fmt == "json":
        out(json.dumps(report, indent=2))
    elif fmt == "md":
        out(render_markdown(report))
    elif fmt == "html":
        out(render_html(report))
    else:
        _write_reports(root, runs_path.parent, report)
        out(f"wrote {runs_path.parent / 'report.html'}, report.md and report.json")
    return 0
