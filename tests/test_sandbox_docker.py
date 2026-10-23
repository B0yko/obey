"""Live sandbox isolation checks. Run with OBEY_DOCKER_TESTS=1 on a machine with Docker and network access."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from obey_cli.runner.sandbox import Batch, DockerSandbox, Invocation

pytestmark = [
    pytest.mark.docker,
    pytest.mark.network,
    pytest.mark.skipif(os.environ.get("OBEY_DOCKER_TESTS") != "1", reason="set OBEY_DOCKER_TESTS=1"),
]
IMAGE = os.environ.get("OBEY_SANDBOX_IMAGE", "obey-sandbox:0.1.0")


@pytest.fixture(scope="module")
def batch() -> Iterator[tuple[DockerSandbox, Batch]]:
    box = DockerSandbox(IMAGE)
    b = box.start_batch(key="not-a-real-key", model=None, price={}, allow_hosts=["pypi.org"], run_cap=None, budget=None)
    yield box, b
    box.stop_batch(b)


SCRIPT = r"""
set +e
probe() { python3 - "$@" <<'PY'
import sys, urllib.request
url = sys.argv[1]
headers = {"Authorization": f"Bearer {sys.argv[2]}"} if len(sys.argv) > 2 else {}
try:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
        print(r.status)
except Exception as e:
    print(type(e).__name__, getattr(e, "code", ""), str(e)[:80].replace("\n", " "))
PY
}
echo "allowed: $(probe https://pypi.org/simple/pip/)"
echo "denied: $(probe https://example.com/)"
echo "gateway: $(probe http://obey-gw:8787/r/t1/openai/models obey-dummy-token)"
echo "no-token: $(probe http://obey-gw:8787/r/t1/openai/models)"
echo "direct: $(env -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy python3 - <<'PY'
import socket
try:
    socket.create_connection(("1.1.1.1", 443), timeout=5).close()
    print("connected")
except OSError as e:
    print("blocked", type(e).__name__)
PY
)"
echo "home: $(ls -A $HOME | tr '\n' ' ')"
echo "key: ${OBEY_UPSTREAM_KEY:-absent} ${OPENROUTER_API_KEY:-absent}"
"""


def test_egress_is_allow_listed_and_key_stays_outside(batch: tuple[DockerSandbox, Batch], tmp_path: Path) -> None:
    box, b = batch
    root = tmp_path / "probe"
    (root / "work").mkdir(parents=True)
    (root / "work" / "README.md").write_text("x\n")
    raw = box.run(
        b,
        root,
        Invocation(argv=["sh", "-c", SCRIPT], timeout_s=120),
        tmp_path / "out",
        "isolation",
        copy_back_work=True,
    )
    assert raw.root is not None
    out = (raw.out_dir / "stream.jsonl").read_text()
    lines = dict(line.split(": ", 1) for line in out.strip().splitlines())
    assert lines["allowed"] == "200"
    assert lines["denied"].startswith(("URLError", "HTTPError", "ProxyError", "OSError")), lines["denied"]
    assert lines["gateway"] == "200"
    assert lines["no-token"].startswith("HTTPError 401")
    assert lines["direct"].startswith("blocked")
    assert lines["key"] == "absent absent"
    assert (raw.root / "work" / "README.md").read_text() == "x\n"
    events = box.egress_log(b)
    assert {"event": "allowed", "host": "pypi.org"}.items() <= next(
        e for e in events if e["event"] == "allowed"
    ).items()
    assert any(e["event"] == "refused" and e.get("host") == "example.com" for e in events)
