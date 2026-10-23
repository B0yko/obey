"""Run the phrasing experiment (pilot, main grid, enforcement) and keep per-run summaries.

Per-run summaries go to study/results/<phase>.jsonl (committed). Full run records with streams-derived events and
diffs go to study/results/raw/<phase>.jsonl (published as a release archive after a scan, never committed).
Interrupted batches resume: runs whose key is already in the summaries are skipped.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from obey_cli.study import design as d

HARNESS_TARGET = {
    "claude-code": "claude",
    "opencode": "opencode",
    "codex": "codex",
    "copilot": "copilot",
    "gemini": "gemini",
}


@dataclass(frozen=True)
class StudyRun:
    phase: str
    cell: d.Cell
    trial: int

    @property
    def key(self) -> str:
        c = self.cell
        return f"{self.phase}|{c.repo}|{c.slot}|{c.condition}|{c.harness}|{self.trial}"

    @property
    def run_id(self) -> str:
        return f"{self.phase}-{hashlib.sha1(self.key.encode()).hexdigest()[:12]}"  # noqa: S324 - an identifier


def plan(design: dict[str, Any], phase: str, trials: int, **filters: Any) -> list[StudyRun]:
    runs = [StudyRun(phase, cell, t) for cell in d.cells(design, **filters) for t in range(trials)]
    # Interleave cells so an early stop leaves a balanced sample rather than whole missing conditions.
    runs.sort(key=lambda r: (r.trial, hashlib.sha1(r.key.encode()).hexdigest()))  # noqa: S324
    return runs


def done_keys(summaries: Path) -> set[str]:
    if not summaries.exists():
        return set()
    keys = set()
    for line in summaries.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("status") == "ok":
                keys.add(row["key"])
    return keys


def summarize(run: StudyRun, record: dict[str, Any], verdict: Any) -> dict[str, Any]:
    denied = sum(1 for h in record.get("hook_log") or [] if h.get("decision") in ("deny", "block"))
    return {
        "key": run.key,
        "run_id": record["run_id"],
        "phase": run.phase,
        "repo": run.cell.repo,
        "slot": run.cell.slot,
        "condition": run.cell.condition,
        "harness": run.cell.harness,
        "trial": run.trial,
        "agent_version": record.get("agent_version"),
        "model": record.get("model"),
        "status": record["status"],
        "verdict": verdict.verdict,
        "evidence_kind": (verdict.evidence[0]["kind"] if verdict.evidence else None),
        "denied": denied,
        "cost_usd": record["usage"]["cost_usd"],
        "input_tokens": record["usage"]["input_tokens"],
        "output_tokens": record["usage"]["output_tokens"],
        "duration_s": record["duration_s"],
        "events": len(record.get("events") or []),
        "commits": len(record.get("commits") or []),
        "started_at": record.get("started_at"),
    }


def execute(
    design: dict[str, Any],
    runs: Sequence[StudyRun],
    *,
    root: Path,
    key: str,
    image: str,
    budget: float,
    spent_before: float,
    concurrency: int,
    results: Path,
    enforce_rules: bool = False,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run `runs` grouped by harness (one gateway batch each), appending summaries and raw records as they finish."""
    from obey_cli.checkers import check
    from obey_cli.commands import _enforcement_files
    from obey_cli.runner import agents
    from obey_cli.runner.core import RunSpec
    from obey_cli.runner.core import execute as execute_run
    from obey_cli.runner.sandbox import DockerSandbox

    phase = runs[0].phase if runs else "none"
    summaries = results / f"{phase}.jsonl"
    raw = results / "raw" / f"{phase}.jsonl"
    raw.parent.mkdir(parents=True, exist_ok=True)
    skip = done_keys(summaries)
    todo = [r for r in runs if r.key not in skip]
    progress(f"{phase}: {len(todo)} runs to do ({len(runs) - len(todo)} already done)")
    box = DockerSandbox(image, cpus="2", memory="4g")
    lock = threading.Lock()
    spent = [spent_before]
    stopped: list[str] = []
    started = time.monotonic()
    model = design["model"]
    for harness in sorted({r.cell.harness for r in todo}):
        adapter = agents.get(harness)
        mine = [r for r in todo if r.cell.harness == harness]
        batch = box.start_batch(
            key=key,
            model=model,
            price={},
            allow_hosts=design.get("allow_hosts") or ["registry.npmjs.org", "pypi.org", "files.pythonhosted.org"],
            run_cap=0.5,
            budget=None,
            run_ids=[r.run_id for r in mine],
        )

        def one(run: StudyRun, adapter: Any = adapter, batch: Any = batch, harness: str = harness) -> None:
            if stopped:
                return
            with lock:
                if spent[0] >= budget:
                    stopped.append(f"budget ${budget:.2f} reached (spent ${spent[0]:.2f})")
                    return
            repo = design["repos"][run.cell.repo]
            text, _ = d.render(repo, run.cell.slot, run.cell.condition)
            rule = d.rule(design, run.cell.repo, run.cell.slot, run.cell.condition)
            extra: dict[str, str] = {}
            hooks: dict[str, str] = {}
            if enforce_rules:
                extra, hooks = _enforcement_files([rule], [HARNESS_TARGET[harness], "precommit"])
            spec = RunSpec(
                run_id=run.run_id,
                prompt=rule["probes"][0]["instruction"],
                source=root / repo["path"],
                probe_id=rule["probes"][0]["id"],
                rule_id=rule["id"],
                arm="enforced" if enforce_rules else ("baseline" if run.cell.condition == "baseline" else "rule"),
                condition=run.cell.condition,
                trial=run.trial,
                overrides={"AGENTS.md": text},
                extra_files=extra,
                git_hooks=hooks,
                timeout_s=600,
            )
            record = execute_run(adapter, spec, box=box, batch=batch, model=model)
            verdict = check(rule["checker"], record)
            summary = summarize(run, record, verdict)
            with lock:
                spent[0] += record["usage"]["cost_usd"]
                with summaries.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(summary, sort_keys=True) + "\n")
                with raw.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({**record, "study_key": run.key}) + "\n")
                elapsed = time.monotonic() - started
                progress(
                    f"{summary['phase']} {harness:11s} {run.cell.repo:10s} {run.cell.slot:24s} "
                    f"{run.cell.condition:11s} t{run.trial} {summary['status']:7s} {summary['verdict']:13s} "
                    f"${summary['cost_usd']:.4f} total ${spent[0]:.2f} ({elapsed:.0f}s)"
                )

        try:
            with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
                for future in as_completed([pool.submit(one, r) for r in mine]):
                    future.result()
        finally:
            box.stop_batch(batch)
        if stopped:
            break
    return {
        "phase": phase,
        "done": len(done_keys(summaries)),
        "spent": spent[0],
        "stopped": stopped[0] if stopped else None,
    }
