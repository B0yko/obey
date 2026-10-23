"""Build the data for `obey demo` from the study's raw run records.

    uv run python eval/build_demo.py --raw study/results/raw --repo ts-web --harness claude-code

Writes demo/obey.yaml (the repository's rules in their imperative phrasing) and demo/runs/{before,after}.jsonl.gz:
main-grid runs in the imperative and no-rule conditions, and the enforcement runs, for one repository and harness.
Command output inside events is shortened; diffs, commits and final messages are kept, because the checkers read them.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any

from obey_cli import config as cfg
from obey_cli.study import design as d

ROOT = Path(__file__).resolve().parents[1]


def trim(record: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in record.items() if k not in ("study_key",)}
    events = []
    for e in record.get("events") or []:
        e = dict(e)
        for key in ("output", "text", "content"):
            if isinstance(e.get(key), str) and len(e[key]) > 300:
                e[key] = e[key][:300] + " …"
        events.append(e)
    out["events"] = events
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=ROOT / "study" / "results" / "raw")
    parser.add_argument("--repo", default="ts-web")
    parser.add_argument("--harness", default="claude-code")
    args = parser.parse_args()
    design = d.load(ROOT / "study" / "design.yaml")
    rules = [d.rule(design, args.repo, slot, "imperative") for slot in design["repos"][args.repo]["slots"]]
    for r in rules:
        r["probes"] = r["probes"][:1]
    sources = [
        {
            "file": "AGENTS.md",
            "sha256": __import__("hashlib")
            .sha256((ROOT / design["repos"][args.repo]["path"] / "AGENTS.md").read_bytes())
            .hexdigest(),
            "kind": "agents_md",
            "scope": ["**"],
            "loaded_by": ["claude-code", "codex", "opencode", "cursor", "gemini", "copilot"],
        }
    ]
    cfg.save(
        ROOT / "demo" / "obey.yaml",
        {"version": 1, "generated_by": "obey study design", "sources": sources, "rules": rules},
    )

    def load(phase: str) -> list[dict[str, Any]]:
        path = args.raw / f"{phase}.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [
            r
            for r in rows
            if r.get("agent") == args.harness and r["rule_id"].startswith(args.repo + "--") and r.get("status") == "ok"
        ]

    before = [r for r in load("main") if r.get("condition") in ("imperative", "baseline")]
    after = load("enforce") if (args.raw / "enforce.jsonl").exists() else []
    out = ROOT / "demo" / "runs"
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("before", before), ("after", after)):
        with gzip.open(out / f"{name}.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as fh:
            for r in rows:
                fh.write(json.dumps(trim(r), sort_keys=True) + "\n")
    runs = before + after
    dates = sorted(r["started_at"][:10] for r in runs)
    meta = {
        "agent": args.harness,
        "agent_version": next((r.get("agent_version") for r in runs if r.get("agent_version")), None),
        "model": runs[0]["model"] if runs else None,
        "repository": f"{args.repo} (obey demo repository)",
        "dates": f"{dates[0]} to {dates[-1]}" if dates else "",
        "runs": len(runs),
        "cost_usd": round(sum(r["usage"]["cost_usd"] for r in runs), 4),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**meta, "before": len(before), "after": len(after)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
