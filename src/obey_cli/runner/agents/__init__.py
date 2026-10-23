"""Agent adapters by name."""

from __future__ import annotations

from obey_cli.runner.agents.base import Adapter, ParsedStream, RunContext
from obey_cli.runner.agents.claude_code import ClaudeCode
from obey_cli.runner.agents.codex import Codex
from obey_cli.runner.agents.copilot import Copilot
from obey_cli.runner.agents.gemini import Gemini
from obey_cli.runner.agents.opencode import OpenCode

ADAPTERS: dict[str, type[Adapter]] = {a.name: a for a in (ClaudeCode, Codex, OpenCode, Gemini, Copilot)}


def get(name: str) -> Adapter:
    try:
        return ADAPTERS[name]()
    except KeyError:
        raise ValueError(f"unknown agent {name!r}; choose from {', '.join(sorted(ADAPTERS))}") from None


__all__ = ["ADAPTERS", "Adapter", "ParsedStream", "RunContext", "get"]
