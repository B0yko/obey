from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

_real_connect = socket.socket.connect


def _guarded_connect(self: socket.socket, address: Any) -> Any:
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and (host in ("127.0.0.1", "::1", "localhost") or host.startswith("/")):
        return _real_connect(self, address)
    raise RuntimeError(f"network access blocked in tests: {address!r}")


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """Block outbound sockets unless a test is marked `network`."""
    if request.node.get_closest_marker("network"):
        yield
        return
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = _real_connect  # type: ignore[method-assign]
