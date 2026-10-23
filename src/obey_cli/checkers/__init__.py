"""Deterministic checkers: one verdict per rule per run, with evidence.

The logic lives in the stdlib-only rule engine (`obey_cli.enforce.engine.obey_engine`), which `obey enforce` also
vendors into generated hooks, so what a hook blocks is exactly what a checker measures.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from obey_cli.enforce.engine import obey_engine as engine

TYPES = tuple(engine.CHECKS)


@dataclass
class Verdict:
    verdict: str  # obeyed | violated | not_exercised
    evidence: list[dict[str, Any]] = field(default_factory=list)


def check(rule: Mapping[str, Any], run: Mapping[str, Any]) -> Verdict:
    """Verdict of `rule` (a checker {"type", "params"} or a rule holding one) on a normalised run record."""
    result = engine.check(dict(rule), dict(run))
    return Verdict(verdict=str(result["verdict"]), evidence=list(result.get("evidence") or []))


__all__ = ["TYPES", "Verdict", "check", "engine"]
