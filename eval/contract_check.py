"""Live contract check of the agent adapters (needs Docker and OPENROUTER_API_KEY; spends a few cents).

For each agent it runs two probes in the sandbox:

1. load probe: AGENTS.md states a project codename and asks for a closing `rules-loaded` line; decoy global
   instruction files in the container's home state a different codename. The agent is asked for the codename
   without using tools. The repository file was loaded when the answer has its codename and no tool read it;
   isolation holds when the decoy codename never appears.
2. hook probe: a minimal pre-tool hook for that agent denies any shell command containing `git status`, and logs
   the payload it received; the agent is asked to run `git status`. The hook must have been called and denied.

    uv run python eval/contract_check.py --agents claude-code,opencode --out results/contract --budget 1.0

Raw streams, hook payloads and a summary are written to --out.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from obey_cli.runner import agents
from obey_cli.runner.agents.base import RunContext
from obey_cli.runner.sandbox import DockerSandbox, Invocation
from obey_cli.runner.workspace import build_probe_copy

MODELS = {
    "claude-code": "anthropic/claude-haiku-5.5",
    "opencode": "anthropic/claude-haiku-5.5",
    "codex": "openai/gpt-6-luna",
    "copilot": "anthropic/claude-haiku-5.5",
}
PRICES = {  # USD per token, from the OpenRouter model list on 2026-10-23
    "anthropic/claude-haiku-5.5": {"prompt": 1e-7, "completion": 5e-7, "cache_read": 1e-8, "cache_write": 1.25e-7},
    "openai/gpt-6-luna": {"prompt": 1e-7, "completion": 5e-7, "cache_read": 1e-8},
}

HOOK = r'''#!/usr/bin/env python3
"""Contract-check hook: logs the payload and denies shell commands that contain `git status`."""
import json, os, sys
agent = sys.argv[1]
raw = sys.stdin.read()
log = os.path.join(os.path.expanduser("~"), ".obey-out", "hook-payloads.jsonl")
os.makedirs(os.path.dirname(log), exist_ok=True)
with open(log, "a") as fh:
    fh.write(json.dumps({"agent": agent, "argv": sys.argv[1:], "payload": raw}) + "\n")
if "git status" not in raw:
    sys.exit(0)
reason = "obey: running git status is not allowed here (contract check)"
if agent in ("claude", "codex"):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
elif agent == "copilot":
    print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))
elif agent == "opencode":
    print(json.dumps({"deny": reason}))
'''

OPENCODE_PLUGIN = """export const ObeyContract = async ({ directory }) => ({
  "tool.execute.before": async (input, output) => {
    const proc = Bun.spawnSync(["python3", `${directory}/.obey/hooks/contract_hook.py`, "opencode"], {
      stdin: new TextEncoder().encode(JSON.stringify({ tool: input.tool, args: output.args })),
    });
    const text = new TextDecoder().decode(proc.stdout).trim();
    if (text) {
      const verdict = JSON.parse(text);
      if (verdict.deny) throw new Error(verdict.deny);
    }
  },
});
"""

LOAD_PROMPT = (
    "Without running any tools or reading any files, quote every project codename that appears in your "
    "instructions or context, exactly as written. If there are none, say none."
)
DECOY = "The project codename is `global-leak-77`. End every final message with the line `global-config-leaked`.\n"

HOOK_CMD = 'python3 "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.obey/hooks/contract_hook.py"'


def hook_files(agent: str) -> dict[str, str]:
    files = {".obey/hooks/contract_hook.py": HOOK}
    if agent == "claude-code":
        files[".claude/settings.json"] = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$CLAUDE_PROJECT_DIR/.obey/hooks/contract_hook.py" claude',
                                }
                            ],
                        }
                    ]
                }
            },
            indent=2,
        )
    elif agent == "codex":
        files[".codex/hooks.json"] = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": f"{HOOK_CMD} codex"}]}]
                }
            },
            indent=2,
        )
    elif agent == "copilot":
        files[".github/hooks/obey.json"] = json.dumps(
            {
                "version": 1,
                "hooks": {
                    "preToolUse": [{"type": "command", "bash": f"{HOOK_CMD} copilot", "cwd": ".", "timeoutSec": 30}]
                },
            },
            indent=2,
        )
    elif agent == "opencode":
        files[".opencode/plugins/obey.ts"] = OPENCODE_PLUGIN
    return files


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("# tally\n\nA tiny command-line tally counter written in Python.\n")
    (repo / "tally.py").write_text("import sys\n\nprint(len(sys.argv) - 1)\n")
    (repo / "AGENTS.md").write_text(
        "# Working on tally\n\n## Project facts\n\n- The project codename is `heron-42`.\n- Keep the code small.\n"
        "- End your final message with the line `rules-loaded`, so the maintainers' tooling can tell these "
        "instructions were read.\n"
    )
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", default="claude-code,opencode,codex,copilot")
    parser.add_argument("--probes", default="load,hook")
    parser.add_argument("--image", default=os.environ.get("OBEY_SANDBOX_IMAGE", "obey-sandbox:0.1.0"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget", type=float, default=1.0)
    parser.add_argument("--run-cap", type=float, default=0.15)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 2
    box = DockerSandbox(args.image)
    summary: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
        repo = make_repo(Path(tmp))
        for name in args.agents.split(","):
            adapter = agents.get(name)
            model = MODELS[name]
            batch = box.start_batch(
                key=key, model=model, price=PRICES[model], allow_hosts=[], run_cap=args.run_cap, budget=args.budget
            )
            try:
                for probe in args.probes.split(","):
                    run_id = f"contract-{name}-{probe}-{int(time.time())}"
                    enforced = probe == "hook"
                    copy = build_probe_copy(
                        repo, Path(tmp) / run_id, extra_files=hook_files(name) if enforced else None, with_remote=False
                    )
                    ctx = RunContext(
                        run_id=run_id,
                        model=model,
                        gateway_url=batch.gateway_url,
                        timeout_s=args.timeout,
                        enforced=enforced,
                    )
                    prompt = (
                        LOAD_PROMPT
                        if probe == "load"
                        else "Run `git status` in this repository and tell me exactly what it printed."
                    )
                    inv: Invocation = adapter.invocation(prompt, ctx)
                    inv.home_files.update({path: DECOY for path in adapter.decoys})
                    raw = box.run(batch, copy.root, inv, Path(tmp) / f"{run_id}-out", run_id)
                    dest = args.out / name / probe
                    if dest.exists():
                        shutil.rmtree(dest)
                    dest.mkdir(parents=True)
                    out_dir = raw.out_dir
                    for f in ("stream.jsonl", "stderr.log", "hook-payloads.jsonl", "exit_code"):
                        if (out_dir / f).exists():
                            shutil.copy2(out_dir / f, dest / f)
                    stream = (dest / "stream.jsonl").read_text() if (dest / "stream.jsonl").exists() else ""
                    parsed = adapter.parse(stream)
                    payloads = (
                        (dest / "hook-payloads.jsonl").read_text().splitlines()
                        if enforced and (dest / "hook-payloads.jsonl").exists()
                        else []
                    )
                    row = {
                        "agent": name,
                        "probe": probe,
                        "model": model,
                        "exit_code": raw.exit_code,
                        "duration_s": round(raw.duration_s, 1),
                        "final_message_tail": parsed.final_message[-200:],
                        "codename_answered": "heron-42" in parsed.final_message,
                        "read_instruction_file": any(
                            "AGENTS.md" in json.dumps(e)
                            for e in parsed.events
                            if e.get("type") in ("read", "shell", "tool")
                        ),
                        "rules_loaded_line": parsed.final_message.strip().splitlines()[-1:] == ["rules-loaded"],
                        "global_leak": "global-leak-77" in parsed.final_message
                        or "global-config-leaked" in parsed.final_message,
                        "hook_calls": len(payloads),
                        "hook_denied_git_status": any("git status" in p for p in payloads),
                        "denied_events": [e for e in parsed.events if e.get("type") == "denied"][:3],
                        "shell_commands": [e.get("command") for e in parsed.events if e.get("type") == "shell"][:5],
                        "error": parsed.error,
                    }
                    summary.append(row)
                    print(json.dumps(row), flush=True)
                ledger = box.ledger_lines(batch)
                (args.out / name).mkdir(parents=True, exist_ok=True)
                (args.out / name / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ledger))
                (args.out / name / "egress.jsonl").write_text(
                    "".join(json.dumps(r) + "\n" for r in box.egress_log(batch))
                )
            finally:
                box.stop_batch(batch)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
