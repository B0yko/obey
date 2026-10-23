"""Measure the generated hook's latency per agent payload (wall clock, including Python start-up).

    uv run python eval/hook_latency.py --runs 200 --out eval/results/hook-latency.json

Each sample starts a fresh `python3 .obey/hooks/obey_hook.py <agent>` process, as the agents do. Run it on a quiet
machine; the README reports the result with the hardware.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    from obey_cli.enforce import plan_enforce, select
    from obey_cli.rules import build_config
    from obey_cli.runner.workspace import build_probe_copy

    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        copy = build_probe_copy(ROOT / "study" / "repos" / "ts-web", Path(tmp) / "p", with_remote=False)
        config, _ = build_config(copy.work)
        rules = select(config)
        plan_enforce(copy.work, rules, ["claude", "codex", "copilot", "gemini", "cursor", "opencode"]).apply()
        hook = copy.work / ".obey" / "hooks" / "obey_hook.py"
        work = str(copy.work)
        payloads = {
            "claude": {"tool_name": "Bash", "tool_input": {"command": "pnpm add date-fns && pnpm test"}, "cwd": work},
            "codex": {"tool_name": "Bash", "tool_input": {"command": "npm install date-fns"}, "cwd": work},
            "copilot": {"toolName": "bash", "toolArgs": {"command": "git status"}, "cwd": work},
            "gemini": {"tool_name": "write_file", "tool_input": {"file_path": f"{work}/src/x.ts",
                                                                "content": "export const x = 1;\n"}, "cwd": work},
            "cursor": {"command": "sed -i 's/a/b/' src/generated/api-types.ts", "cwd": work},
            "opencode": {"tool": "edit", "args": {"filePath": f"{work}/src/date-utils.ts", "oldString": "a",
                                                  "newString": "b"}, "cwd": work},
        }
        results = {}
        for agent, payload in payloads.items():
            data = json.dumps(payload)
            times = []
            for _ in range(args.runs):
                started = time.perf_counter()
                subprocess.run([args.python, str(hook), agent], input=data, text=True, capture_output=True,
                               cwd=work, check=False)
                times.append((time.perf_counter() - started) * 1000)
            times.sort()
            results[agent] = {"p50_ms": round(statistics.median(times), 1),
                              "p95_ms": round(times[int(len(times) * 0.95) - 1], 1),
                              "max_ms": round(times[-1], 1), "runs": len(times)}
            print(agent, results[agent], flush=True)
    report = {"python": subprocess.run([args.python, "--version"], capture_output=True, text=True).stdout.strip(),
              "machine": platform.machine(), "system": platform.system(), "rules": len(rules), "agents": results}
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
