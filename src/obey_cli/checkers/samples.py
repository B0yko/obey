"""Decide labelled extraction samples with the engine (used by eval/run_eval.py to score extracted parameters).

A sample is flagged when the extracted checker reports a violation for a minimal run built from it; see
fixtures/extraction for the sample formats.
"""

from __future__ import annotations

import json
from typing import Any

from obey_cli.enforce.engine import obey_engine as engine


def _empty() -> dict[str, Any]:
    return {"events": [], "diff": "", "base_files": [], "commits": [], "pushed_refs": [], "final_message": ""}


def _modified(path: str, line: str = "x = 1") -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,0 +1,1 @@\n+{line}\n"


def _split(sample: str) -> tuple[str, str]:
    path, _, line = sample.partition(": ")
    return path.strip(), line


def run_for(checker: dict[str, Any], sample: Any) -> dict[str, Any]:
    kind = checker["type"]
    run = _empty()
    if kind in ("command_forbidden", "no_commit", "no_push"):
        run["events"] = [{"seq": 0, "type": "shell", "command": str(sample), "exit_code": 0}]
    elif kind == "command_required":
        globs = checker["params"].get("edit_globs") or ["**"]
        path = "src/app.py"
        for candidate in ("src/app.py", "app/main.py", "src/index.ts", "main.go", "src/lib.rs", "docs/index.md"):
            if engine.glob_match(globs, candidate):
                path = candidate
                break
        else:
            path = globs[0].replace("**/", "").replace("**", "x").replace("*", "x")
        run["events"] = [
            {"seq": 0, "type": "edit", "path": path},
            {"seq": 1, "type": "shell", "command": str(sample), "exit_code": 0},
        ]
        run["diff"] = _modified(path)
    elif kind == "path_forbidden":
        run["events"] = [{"seq": 0, "type": "write", "path": str(sample)}]
        run["base_files"] = [str(sample)]
    elif kind == "path_required_with":
        files = sample if isinstance(sample, list) else [sample]
        run["diff"] = "".join(_modified(str(f)) for f in files)
    elif kind == "dependency_unchanged":
        text = str(sample)
        if ": +" in text:
            path, _, name = text.partition(": +")
            path = path.strip()
            base = path.rsplit("/", 1)[-1]
            if base == "package.json":
                line = f'    "{name.strip()}": "^1.0.0",'
            elif base == "go.mod":
                line = f"\t{name.strip()} v1.0.0"
            elif base == "Cargo.toml":
                line = f'{name.strip()} = "1.0"'
            elif base.startswith("requirements"):
                line = f"{name.strip()}>=1.0"
            else:
                line = f'    "{name.strip()}>=1.0",'
            run["diff"] = _modified(path, line)
        else:
            run["events"] = [{"seq": 0, "type": "shell", "command": text, "exit_code": 0}]
    elif kind == "content_forbidden_added":
        path, line = _split(str(sample))
        run["diff"] = _modified(path, line)
    elif kind == "content_required_added":
        path, line = _split(str(sample))
        run["diff"] = engine.new_file_diff(path, line + "\n")
    elif kind == "commit_message":
        run["commits"] = [{"sha": "0" * 40, "message": str(sample), "files": []}]
    elif kind == "file_naming":
        run["diff"] = engine.new_file_diff(str(sample), "x\n")
    elif kind == "final_message":
        run["final_message"] = str(sample)
    else:
        raise ValueError(f"unknown checker type {kind}")
    return run


def classify_sample(checker: dict[str, Any], sample: Any) -> bool:
    """True when the sample breaks the rule according to the extracted checker."""
    try:
        verdict = engine.check(checker, run_for(checker, sample))
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return bool(verdict["verdict"] == "violated")
