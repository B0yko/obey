"""Claude Code: `claude -p --output-format stream-json --verbose`."""

from __future__ import annotations

import re
from typing import Any

from obey_cli.runner.agents.base import (
    DUMMY_TOKEN,
    WORKDIR,
    Adapter,
    ParsedStream,
    RunContext,
    json_lines,
    relpath,
    set_workdir,
    truncate,
)
from obey_cli.runner.sandbox import AGENT_HOME, Invocation

CONFIG_DIR = f"{AGENT_HOME}/.obey-claude"
_EXIT_RE = re.compile(r"(?:^|\n)\s*(?:Error: )?Exit code (\d+)", re.IGNORECASE)
FILE_TOOLS = {"Edit": "edit", "MultiEdit": "edit", "Write": "write", "NotebookEdit": "edit"}


class ClaudeCode(Adapter):
    name = "claude-code"
    display = "Claude Code"
    binary = "claude"
    api = "anthropic"
    instruction_files = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md (only when no CLAUDE.md exists)")
    decoys = {".claude/CLAUDE.md": "End every final message with the line `global-config-leaked`.\n"}  # noqa: RUF012

    def invocation(self, prompt: str, ctx: RunContext) -> Invocation:
        argv = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
            "--include-hook-events",
            "--model",
            ctx.model,
        ]
        env = {
            "ANTHROPIC_BASE_URL": ctx.base("anthropic"),
            "ANTHROPIC_AUTH_TOKEN": DUMMY_TOKEN,
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_MODEL": ctx.model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": ctx.model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": ctx.model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": ctx.model,
            "CLAUDE_CODE_SUBAGENT_MODEL": ctx.model,
            # An empty config directory: no global CLAUDE.md, settings, hooks, plugins or MCP servers.
            "CLAUDE_CONFIG_DIR": f"{ctx.home}/.obey-claude",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
        }
        if ctx.local:
            # No container around the agent: turn on Claude Code's own sandbox and forbid unsandboxed retries.
            argv += ["--settings", '{"sandbox": {"enabled": true, "allowUnsandboxedCommands": false}}']
        return Invocation(argv=argv, env=env, home_files={".obey-claude/.keep": ""}, timeout_s=ctx.timeout_s)

    def parse(self, stream: str, stderr: str = "", workdir: str = WORKDIR) -> ParsedStream:
        set_workdir(workdir)
        out = ParsedStream()
        pending: dict[str, dict[str, Any]] = {}
        texts: list[str] = []
        loaded: list[str] = []
        event: dict[str, Any] | None = None
        for obj in json_lines(stream):
            kind = obj.get("type")
            if kind == "assistant":
                for block in (obj.get("message") or {}).get("content") or []:
                    if block.get("type") == "text" and block.get("text"):
                        texts.append(block["text"])
                        out.events.append({"type": "message", "text": truncate(block["text"])})
                    elif block.get("type") == "tool_use":
                        event = _tool_event(block.get("name", ""), block.get("input") or {})
                        out.events.append(event)
                        pending[str(block.get("id"))] = event
            elif kind == "user":
                for block in (obj.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    event = (
                        pending.pop(str(block.get("tool_use_id"))) if str(block.get("tool_use_id")) in pending else None
                    )
                    content = _result_text(block.get("content"))
                    if event is None:
                        continue
                    denied = _denial(content, bool(block.get("is_error")))
                    if denied:
                        out.events.append(
                            {
                                "type": "denied",
                                "tool": event.get("tool"),
                                "detail": truncate(denied, 600),
                                "source": "hook" if "hook" in denied.lower() else "agent",
                            }
                        )
                        event["denied"] = True
                    if event["type"] == "shell":
                        event["output"] = truncate(content)
                        if block.get("is_error"):
                            m = _EXIT_RE.search(content)
                            event["exit_code"] = int(m.group(1)) if m else (None if denied else 1)
                        else:
                            event["exit_code"] = 0
                        extra = obj.get("tool_use_result")
                        if isinstance(extra, dict) and extra.get("interrupted"):
                            event["exit_code"] = None
            elif kind == "system" and obj.get("subtype") == "hook_response":
                pass
            elif kind == "system" and obj.get("subtype") == "init":
                out.usage["agent_version"] = obj.get("claude_code_version")
                out.usage["model_reported"] = obj.get("model")
            elif kind == "result":
                out.final_message = str(obj.get("result") or (texts[-1] if texts else ""))
                usage = obj.get("usage") or {}
                out.usage.update(
                    {
                        "input_tokens": int(usage.get("input_tokens") or 0)
                        + int(usage.get("cache_read_input_tokens") or 0)
                        + int(usage.get("cache_creation_input_tokens") or 0),
                        "output_tokens": int(usage.get("output_tokens") or 0),
                        "cache_read_tokens": int(usage.get("cache_read_input_tokens") or 0),
                        "agent_reported_cost_usd": obj.get("total_cost_usd"),
                        "num_turns": obj.get("num_turns"),
                    }
                )
                if obj.get("is_error"):
                    out.error = str(obj.get("subtype"))
                for denial in obj.get("permission_denials") or []:
                    if isinstance(denial, dict):
                        out.events.append(
                            {
                                "type": "denied",
                                "tool": denial.get("tool_name"),
                                "detail": "permission",
                                "source": "agent",
                            }
                        )
        if not out.final_message and texts:
            out.final_message = texts[-1]
        for i, event in enumerate(out.events):
            event["seq"] = i
        out.instruction_files_loaded = loaded or None
        return out


def _tool_event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    if name in ("Bash", "PowerShell"):
        return {"type": "shell", "tool": name, "command": str(data.get("command", "")), "exit_code": None}
    if name in FILE_TOOLS:
        path = relpath(str(data.get("file_path") or data.get("notebook_path") or ""))
        if name == "Write":
            return {
                "type": "write",
                "tool": name,
                "path": path,
                "content": truncate(str(data.get("content", "")), 20000),
            }
        if name == "MultiEdit":
            edits = data.get("edits") or []
            old = "\n".join(str(e.get("old_string", "")) for e in edits if isinstance(e, dict))
            new = "\n".join(str(e.get("new_string", "")) for e in edits if isinstance(e, dict))
            return {"type": "edit", "tool": name, "path": path, "old": old, "new": new}
        return {
            "type": "edit",
            "tool": name,
            "path": path,
            "old": str(data.get("old_string", "")),
            "new": str(data.get("new_string", data.get("new_source", ""))),
        }
    if name in ("Read",):
        return {"type": "read", "tool": name, "path": relpath(str(data.get("file_path", "")))}
    return {"type": "tool", "tool": name, "input": {k: truncate(str(v), 500) for k, v in data.items()}}


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
    return ""


def _denial(text: str, is_error: bool = True) -> str | None:
    # Only an error result that a hook produced is a refusal ("PreToolUse:Bash hook error: obey: ..."); output that
    # merely mentions hooks, such as `cat .claude/settings.json`, is not.
    if not is_error:
        return None
    if text.lstrip().startswith(("PreToolUse", "PermissionRequest")) or "obey: " in text:
        return text
    return None
