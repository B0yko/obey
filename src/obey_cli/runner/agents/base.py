"""Common interface for agent adapters: how to invoke an agent headless, and how to read its stream back."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from obey_cli.runner.sandbox import WORK_ROOT, Invocation

WORKDIR = f"{WORK_ROOT}/work"
DUMMY_TOKEN = "obey-dummy-token"  # noqa: S105 - agents never see a real key; the gateway swaps it


@dataclass
class ParsedStream:
    events: list[dict[str, Any]] = field(default_factory=list)
    final_message: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    instruction_files_loaded: list[str] | None = None  # None: the agent does not report it
    error: str | None = None


@dataclass
class RunContext:
    run_id: str
    model: str
    gateway_url: str  # e.g. http://obey-gw:8787
    timeout_s: int = 600
    enforced: bool = False

    def base(self, api: str) -> str:
        return f"{self.gateway_url}/r/{self.run_id}/{api}"


class Adapter:
    """Subclasses set the class attributes and implement `invocation` and `parse`."""

    name = ""
    display = ""
    binary = ""
    api = "openai"  # which gateway skin the agent speaks: anthropic | openai | gemini
    instruction_files: tuple[str, ...] = ()
    # Decoy global instruction files: if isolation works the agent never sees them (contract check).
    decoys: dict[str, str] = {}  # noqa: RUF012 - read-only class data

    def invocation(self, prompt: str, ctx: RunContext) -> Invocation:
        raise NotImplementedError

    def parse(self, stream: str, stderr: str = "") -> ParsedStream:
        raise NotImplementedError

    def version_argv(self) -> list[str]:
        return [self.binary, "--version"]


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def json_lines(text: str) -> Iterator[dict[str, Any]]:
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def relpath(path: str) -> str:
    """Repository-relative POSIX path for an absolute path inside the sandbox work directory."""
    p = path.replace("\\", "/")
    for prefix in (WORKDIR + "/", "./"):
        if p.startswith(prefix):
            p = p[len(prefix) :]
    return p.lstrip("/") if p.startswith(WORKDIR) else p


def truncate(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… [{len(text) - limit} more characters]"
