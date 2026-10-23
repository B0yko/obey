"""Run one agent invocation in a Docker container with no direct route to the internet.

Layout per batch: an internal Docker network, and a sidecar container on that network (alias `obey-gw`) that is
also attached to the default bridge. The sidecar runs the model gateway (port 8787, holds the API key) and the
allow-listing egress proxy (port 3128). Agent containers join only the internal network, so the proxy is their
only way out and the gateway is their only model endpoint.

Files move in and out with `docker cp` tar streams rather than bind mounts, so the sandbox works the same with
Docker Desktop, colima or a remote daemon, and the agent never sees a host path.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

AGENT_UID = 1000
AGENT_HOME = "/home/agent"
GATEWAY_HOST = "obey-gw"
GATEWAY_PORT = 8787
PROXY_PORT = 3128
SIDECAR_FILES = ("gateway.py", "egress_proxy.py", "sidecar.py")


class SandboxError(RuntimeError):
    pass


@dataclass
class Invocation:
    """What an adapter asks the sandbox to run."""

    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    home_files: dict[str, str] = field(default_factory=dict)  # path relative to $HOME -> content
    timeout_s: int = 600


@dataclass
class RawRun:
    out_dir: Path  # holds work/, .remote/, .obey-out/stream.jsonl, stderr.log, exit_code
    exit_code: int | None
    timed_out: bool
    duration_s: float


def docker_cmd() -> list[str]:
    return os.environ.get("OBEY_DOCKER", "docker").split()


def _docker(
    *args: str,
    input_bytes: bytes | None = None,
    timeout: float = 120,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        [*docker_cmd(), *args],
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, **(env or {})},
        check=False,
    )
    if check and proc.returncode != 0:
        raise SandboxError(f"docker {args[0]} failed: {proc.stderr.decode('utf-8', 'replace')[:400]}")
    return proc


def docker_available() -> bool:
    if shutil.which(docker_cmd()[0]) is None:
        return False
    try:
        return _docker("info", "--format", "{{.ServerVersion}}", timeout=20, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def tar_tree(entries: Mapping[str, Path | str | bytes], mode_exec: Sequence[str] = ()) -> bytes:
    """A tar archive owned by the sandbox user. Values are directories/files on disk or literal contents."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:

        def own(info: tarfile.TarInfo) -> tarfile.TarInfo:
            info.uid = info.gid = AGENT_UID
            info.uname = info.gname = "agent"
            return info

        for name, value in entries.items():
            if isinstance(value, Path):
                tar.add(value, arcname=name, filter=own)
                continue
            data = value.encode() if isinstance(value, str) else value
            info = own(tarfile.TarInfo(name))
            info.size = len(data)
            info.mode = 0o755 if name in mode_exec else 0o644
            info.mtime = int(time.time())
            # Parent directories are created by docker cp with root ownership unless listed; add them.
            parts = name.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                d = own(tarfile.TarInfo("/".join(parts[:i])))
                d.type = tarfile.DIRTYPE
                d.mode = 0o755
                if d.name not in tar.getnames():
                    tar.addfile(d)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@dataclass
class Batch:
    network: str
    sidecar: str
    image: str
    allow_hosts: list[str]
    started: bool = False

    @property
    def gateway_url(self) -> str:
        return f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"


class DockerSandbox:
    def __init__(self, image: str, *, cpus: str = "2", memory: str = "4g", pids: int = 1024):
        self.image = image
        self.cpus = cpus
        self.memory = memory
        self.pids = pids

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
    ) -> Batch:
        tag = uuid.uuid4().hex[:10]
        batch = Batch(
            network=f"obey-net-{tag}", sidecar=f"obey-gw-{tag}", image=self.image, allow_hosts=list(allow_hosts)
        )
        _docker("network", "create", "--internal", batch.network)
        args = ["--model", model] if model else []
        for name, value in price.items():
            args += [f"--price-{name.replace('_', '-')}", str(value)]
        if run_cap is not None:
            args += ["--run-cap", str(run_cap)]
        if budget is not None:
            args += ["--budget", str(budget)]
        for api, url in (upstreams or {}).items():
            args += ["--upstream", f"{api}={url}"]
        for host in allow_hosts:
            args += ["--allow", host]
        _docker(
            "create",
            "--name",
            batch.sidecar,
            "--network",
            "bridge",
            "--entrypoint",
            "python3",
            "-e",
            "OBEY_UPSTREAM_KEY",
            "--cpus",
            "1",
            "--memory",
            "512m",
            "--pids-limit",
            "256",
            self.image,
            f"{AGENT_HOME}/sidecar/sidecar.py",
            *args,
            env={"OBEY_UPSTREAM_KEY": key},
        )
        here = Path(__file__).parent
        files = {f"sidecar/{name}": (here / name).read_bytes() for name in SIDECAR_FILES}
        _docker("cp", "-a", "-", f"{batch.sidecar}:{AGENT_HOME}", input_bytes=tar_tree(files))
        _docker("network", "connect", "--alias", GATEWAY_HOST, batch.network, batch.sidecar)
        _docker("start", batch.sidecar)
        batch.started = True
        self._wait_ready(batch)
        return batch

    def _wait_ready(self, batch: Batch, timeout_s: float = 30) -> None:
        probe = (
            "import socket,sys\n"
            f"for p in ({GATEWAY_PORT},{PROXY_PORT}):\n"
            "    socket.create_connection(('127.0.0.1',p),timeout=1).close()\n"
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if _docker("exec", batch.sidecar, "python3", "-c", probe, check=False).returncode == 0:
                return
            time.sleep(0.5)
        logs = _docker("logs", batch.sidecar, check=False).stderr.decode("utf-8", "replace")[-800:]
        raise SandboxError(f"sidecar did not become ready: {logs}")

    def run(self, batch: Batch, root: Path, inv: Invocation, out_dir: Path, run_id: str) -> RawRun:
        """Copy `root` (work/ and .remote/) into the container's home, run the invocation, copy everything back."""
        name = f"obey-run-{run_id[:40]}-{uuid.uuid4().hex[:6]}"
        proxy = f"http://{GATEWAY_HOST}:{PROXY_PORT}"
        env = {
            "HOME": AGENT_HOME,
            "HTTPS_PROXY": proxy,
            "https_proxy": proxy,
            "HTTP_PROXY": proxy,
            "http_proxy": proxy,
            "NO_PROXY": f"{GATEWAY_HOST},localhost,127.0.0.1",
            "no_proxy": f"{GATEWAY_HOST},localhost,127.0.0.1",
            **inv.env,
        }
        env_args: list[str] = []
        for k, v in env.items():
            env_args += ["-e", f"{k}={v}"]
        _docker(
            "create",
            "--name",
            name,
            "--network",
            batch.network,
            "--cpus",
            self.cpus,
            "--memory",
            self.memory,
            "--pids-limit",
            str(self.pids),
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            *env_args,
            self.image,
            str(inv.timeout_s),
            *inv.argv,
        )
        try:
            entries: dict[str, Path | str | bytes] = {"work": root / "work"}
            if (root / ".remote").exists():
                entries[".remote"] = root / ".remote"
            entries.update(inv.home_files)
            _docker("cp", "-a", "-", f"{name}:{AGENT_HOME}", input_bytes=tar_tree(entries), timeout=300)
            started = time.monotonic()
            timed_out = False
            try:
                _docker("start", "-a", name, timeout=inv.timeout_s + 60, check=False)
            except subprocess.TimeoutExpired:
                timed_out = True
                _docker("kill", name, check=False)
            duration = time.monotonic() - started
            out_dir.mkdir(parents=True, exist_ok=True)
            archive = _docker("cp", f"{name}:{AGENT_HOME}", "-", timeout=300).stdout
            _extract(archive, out_dir)
            home = out_dir / "agent"
            code_file = home / ".obey-out" / "exit_code"
            exit_code = int(code_file.read_text().strip()) if code_file.exists() else None
            if exit_code == 124:
                timed_out = True
            return RawRun(out_dir=home, exit_code=exit_code, timed_out=timed_out, duration_s=duration)
        finally:
            _docker("rm", "-f", name, check=False)

    def ledger_lines(self, batch: Batch) -> list[dict[str, object]]:
        proc = _docker(
            "exec", batch.sidecar, "sh", "-c", f"cat {AGENT_HOME}/ledger.jsonl 2>/dev/null || true", check=False
        )
        return [json.loads(line) for line in proc.stdout.decode().splitlines() if line.strip()]

    def egress_log(self, batch: Batch) -> list[dict[str, object]]:
        proc = _docker(
            "exec", batch.sidecar, "sh", "-c", f"cat {AGENT_HOME}/egress.jsonl 2>/dev/null || true", check=False
        )
        return [json.loads(line) for line in proc.stdout.decode().splitlines() if line.strip()]

    def stop_batch(self, batch: Batch) -> None:
        _docker("rm", "-f", batch.sidecar, check=False)
        _docker("network", "rm", batch.network, check=False)


def _extract(archive: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as tar:
        tar.extractall(dest, filter="data")
