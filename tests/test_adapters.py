"""Adapters against streams recorded from the real CLIs (see fixtures/streams and eval/record_runs.py)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from obey_cli.runner import agents
from obey_cli.runner.agents.base import DUMMY_TOKEN, WORKDIR, RunContext, relpath

STREAMS = Path(__file__).parents[1] / "fixtures" / "streams"
CTX = RunContext(run_id="r1", model="vendor/model", gateway_url="http://obey-gw:8787")


def parse(agent: str, name: str) -> agents.ParsedStream:
    return agents.get(agent).parse((STREAMS / agent / f"{name}.jsonl").read_text())


@pytest.mark.parametrize("agent", ["claude-code", "codex", "copilot", "opencode"])
def test_load_probe_final_message(agent: str) -> None:
    assert parse(agent, "load").final_message.strip().endswith("rules-loaded")


@pytest.mark.parametrize("agent", ["claude-code", "copilot", "opencode"])
def test_hook_denial_is_visible_in_stream(agent: str) -> None:
    parsed = parse(agent, "hook")
    shells = [e for e in parsed.events if e["type"] == "shell"]
    assert shells and "status" in shells[0]["command"]
    assert any(e["type"] == "denied" and e["source"] == "hook" for e in parsed.events)
    # A blocked command never ran: checkers must not count it (the enforcement study depends on it).
    assert shells[0].get("denied") is True


def test_codex_hook_denial_only_in_message() -> None:
    # Codex emits no command item for a call its PreToolUse hook blocked; obey relies on the hook log instead.
    parsed = parse("codex", "hook")
    assert not [e for e in parsed.events if e["type"] == "shell"]
    assert "blocked by the PreToolUse hook" in parsed.final_message


def test_claude_code_edits_and_exit_codes() -> None:
    parsed = parse("claude-code", "py-rename-column")
    edits = [e for e in parsed.events if e["type"] == "edit"]
    assert edits and all(not e["path"].startswith("/") for e in edits)
    assert all(e["exit_code"] == 0 for e in parsed.events if e["type"] == "shell")
    assert [e["seq"] for e in parsed.events] == list(range(len(parsed.events)))


def test_codex_shell_exit_codes_and_unwrapping() -> None:
    parsed = parse("codex", "py-parse-amount")
    shells = [e for e in parsed.events if e["type"] == "shell"]
    assert not any(e["command"].startswith("/bin/bash -lc") for e in shells)
    assert {0, 2}.issubset({e["exit_code"] for e in shells})


def test_opencode_write_and_copilot_shell_edits() -> None:
    oc = parse("opencode", "py-rename-column")
    assert any(e["type"] == "write" and e["path"].startswith("migrations/") for e in oc.events)
    cp = parse("copilot", "py-rename-column")
    assert any("sed -i" in e["command"] for e in cp.events if e["type"] == "shell")


def test_relpath() -> None:
    assert relpath(f"{WORKDIR}/src/a.py") == "src/a.py"
    assert relpath("src/a.py") == "src/a.py"
    assert relpath("./src/a.py") == "src/a.py"


def test_invocations_isolate_configuration() -> None:
    cc = agents.get("claude-code").invocation("p", CTX)
    assert cc.argv[:2] == ["claude", "-p"] and "stream-json" in cc.argv and "--verbose" in cc.argv
    assert cc.env["CLAUDE_CONFIG_DIR"].endswith(".obey-claude") and cc.env["ANTHROPIC_API_KEY"] == ""
    assert cc.env["ANTHROPIC_BASE_URL"] == "http://obey-gw:8787/r/r1/anthropic"
    codex = agents.get("codex").invocation("p", RunContext("r1", "m", "http://obey-gw:8787", enforced=True))
    assert "--dangerously-bypass-hook-trust" in codex.argv and codex.env["CODEX_HOME"].endswith(".obey-codex")
    assert 'trust_level = "trusted"' in codex.home_files[".obey-codex/config.toml"]
    oc = agents.get("opencode").invocation("p", CTX)
    assert oc.env["OPENCODE_DISABLE_CLAUDE_CODE"] == "1" and "--auto" in oc.argv
    assert json.loads(oc.env["OPENCODE_CONFIG_CONTENT"])["provider"]["openrouter"]["options"]["baseURL"].endswith(
        "/openai"
    )
    cp = agents.get("copilot").invocation("p", CTX)
    assert cp.env["COPILOT_PROVIDER_BASE_URL"].endswith("/r/r1/openai") and "--allow-all-tools" in cp.argv
    gm = agents.get("gemini").invocation("p", CTX)
    assert gm.env["GOOGLE_GEMINI_BASE_URL"].startswith("http://127.0.0.1:")
    for inv in (cc, codex, oc, cp, gm):
        assert not any(v.startswith("sk-") for v in inv.env.values())


def test_gemini_reaches_the_gateway_through_an_allowed_forwarder() -> None:
    from obey_cli.runner import sidecar

    gm = agents.get("gemini").invocation("p", CTX)
    base = urlsplit(gm.env["GOOGLE_GEMINI_BASE_URL"])
    assert base.path == "/r/r1/gemini" and base.netloc in sidecar.ALLOWED_HOSTS
    assert gm.env["OBEY_LOCAL_FORWARD"] == str(base.port)
    assert gm.env["GEMINI_API_KEY"] == DUMMY_TOKEN and gm.argv[-2:] == ["-m", "vendor/model"]


def test_unknown_agent() -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        agents.get("nope")


def test_gemini_marks_a_hook_blocked_command_as_not_run() -> None:
    stream = "\n".join(
        json.dumps(obj)
        for obj in (
            {
                "type": "tool_use",
                "tool_name": "run_shell_command",
                "tool_id": "t1",
                "parameters": {"command": "git push"},
            },
            {"type": "tool_result", "tool_id": "t1", "status": "error", "output": "Hook denied: obey: never push"},
        )
    )
    parsed = agents.get("gemini").parse(stream)
    shell = next(e for e in parsed.events if e["type"] == "shell")
    assert shell["denied"] is True and any(e["type"] == "denied" for e in parsed.events)
