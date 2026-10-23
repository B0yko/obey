"""--unsafe-local: run the agent on this machine without a container.

For users without Docker. Each run gets a fresh copy of the tracked files in a temporary directory with no git
remotes, an empty HOME, no credential environment variables and no git credential helpers. The agent's own sandbox
mode is switched on where it has one (Claude Code, Codex CLI, Gemini CLI). The model gateway runs in this process on
127.0.0.1, so the API key still never reaches the agent. There is no egress allow-list: commands the agent runs can
reach the network. Probes for "never commit" and "never push" are refused in this mode.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obey_cli.runner import gateway
from obey_cli.runner.sandbox import Invocation, RawRun
from obey_cli.runner.workspace import collect_end_state

KEEP_ENV = ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR")
REFUSED_TYPES = ("no_commit", "no_push")
WARNING = (
    "obey: --unsafe-local runs the agent directly on this machine. It works in a temporary copy with an empty HOME and "
    "no credentials, and turns on the agent's own sandbox where it has one, but commands it runs can still reach the "
    "network and anything your user can read. Prefer the default container sandbox."
)


@dataclass
class LocalBatch:
    server: Any
    config: gateway.Config
    ledger_path: Path
    gateway_url: str
    homes: list[Path] = field(default_factory=list)


class LocalSandbox:
    def start_batch(
        self,
        *,
        key: str,
        model: str | None,
        price: Mapping[str, float],
        allow_hosts: Sequence[str],
        run_cap: float | None,
        budget: float | None,
        upstreams: Mapping[str, str] | None = None,
    ) -> LocalBatch:
        ledger_path = Path(tempfile.mkdtemp(prefix="obey-ledger-")) / "ledger.jsonl"
        config = gateway.Config(
            key, model, str(ledger_path), dict(price), run_cap, budget, {**gateway.UPSTREAMS, **(upstreams or {})}
        )
        server = gateway.make_server("127.0.0.1:0", config)
        port = server.server_address[1]
        config.allowed_hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return LocalBatch(server=server, config=config, ledger_path=ledger_path, gateway_url=f"http://127.0.0.1:{port}")

    def run(
        self,
        batch: LocalBatch,
        root: Path,
        inv: Invocation,
        out_dir: Path,
        run_id: str,
        *,
        base_sha: str | None = None,
        copy_back_work: bool = False,
    ) -> RawRun:
        work = root / "work"
        home = root / "home"
        home.mkdir(parents=True, exist_ok=True)
        for rel, content in inv.home_files.items():
            target = home / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content if isinstance(content, str) else content.decode(), encoding="utf-8")
        # Strip the copy's remotes and credential helpers: nothing to push to, nothing to log in with.
        for remote in subprocess.run(
            ["git", "remote"], cwd=work, capture_output=True, text=True, check=False
        ).stdout.split():
            subprocess.run(["git", "remote", "remove", remote], cwd=work, check=False)
        env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
        env.update(
            {
                "HOME": str(home),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
                "TERM": "dumb",
                **inv.env,
            }
        )
        (home / ".gitconfig").write_text(
            "[user]\n\tname = Developer\n\temail = dev@example.com\n[credential]\n\thelper =\n", encoding="utf-8"
        )
        out = out_dir / ".obey-out"
        out.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        timed_out = False
        (home / ".obey-out").mkdir(exist_ok=True)
        code: int | None = None
        with (out / "stream.jsonl").open("wb") as stdout, (out / "stderr.log").open("wb") as stderr:
            # A session of its own, so a timeout (or the end of the run) also stops what the agent left running.
            proc = subprocess.Popen(
                inv.argv,
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                code = proc.wait(timeout=inv.timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                _kill_group(proc)
        duration = time.monotonic() - started
        if code is not None:
            (out / "exit_code").write_text(str(code), encoding="utf-8")
        if base_sha:
            state = collect_end_state(work, base_sha, None)
            (out / "end-state.json").write_text(
                json.dumps(
                    {
                        "diff": state.diff,
                        "commits": state.commits,
                        "pushed_refs": [],
                        "diff_truncated": state.diff_truncated,
                    }
                )
            )
        hook_log = Path(inv.env.get("OBEY_HOOK_LOG", ""))
        if hook_log.name and hook_log.exists():
            (out / "hook-log.jsonl").write_bytes(hook_log.read_bytes())
        return RawRun(
            root=root if copy_back_work else None, out_dir=out, exit_code=code, timed_out=timed_out, duration_s=duration
        )

    def ledger_lines(self, batch: LocalBatch) -> list[dict[str, Any]]:
        if not batch.ledger_path.exists():
            return []
        return [json.loads(line) for line in batch.ledger_path.read_text().splitlines() if line.strip()]

    def egress_log(self, batch: LocalBatch) -> list[dict[str, Any]]:
        return []

    def stop_batch(self, batch: LocalBatch) -> None:
        batch.server.shutdown()
        batch.server.server_close()


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
