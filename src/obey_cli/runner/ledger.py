"""Spend ledger: every model call is recorded, and runs stop before the budget is exhausted.

The ledger is an append-only JSON-lines file guarded by an advisory lock, so the model gateway (which records
usage as responses stream through) and the runner (which checks the budget before starting a run) can share it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import time
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Any


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Price:
    """USD per token."""

    prompt: float
    completion: float
    cache_read: float | None = None
    cache_write: float | None = None

    def cost(self, usage: Mapping[str, int]) -> float:
        cached = int(usage.get("cache_read_tokens", 0))
        written = int(usage.get("cache_write_tokens", 0))
        fresh = max(0, int(usage.get("input_tokens", 0)) - cached - written)
        total = fresh * self.prompt + int(usage.get("output_tokens", 0)) * self.completion
        total += cached * (self.cache_read if self.cache_read is not None else self.prompt)
        total += written * (self.cache_write if self.cache_write is not None else self.prompt)
        return total


@dataclass
class Entry:
    ts: float
    run_id: str
    kind: str  # agent | llm | estimate
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    cost_source: str = "price_table"  # provider | price_table


@contextlib.contextmanager
def _locked(path: Path, mode: str) -> Iterator[IO[str]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX if "a" in mode or "w" in mode else fcntl.LOCK_SH)
        try:
            yield fh
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class Ledger:
    def __init__(self, path: Path, budget_usd: float | None = None):
        self.path = path
        self.budget_usd = budget_usd

    def record(self, entry: Entry) -> None:
        with _locked(self.path, "a") as fh:
            fh.write(json.dumps(asdict(entry), sort_keys=True) + "\n")

    def entries(self) -> list[Entry]:
        if not self.path.exists():
            return []
        with _locked(self.path, "r") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        return [Entry(**row) for row in rows]

    def spent(self, run_id: str | None = None) -> float:
        return sum(e.cost_usd for e in self.entries() if run_id is None or e.run_id == run_id)

    def remaining(self) -> float | None:
        return None if self.budget_usd is None else self.budget_usd - self.spent()

    def check(self, next_cost_usd: float = 0.0) -> None:
        """Raise BudgetExceeded when spending `next_cost_usd` more would cross the budget."""
        if self.budget_usd is None:
            return
        spent = self.spent()
        if spent + next_cost_usd > self.budget_usd:
            raise BudgetExceeded(
                f"budget ${self.budget_usd:.2f}: spent ${spent:.4f}, next run estimated at ${next_cost_usd:.4f}"
            )


def usage_from_response(body: Mapping[str, Any]) -> dict[str, int]:
    """Normalise OpenAI- and Anthropic-style usage blocks to input/output/cache token counts."""
    usage = body.get("usage") or {}
    if not isinstance(usage, Mapping):
        return {}
    if "prompt_tokens" in usage or "completion_tokens" in usage:
        details = usage.get("prompt_tokens_details") or {}
        return {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "cache_read_tokens": int(details.get("cached_tokens") or 0),
            "cache_write_tokens": int(details.get("cache_write_tokens") or 0),
        }
    read = int(usage.get("cache_read_input_tokens") or 0)
    write = int(usage.get("cache_creation_input_tokens") or 0)
    return {
        # Anthropic counts cached tokens separately from input_tokens.
        "input_tokens": int(usage.get("input_tokens") or 0) + read + write,
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_tokens": read,
        "cache_write_tokens": write,
    }


def provider_cost(body: Mapping[str, Any]) -> float | None:
    usage = body.get("usage") or {}
    if isinstance(usage, Mapping) and isinstance(usage.get("cost"), int | float):
        return float(usage["cost"])
    return None


def now() -> float:
    return time.time()
