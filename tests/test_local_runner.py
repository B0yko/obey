"""--unsafe-local: host paths and the agent's own sandbox reach the adapter, and a timeout stops everything it started."""

from __future__ import annotations

import os
from pathlib import Path

from obey_cli.runner.agents.base import Adapter, ParsedStream, RunContext, json_lines
from obey_cli.runner.core import RunSpec, execute
from obey_cli.runner.local import LocalSandbox
from obey_cli.runner.sandbox import Invocation

DEMO = Path(__file__).parents[1] / "study" / "repos" / "ts-web"


class Scripted(Adapter):
    name = "scripted"
    binary = "bash"

    def __init__(self, script: str, timeout_s: int = 60) -> None:
        self.script = script
        self.timeout_s = timeout_s
        self.contexts: list[RunContext] = []

    def invocation(self, prompt: str, ctx: RunContext) -> Invocation:
        self.contexts.append(ctx)
        return Invocation(argv=["bash", "-c", self.script], timeout_s=self.timeout_s)

    def parse(self, stream: str, stderr: str = "", workdir: str = "") -> ParsedStream:
        out = ParsedStream(events=list(json_lines(stream)))
        out.final_message = "done"
        return out


def _run(adapter: Adapter, run_id: str) -> dict:
    box = LocalSandbox()
    batch = box.start_batch(key="unused", model=None, price={}, allow_hosts=[], run_cap=None, budget=None)
    try:
        return execute(adapter, RunSpec(run_id=run_id, prompt="x", source=DEMO), box=box, batch=batch, model="none")
    finally:
        box.stop_batch(batch)


def test_local_runs_get_host_paths_and_the_local_flag() -> None:
    script = 'printf \'{"type":"shell","command":"pwd","cwd":"%s","home":"%s"}\\n\' "$PWD" "$HOME"\necho x > new.txt'
    adapter = Scripted(script)
    record = _run(adapter, "local-paths")
    ctx = adapter.contexts[0]
    assert ctx.local and not ctx.workdir.startswith("/srv/") and not ctx.home.startswith("/home/agent")
    event = record["events"][0]
    assert os.path.realpath(event["cwd"]) == os.path.realpath(ctx.workdir)
    assert os.path.realpath(event["home"]) == os.path.realpath(ctx.home)
    assert record["status"] == "ok" and "+++ b/new.txt" in record["diff"]


def test_a_timeout_stops_the_agents_background_processes(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    adapter = Scripted(f"sleep 60 & echo $! > {pidfile}; wait", timeout_s=1)
    record = _run(adapter, "local-timeout")
    assert record["status"] == "timeout"
    pid = int(pidfile.read_text())
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive
