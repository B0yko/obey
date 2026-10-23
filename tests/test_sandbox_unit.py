"""Sandbox behaviour that needs no Docker: a batch that fails to start leaves no sidecar (it holds the key)."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from obey_cli.runner import sandbox


def test_failed_start_removes_the_sidecar_and_network(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        if args[0] == "start":
            raise subprocess.CalledProcessError(1, ["docker", *args])
        return subprocess.CompletedProcess(list(args), 0, b"", b"")

    monkeypatch.setattr(sandbox, "_docker", fake)
    box = sandbox.DockerSandbox("obey-sandbox:test")
    with pytest.raises(subprocess.CalledProcessError):
        box.start_batch(key="k", model=None, price={}, allow_hosts=[], run_cap=None, budget=None)
    assert calls[-2][:2] == ("rm", "-f") and calls[-1][:2] == ("network", "rm")
