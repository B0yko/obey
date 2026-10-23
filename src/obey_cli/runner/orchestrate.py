"""Plan and execute probe runs: arms, trials, concurrency, budget, and scoring."""

from __future__ import annotations

import datetime as _dt
import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obey_cli.runner.ledger import BudgetExceeded, Entry, Ledger
from obey_cli.runner.workspace import remove_lines

# Rough tokens per run by agent, used only for --estimate before any run has been measured.
EST_TOKENS = {
    "claude-code": (450_000, 6_000),
    "codex": (250_000, 5_000),
    "opencode": (200_000, 4_000),
    "copilot": (250_000, 5_000),
    "gemini": (250_000, 5_000),
}
CACHE_SHARE = 0.85


@dataclass
class PlannedRun:
    run_id: str
    rule: dict[str, Any]
    probe: dict[str, Any]
    arm: str  # rule | baseline | enforced
    trial: int
    overrides: dict[str, str | None] = field(default_factory=dict)
    extra_files: dict[str, str] = field(default_factory=dict)
    git_hooks: dict[str, str] = field(default_factory=dict)
    condition: str | None = None


def _rid(*parts: object) -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    text = "-".join(str(p) for p in parts)
    import hashlib

    return f"{stamp}-{hashlib.sha1(text.encode()).hexdigest()[:10]}"  # noqa: S324 - an identifier


def plan_runs(
    repo: Path,
    rules: Sequence[dict[str, Any]],
    *,
    trials: int,
    baseline_trials: int,
    enforced: Mapping[str, str] | None = None,
    enforced_hooks: Mapping[str, str] | None = None,
    only_enforced: bool = False,
) -> list[PlannedRun]:
    """One PlannedRun per (rule, probe, arm, trial). `enforced` maps repository paths to enforcement file contents."""
    planned: list[PlannedRun] = []
    for rule in rules:
        for probe in rule.get("probes") or []:
            if not only_enforced:
                for t in range(trials):
                    planned.append(PlannedRun(_rid(rule["id"], probe["id"], "rule", t), rule, probe, "rule", t))
                src = rule["source"]
                path = repo / src["file"]
                if baseline_trials and path.exists():
                    text = remove_lines(path.read_text(encoding="utf-8"), src["lines"][0], src["lines"][1])
                    for t in range(baseline_trials):
                        planned.append(
                            PlannedRun(
                                _rid(rule["id"], probe["id"], "baseline", t),
                                rule,
                                probe,
                                "baseline",
                                t,
                                overrides={src["file"]: text},
                            )
                        )
            if enforced is not None:
                for t in range(trials):
                    planned.append(
                        PlannedRun(
                            _rid(rule["id"], probe["id"], "enforced", t),
                            rule,
                            probe,
                            "enforced",
                            t,
                            extra_files=dict(enforced),
                            git_hooks=dict(enforced_hooks or {}),
                        )
                    )
    return planned


def estimate(
    planned: Sequence[PlannedRun], agent: str, price: Mapping[str, float], measured_per_run: float | None = None
) -> dict[str, Any]:
    if measured_per_run is not None:
        per_run = measured_per_run
        source = "measured from previous runs"
    else:
        tokens_in, tokens_out = EST_TOKENS.get(agent, (300_000, 5_000))
        cached = tokens_in * CACHE_SHARE
        fresh = tokens_in - cached
        per_run = (
            fresh * price.get("prompt", 0.0)
            + cached * price.get("cache_read", price.get("prompt", 0.0))
            + tokens_out * price.get("completion", 0.0)
        )
        source = "default token profile × model price"
    return {"runs": len(planned), "per_run_usd": per_run, "total_usd": per_run * len(planned), "source": source}


def model_price(model: str, client: Any = None) -> dict[str, float]:
    """USD per token for an OpenRouter model id (empty when unknown or offline)."""
    import httpx

    try:
        resp = (client or httpx).get("https://openrouter.ai/api/v1/models", timeout=20)
        for m in resp.json().get("data", []):
            if m.get("id") == model:
                p = m.get("pricing") or {}
                out = {"prompt": float(p.get("prompt") or 0), "completion": float(p.get("completion") or 0)}
                if p.get("input_cache_read"):
                    out["cache_read"] = float(p["input_cache_read"])
                if p.get("input_cache_write"):
                    out["cache_write"] = float(p["input_cache_write"])
                return out
    except (httpx.HTTPError, ValueError):
        pass
    return {}


@dataclass
class Execution:
    records: list[dict[str, Any]]
    stopped: str | None  # why the batch stopped early, if it did


def execute_all(
    planned: Sequence[PlannedRun],
    run_one: Callable[[PlannedRun], dict[str, Any]],
    *,
    ledger: Ledger,
    per_run_estimate: float,
    concurrency: int,
    out: Path,
    progress: Callable[[str], None] = print,
) -> Execution:
    """Run everything with a thread pool, writing each record as it finishes and stopping before the budget."""
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    records: list[dict[str, Any]] = []
    stop: list[str] = []
    started = time.monotonic()

    def guarded(run: PlannedRun) -> dict[str, Any] | None:
        if stop:
            return None
        try:
            with lock:
                ledger.check(per_run_estimate)
        except BudgetExceeded as exc:
            stop.append(str(exc))
            return None
        record = run_one(run)
        with lock:
            ledger.record(
                Entry(
                    ts=time.time(),
                    run_id=record["run_id"],
                    kind="agent",
                    model=record.get("model", ""),
                    input_tokens=record["usage"]["input_tokens"],
                    output_tokens=record["usage"]["output_tokens"],
                    cache_read_tokens=record["usage"]["cache_read_tokens"],
                    cost_usd=record["usage"]["cost_usd"],
                    cost_source="provider",
                )
            )
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        return record

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(guarded, run): run for run in planned}
        for done, future in enumerate(as_completed(futures), 1):
            record = future.result()
            if record is not None:
                records.append(record)
                elapsed = time.monotonic() - started
                progress(
                    f"[{done}/{len(planned)}] {record['arm']:8s} {record['rule_id'][:40]:40s} "
                    f"{record['status']:7s} ${record['usage']['cost_usd']:.4f} ({elapsed:.0f}s)"
                )
    return Execution(records=records, stopped=stop[0] if stop else None)


def outcomes(records: Iterable[dict[str, Any]], rules: Mapping[str, dict[str, Any]]) -> list[Any]:
    """Score every run against its own rule with the deterministic checker."""
    from obey_cli.checkers import check
    from obey_cli.score import Outcome

    result = []
    for rec in records:
        rule = rules.get(rec["rule_id"])
        if rule is None:
            continue
        verdict = check(rule["checker"], rec)
        denied = sum(1 for h in rec.get("hook_log") or [] if h.get("decision") in ("deny", "block"))
        result.append(
            Outcome(
                rule_id=rec["rule_id"],
                agent=rec["agent"],
                arm=rec["arm"],
                verdict=verdict.verdict,
                run_id=rec["run_id"],
                denied=denied,
                evidence=verdict.evidence,
                condition=rec.get("condition"),
                status=rec.get("status", "ok"),
            )
        )
    return result
