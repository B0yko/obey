"""Build and merge obey.yaml rule lists."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from obey_cli import __version__
from obey_cli.config import DEFAULT_ALLOW_HOSTS
from obey_cli.discover import InstructionFile, discover
from obey_cli.extract import Extracted, extract


def sources(files: Iterable[InstructionFile]) -> list[dict[str, Any]]:
    return [
        {
            "file": f.path,
            "sha256": f.sha256,
            "kind": f.kind,
            "scope": list(f.scope_paths),
            "loaded_by": list(f.loaded_by),
        }
        for f in files
    ]


def merge(fresh: Sequence[dict[str, Any]], previous: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep what a person changed in obey.yaml (status, checker, probes) for rules whose text did not change."""
    old = {r["id"]: r for r in previous}
    merged = []
    for rule in fresh:
        before = old.get(rule["id"])
        if before is None:
            merged.append(rule)
            continue
        keep = dict(rule)
        for key in ("status", "checker", "reason", "probes", "scope"):
            if key in before:
                keep[key] = before[key]
        if before.get("origin") == "user":
            keep["origin"] = "user"
        merged.append(keep)
    # Rules a person added by hand survive re-extraction.
    merged += [r for r in previous if r.get("origin") == "user" and r["id"] not in {m["id"] for m in merged}]
    return merged


def build_config(
    root: Path, previous: dict[str, Any] | None = None, include_local: bool = False, proposals: Sequence[Extracted] = ()
) -> tuple[dict[str, Any], list[InstructionFile]]:
    files = discover(root, include_local=include_local)
    items = extract(files)
    fresh = [x.as_rule() for x in items] + [p.as_rule() for p in proposals]
    rules = merge(fresh, (previous or {}).get("rules") or [])
    config: dict[str, Any] = {
        "version": 1,
        "generated_by": f"obey {__version__}",
        "sources": sources(files),
        "sandbox": (previous or {}).get("sandbox")
        or {"image": None, "allow_hosts": list(DEFAULT_ALLOW_HOSTS), "timeout_s": 600},
        "rules": rules,
    }
    if previous and previous.get("agents"):
        config["agents"] = previous["agents"]
    return config, files


def counts(rules: Iterable[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rules:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out
