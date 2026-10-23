from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from obey_cli.runner import egress_proxy, gateway

SEEN: list[dict[str, Any]] = []


class FakeUpstream(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "body": body,
                "x-api-key": self.headers.get("x-api-key"),
            }
        )
        if body.get("stream"):
            events = [
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 90}},
                },
                {"type": "message_delta", "usage": {"output_tokens": 25}},
            ]
            data = b"".join(b"event: x\ndata: " + json.dumps(e).encode() + b"\n\n" for e in events)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        data = json.dumps(
            {
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 7, "cost": 0.0042},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _serve(server: ThreadingHTTPServer) -> None:
    threading.Thread(target=server.serve_forever, daemon=True).start()


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[tuple[str, Path, gateway.Config]]:
    SEEN.clear()
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    _serve(upstream)
    base = f"http://127.0.0.1:{upstream.server_address[1]}"
    ledger = tmp_path / "ledger.jsonl"
    cfg = gateway.Config(
        "real-key",
        "pinned/model",
        str(ledger),
        {"prompt": 1e-6, "completion": 2e-6, "cache_read": 1e-7},
        run_cap=0.004,
        budget=None,
        upstreams={"anthropic": base + "/api", "openai": base + "/api/v1"},
    )
    gw = gateway.make_server("127.0.0.1:0", cfg)
    _serve(gw)
    yield f"http://127.0.0.1:{gw.server_address[1]}", ledger, cfg
    gw.shutdown()
    upstream.shutdown()


def test_anthropic_stream_is_pinned_metered_and_keyed(stack: tuple[str, Path, gateway.Config]) -> None:
    url, ledger, _ = stack
    resp = httpx.post(
        f"{url}/r/run1/anthropic/v1/messages",
        json={"model": "claude-x", "stream": True},
        headers={"x-api-key": "dummy", "Authorization": "Bearer dummy"},
    )
    assert resp.status_code == 200 and b"message_delta" in resp.content
    seen = SEEN[-1]
    assert seen["path"] == "/api/v1/messages"
    assert seen["auth"] == "Bearer real-key" and seen["x-api-key"] is None
    assert seen["body"]["model"] == "pinned/model"
    (entry,) = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert (entry["input_tokens"], entry["cache_read_tokens"], entry["output_tokens"]) == (100, 90, 25)
    assert entry["cost_usd"] == pytest.approx(10 * 1e-6 + 90 * 1e-7 + 25 * 2e-6)
    assert entry["cost_source"] == "price_table"


def test_openai_json_uses_provider_cost_and_run_cap(stack: tuple[str, Path, gateway.Config]) -> None:
    url, _ledger, cfg = stack
    resp = httpx.post(f"{url}/r/run2/openai/chat/completions", json={"model": "x", "messages": []})
    assert resp.json()["choices"][0]["message"]["content"] == "hi"
    assert SEEN[-1]["body"]["usage"] == {"include": True}
    assert cfg.spent["run2"] == pytest.approx(0.0042)
    blocked = httpx.post(f"{url}/r/run2/openai/chat/completions", json={"model": "x", "messages": []})
    assert blocked.status_code == 402 and "per-run cap" in blocked.text
    other = httpx.post(f"{url}/r/run3/openai/chat/completions", json={"model": "x", "messages": []})
    assert other.status_code == 200


def test_gateway_refuses_browser_and_bad_paths(stack: tuple[str, Path, gateway.Config]) -> None:
    url, _, cfg = stack
    assert (
        httpx.post(
            f"{url}/r/run1/anthropic/v1/messages", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert httpx.post(f"{url}/v1/messages", json={}).status_code == 404
    cfg.allowed_hosts = ["obey-gw:8787"]
    assert httpx.post(f"{url}/r/run1/anthropic/v1/messages", json={}).status_code == 403


def test_host_allow_list() -> None:
    allow = ["registry.npmjs.org", "*.pythonhosted.org"]
    assert egress_proxy.host_allowed("registry.npmjs.org", 443, allow)
    assert egress_proxy.host_allowed("files.pythonhosted.org", 443, allow)
    assert not egress_proxy.host_allowed("pythonhosted.org", 443, allow)
    assert not egress_proxy.host_allowed("registry.npmjs.org", 80, allow)
    assert not egress_proxy.host_allowed("evil.example", 443, allow)
    assert not egress_proxy.host_allowed("registry.npmjs.org.evil.example", 443, allow)


def test_proxy_tunnels_allowed_and_refuses_others(tmp_path: Path) -> None:
    log = tmp_path / "egress.jsonl"

    async def scenario() -> tuple[bytes, bytes, bytes]:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.write(await reader.read(100))
            await writer.drain()
            writer.close()

        target = await asyncio.start_server(echo, "127.0.0.1", 0)
        tport = target.sockets[0].getsockname()[1]
        proxy = egress_proxy.Proxy(["127.0.0.1"], str(log), ports=(tport,))
        server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
        pport = server.sockets[0].getsockname()[1]

        async def connect(line: bytes) -> bytes:
            r, w = await asyncio.open_connection("127.0.0.1", pport)
            w.write(line)
            await w.drain()
            head = await r.readuntil(b"\r\n\r\n")
            if b" 200 " in head:
                w.write(b"ping")
                await w.drain()
                head += await r.read(100)
            w.close()
            return head

        ok = await connect(f"CONNECT 127.0.0.1:{tport} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        denied = await connect(b"CONNECT evil.example:443 HTTP/1.1\r\n\r\n")
        plain = await connect(b"GET http://evil.example/ HTTP/1.1\r\n\r\n")
        server.close()
        target.close()
        return ok, denied, plain

    ok, denied, plain = asyncio.run(scenario())
    assert ok.endswith(b"ping") and b" 200 " in ok
    assert b" 403 " in denied and b" 405 " in plain
    events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
    assert events == ["allowed", "refused", "refused"]
