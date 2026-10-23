"""Run one probe once and turn what happened into a normalised run record (`obey-run-v1`)."""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obey_cli.runner.agents.base import Adapter, RunContext
from obey_cli.runner.sandbox import AGENT_HOME, WORK_ROOT, Batch, DockerSandbox
from obey_cli.runner.workspace import EndState, build_probe_copy, set_origin

HOOK_LOG = f"{AGENT_HOME}/.obey-out/hook-log.jsonl"
REMOTE = f"{WORK_ROOT}/.remote/origin.git"


@dataclass
class RunSpec:
    run_id: str
    prompt: str
    source: Path
    probe_id: str = ""
    rule_id: str | None = None
    arm: str = "rule"  # rule | baseline | enforced
    condition: str | None = None
    trial: int = 0
    overrides: Mapping[str, str | None] = field(default_factory=dict)
    extra_files: Mapping[str, str] = field(default_factory=dict)
    git_hooks: Mapping[str, str] = field(default_factory=dict)
    setup_patch: str | None = None
    timeout_s: int = 600


def execute(
    adapter: Adapter, spec: RunSpec, *, box: DockerSandbox, batch: Batch, model: str, keep_dir: Path | None = None
) -> dict[str, Any]:
    started = _dt.datetime.now(_dt.timezone.utc)
    with tempfile.TemporaryDirectory(prefix="obey-run-") as tmp:
        root = Path(tmp)
        copy = build_probe_copy(
            spec.source,
            root / "probe",
            overrides=spec.overrides,
            extra_files=spec.extra_files,
            setup_patch=spec.setup_patch,
            git_hooks=spec.git_hooks,
            with_remote=True,
        )
        set_origin(copy.work, REMOTE)
        ctx = RunContext(
            run_id=spec.run_id,
            model=model,
            gateway_url=batch.gateway_url,
            timeout_s=spec.timeout_s,
            enforced=spec.arm == "enforced",
        )
        inv = adapter.invocation(spec.prompt, ctx)
        inv.env["OBEY_HOOK_LOG"] = HOOK_LOG
        raw = box.run(batch, copy.root, inv, root / "out", spec.run_id, base_sha=copy.base_sha)
        stream = _read(raw.out_dir / "stream.jsonl")
        stderr = _read(raw.out_dir / "stderr.log")
        parsed = adapter.parse(stream, stderr)
        end_state = json.loads(_read(raw.out_dir / "end-state.json") or "{}")
        state = EndState(
            diff=str(end_state.get("diff", "")),
            commits=list(end_state.get("commits", [])),
            pushed_refs=list(end_state.get("pushed_refs", [])),
            diff_truncated=bool(end_state.get("diff_truncated")),
        )
        hook_log = [json.loads(line) for line in _read(raw.out_dir / "hook-log.jsonl").splitlines() if line.strip()]
        ledger = [row for row in box.ledger_lines(batch) if row.get("run_id") == spec.run_id]
        status = "ok"
        if raw.timed_out:
            status = "timeout"
        elif any("budget" in str(e.get("detail", "")) for e in parsed.events) or "budget" in stderr[-2000:]:
            status = "budget_exceeded"
        elif (raw.exit_code not in (0, None) and not parsed.final_message) or not end_state:
            status = "error"
        record = {
            "schema": "obey-run-v1",
            "run_id": spec.run_id,
            "agent": adapter.name,
            "agent_version": parsed.usage.get("agent_version"),
            "model": model,
            "probe_id": spec.probe_id,
            "rule_id": spec.rule_id,
            "arm": spec.arm,
            "condition": spec.condition,
            "trial": spec.trial,
            "started_at": started.replace(microsecond=0).isoformat(),
            "duration_s": round(raw.duration_s, 2),
            "status": status,
            "exit_code": raw.exit_code,
            "events": parsed.events,
            "final_message": parsed.final_message,
            "diff": state.diff,
            "diff_truncated": state.diff_truncated,
            "base_files": copy.base_files,
            "commits": state.commits,
            "pushed_refs": state.pushed_refs,
            "instruction_files_loaded": parsed.instruction_files_loaded,
            "usage": {
                "input_tokens": sum(int(r.get("input_tokens", 0)) for r in ledger),
                "output_tokens": sum(int(r.get("output_tokens", 0)) for r in ledger),
                "cache_read_tokens": sum(int(r.get("cache_read_tokens", 0)) for r in ledger),
                "cost_usd": round(sum(float(r.get("cost_usd", 0.0)) for r in ledger), 6),
                "model_calls": len(ledger),
            },
            "hook_log": hook_log,
            "error": parsed.error,
        }
        if keep_dir is not None:
            keep_dir.mkdir(parents=True, exist_ok=True)
            (keep_dir / "stream.jsonl").write_text(stream, encoding="utf-8")
            (keep_dir / "stderr.log").write_text(stderr[-20000:], encoding="utf-8")
            for name in ("hook-log.jsonl",):
                if (raw.out_dir / name).exists():
                    shutil.copy2(raw.out_dir / name, keep_dir / name)
        return record


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
