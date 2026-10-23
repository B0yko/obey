from __future__ import annotations

import asyncio
import http.client
import json
import socket
import struct
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from obey_cli.runner import egress_proxy, gateway, sidecar
from obey_cli.runner.agents.base import DUMMY_TOKEN

SEEN: list[dict[str, Any]] = []
AUTH = {"Authorization": f"Bearer {gateway.DUMMY_TOKEN}"}


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
                "goog": self.headers.get_all("x-goog-api-key"),
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


class EdgeUpstream(BaseHTTPRequestHandler):
    """Answers the awkward way: no body, or a stream that dies half way."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        event = {"id": "x", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0007}}
        data = b"data: " + json.dumps(event).encode() + b"\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        if self.path.endswith("/responses"):  # promises more than it sends
            self.send_header("Content-Length", str(len(data) + 1000))
            self.end_headers()
            self.wfile.write(data)
        else:  # chunked, then cut off without the final chunk
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()
        self.connection.shutdown(socket.SHUT_RDWR)


def _serve(server: ThreadingHTTPServer) -> None:
    threading.Thread(target=server.serve_forever, daemon=True).start()


def _request(url: str, method: str, target: str, body: bytes | None = None, **headers: str) -> int:
    """Send the request target exactly as given (httpx would normalise `..` away) and return the status."""
    netloc = urlsplit(url).netloc
    conn = http.client.HTTPConnection(netloc)
    try:
        conn.request(method, target, body=body, headers={**AUTH, "Content-Type": "application/json", **headers})
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


def _raw(url: str, request: bytes) -> bytes:
    """Send raw bytes and read until the gateway closes the connection (a stall fails the test via the timeout)."""
    with socket.create_connection(("127.0.0.1", urlsplit(url).port or 0), timeout=5) as sock:
        sock.sendall(request)
        out = b""
        while chunk := sock.recv(65536):
            out += chunk
    return out


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
        upstreams={"anthropic": base + "/api", "openai": base + "/api/v1", "gemini": base + "/gem"},
    )
    gw = gateway.make_server("127.0.0.1:0", cfg)
    _serve(gw)
    yield f"http://127.0.0.1:{gw.server_address[1]}", ledger, cfg
    gw.shutdown()
    upstream.shutdown()


@pytest.fixture
def edge(tmp_path: Path) -> Iterator[tuple[str, gateway.Config]]:
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), EdgeUpstream)
    _serve(upstream)
    base = f"http://127.0.0.1:{upstream.server_address[1]}"
    cfg = gateway.Config("real-key", None, None, {}, None, None, {"openai": base + "/api/v1"})
    gw = gateway.make_server("127.0.0.1:0", cfg)
    _serve(gw)
    yield f"http://127.0.0.1:{gw.server_address[1]}", cfg
    gw.shutdown()
    upstream.shutdown()


def test_anthropic_stream_is_pinned_metered_and_keyed(stack: tuple[str, Path, gateway.Config]) -> None:
    url, ledger, _ = stack
    resp = httpx.post(
        f"{url}/r/run1/anthropic/v1/messages",
        json={"model": "claude-x", "stream": True},
        headers={"x-api-key": gateway.DUMMY_TOKEN, "Authorization": f"Bearer {gateway.DUMMY_TOKEN}"},
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
    resp = httpx.post(f"{url}/r/run2/openai/chat/completions", json={"model": "x", "messages": []}, headers=AUTH)
    assert resp.json()["choices"][0]["message"]["content"] == "hi"
    assert SEEN[-1]["body"]["usage"] == {"include": True}
    assert cfg.spent["run2"] == pytest.approx(0.0042)
    blocked = httpx.post(f"{url}/r/run2/openai/chat/completions", json={"model": "x", "messages": []}, headers=AUTH)
    assert blocked.status_code == 402 and "per-run cap" in blocked.text
    other = httpx.post(f"{url}/r/run3/openai/chat/completions", json={"model": "x", "messages": []}, headers=AUTH)
    assert other.status_code == 200


def test_gateway_refuses_browser_and_bad_paths(stack: tuple[str, Path, gateway.Config]) -> None:
    url, _, cfg = stack
    assert (
        httpx.post(
            f"{url}/r/run1/anthropic/v1/messages", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert httpx.post(f"{url}/v1/messages", json={}, headers=AUTH).status_code == 404
    cfg.allowed_hosts = ["obey-gw:8787"]
    assert httpx.post(f"{url}/r/run1/anthropic/v1/messages", json={}, headers=AUTH).status_code == 403


def test_gateway_requires_the_batch_token(stack: tuple[str, Path, gateway.Config]) -> None:
    url, _, cfg = stack
    body = {"model": "x", "messages": []}
    wrong = [{}, {"Authorization": "Bearer nope"}, {"x-api-key": "nope"}, {"Authorization": gateway.DUMMY_TOKEN}]
    for i, headers in enumerate(wrong):
        assert httpx.post(f"{url}/r/t{i}/openai/chat/completions", json=body, headers=headers).status_code == 401
    assert not SEEN
    cfg.token = "batch-token"
    assert httpx.post(f"{url}/r/t9/openai/chat/completions", json=body, headers=AUTH).status_code == 401
    right = [{"Authorization": "Bearer batch-token"}, {"x-api-key": "batch-token"}, {"x-goog-api-key": "batch-token"}]
    for i, headers in enumerate(right):
        assert httpx.post(f"{url}/r/u{i}/openai/chat/completions", json=body, headers=headers).status_code == 200
    assert len(SEEN) == 3 and all(seen["auth"] == "Bearer real-key" for seen in SEEN)


def test_default_token_is_what_the_agents_send() -> None:
    assert gateway.DUMMY_TOKEN == DUMMY_TOKEN
    assert gateway.Config("k", None, None, {}, None, None, {}).token == DUMMY_TOKEN


def test_cli_options_set_the_token_and_the_run_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[gateway.Config] = []

    class Done:
        def serve_forever(self) -> None:
            pass

    def fake_make_server(listen: str, config: gateway.Config) -> Any:
        made.append(config)
        return Done()

    monkeypatch.setenv("OBEY_UPSTREAM_KEY", "k")
    monkeypatch.setattr(gateway, "make_server", fake_make_server)
    assert gateway.main(["--token", "t", "--run-id", "a", "--run-id", "b"]) == 0
    assert gateway.main([]) == 0
    assert (made[0].token, made[0].run_ids) == ("t", {"a", "b"})
    assert (made[1].token, made[1].run_ids) == (DUMMY_TOKEN, None)


def test_run_ids_must_be_registered_by_the_host(stack: tuple[str, Path, gateway.Config]) -> None:
    url, _, cfg = stack

    def call(run_id: str) -> int:
        return httpx.post(
            f"{url}/r/{run_id}/openai/chat/completions", json={"model": "x", "messages": []}, headers=AUTH
        ).status_code

    cfg.register_run("run-a")
    assert call("run-b") == 403 and not SEEN
    assert call("run-a") == 200
    assert call("run-a") == 402  # the per-run cap holds ...
    assert call("run-a2") == 403 and len(SEEN) == 1  # ... and a new id in the URL does not reset it
    assert gateway.Config("k", None, None, {}, None, None, {}, run_ids=["x"]).known_run("x")
    assert not gateway.Config("k", None, None, {}, None, None, {}, run_ids=["x"]).known_run("y")


@pytest.mark.parametrize(
    ("method", "target"),
    [
        ("POST", "/r/a/openai/../../v1/key"),
        ("GET", "/r/a/anthropic/%2e%2e/v1/credits"),
        ("POST", "/r/a/openai/%2E%2E/%2e%2e/key"),
        ("POST", "/r/a/openai/chat/completions/../../key"),
        ("POST", "/r/a/openai/chat%2fcompletions"),
        ("POST", "/r/a/openai/%252e%252e/key"),
        ("POST", "/r/a/openai//chat/completions"),
        ("POST", "/r/a/openai/chat/completions%00"),
        ("POST", "/r/a/openai/credits"),
        ("GET", "/r/a/openai/chat/completions"),
        ("POST", "/r/a/openai"),
        ("POST", "/r/a/anthropic/v1/key"),
        ("POST", "/r/a/anthropic/v1/messages/"),
        ("POST", "/r/a/anthropic/v1/messages/batches"),
        ("POST", "/r/a/gemini/v1beta/cachedContents"),
        ("POST", "/r/a/gemini/v1beta/models/m:deleteModel"),
        ("POST", "/r/a/gemini/v1beta/models/m:generateContent/../../cachedContents"),
        ("POST", "/r/a/gemini/v1beta/models/m%2f..%2fn:generateContent"),
    ],
)
def test_only_model_endpoints_are_reachable(stack: tuple[str, Path, gateway.Config], method: str, target: str) -> None:
    url, _, cfg = stack
    assert _request(url, method, target, body=b"{}" if method == "POST" else None) == 403
    assert not SEEN and cfg.total == 0  # nothing went upstream


@pytest.mark.parametrize(
    ("target", "upstream"),
    [
        ("/r/a/anthropic/v1/messages?beta=true", "/api/v1/messages?beta=true"),
        ("/r/a/anthropic/v1/messages/count_tokens", "/api/v1/messages/count_tokens"),
        ("/r/a/openai/chat/completions", "/api/v1/chat/completions"),
        ("/r/a/openai/responses", "/api/v1/responses"),
        ("/r/a/gemini/v1beta/models/gemini-3-pro:generateContent", "/gem/v1beta/models/gemini-3-pro:generateContent"),
        (
            "/r/a/gemini/v1beta/models/gemini-3-pro:streamGenerateContent?alt=sse",
            "/gem/v1beta/models/gemini-3-pro:streamGenerateContent?alt=sse",
        ),
        ("/r/a/gemini/v1beta/models/gemini-3-pro:countTokens", "/gem/v1beta/models/gemini-3-pro:countTokens"),
        ("/r/a/gemini/v1beta/models/gemini-3-pro%3AgenerateContent", "/gem/v1beta/models/gemini-3-pro:generateContent"),
    ],
)
def test_model_endpoints_are_forwarded(stack: tuple[str, Path, gateway.Config], target: str, upstream: str) -> None:
    url, _, cfg = stack
    cfg.model = None  # the Gemini pin is tested on its own
    assert _request(url, "POST", target, body=b'{"model": "x"}') == 200
    assert SEEN[-1]["path"] == upstream


def test_gemini_forwarder_host_is_accepted_and_the_model_is_pinned(stack: tuple[str, Path, gateway.Config]) -> None:
    url, ledger, cfg = stack
    cfg.allowed_hosts = list(sidecar.ALLOWED_HOSTS)
    cfg.model = "gemini-pinned"
    # What the agent sends from inside the container: Host is the localhost forwarder, the model is in the path.
    target = f"{url}/r/g1/gemini/v1beta/models/gemini-agent-chose:streamGenerateContent?alt=sse&key={DUMMY_TOKEN}"
    resp = httpx.post(target, json={"contents": []}, headers={"Host": "127.0.0.1:8788", "x-goog-api-key": DUMMY_TOKEN})
    assert resp.status_code == 200
    seen = SEEN[-1]
    assert seen["path"] == "/gem/v1beta/models/gemini-pinned:streamGenerateContent?alt=sse"
    assert seen["goog"] == ["real-key"]  # the dummy token never goes upstream, in any letter case
    assert json.loads(ledger.read_text().splitlines()[-1])["model"] == "gemini-pinned"
    other = httpx.post(target, json={}, headers={"Host": "evil.example:8788", "x-goog-api-key": DUMMY_TOKEN})
    assert other.status_code == 403
    cfg.model = None
    free = httpx.post(target.replace("/g1/", "/g2/"), json={}, headers={"Host": "obey-gw:8787", **AUTH})
    assert free.status_code == 200 and "gemini-agent-chose" in SEEN[-1]["path"]


def test_chunked_request_body_is_decoded(stack: tuple[str, Path, gateway.Config]) -> None:
    url, _, _ = stack
    conn = http.client.HTTPConnection(urlsplit(url).netloc)
    headers = {**AUTH, "Content-Type": "application/json", "Transfer-Encoding": "chunked"}
    pieces = [b'{"model": "x", ', b'"messages": []}']
    for run_id in ("c1", "c2"):  # the second request proves nothing was left over on the connection
        conn.request(
            "POST", f"/r/{run_id}/openai/chat/completions", body=iter(pieces), headers=headers, encode_chunked=True
        )
        resp = conn.getresponse()
        assert resp.status == 200 and b"choices" in resp.read()
        assert SEEN[-1]["body"]["model"] == "pinned/model" and SEEN[-1]["body"]["messages"] == []
    conn.close()
    assert len(SEEN) == 2
    bad = _raw(
        url,
        b"POST /r/c3/openai/chat/completions HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n"
        + f"Authorization: Bearer {DUMMY_TOKEN}\r\n\r\nzz\r\n".encode(),
    )
    assert bad.startswith(b"HTTP/1.1 400 ") and len(SEEN) == 2


def test_bodyless_status_has_no_chunk_framing_or_repeated_headers(edge: tuple[str, gateway.Config]) -> None:
    url, _ = edge
    request = f"GET /r/e1/openai/models HTTP/1.1\r\nHost: x\r\nConnection: close\r\n{_auth_line()}\r\n".encode()
    raw = _raw(url, request)
    head = raw.lower()
    assert raw.startswith(b"HTTP/1.1 204 ") and raw.endswith(b"\r\n\r\n") and raw.count(b"\r\n\r\n") == 1
    assert head.count(b"\r\nserver:") == 1 and head.count(b"\r\ndate:") == 1 and b"transfer-encoding" not in head


def _auth_line() -> str:
    return f"Authorization: Bearer {DUMMY_TOKEN}\r\n"


@pytest.mark.parametrize("api_path", ["chat/completions", "responses"], ids=["connection-cut", "short-body"])
def test_upstream_failure_mid_stream_ends_the_body_and_closes(edge: tuple[str, gateway.Config], api_path: str) -> None:
    url, cfg = edge
    request = f"POST /r/e2/openai/{api_path} HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n{_auth_line()}\r\n{{}}"
    raw = _raw(url, request.encode())  # returns only because the gateway closed the connection
    assert raw.startswith(b"HTTP/1.1 200 ") and raw.count(b"HTTP/1.1 ") == 1
    assert raw.endswith(b"\r\n0\r\n\r\n")
    assert b"502" not in raw and b"upstream error" not in raw
    assert cfg.spent["e2"] == pytest.approx(0.0007)  # what was seen before the failure is still billed


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


def _proxy_scenario(tmp_path: Path, **proxy_options: Any) -> Any:
    """Run a coroutine factory against a proxy that may tunnel to a throwaway upstream on 127.0.0.1."""

    def run(body: Any) -> Any:
        async def main() -> Any:
            upstream = await asyncio.start_server(body.upstream, "127.0.0.1", 0)
            uport = upstream.sockets[0].getsockname()[1]
            proxy = egress_proxy.Proxy(["127.0.0.1"], str(tmp_path / "egress.jsonl"), ports=(uport,), **proxy_options)
            server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
            try:
                return await body.run(server.sockets[0].getsockname()[1], uport)
            finally:
                server.close()
                upstream.close()

        return asyncio.run(main())

    return run


def test_proxy_closes_the_upstream_when_the_client_resets_after_connect(tmp_path: Path) -> None:
    class Body:
        opened = live = 0

        async def upstream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            self.opened += 1
            self.live += 1
            try:
                while await reader.read(1024):
                    pass
            finally:
                self.live -= 1
                writer.close()

        async def run(self, proxy_port: int, upstream_port: int) -> tuple[int, int]:
            for _ in range(20):
                sock = socket.create_connection(("127.0.0.1", proxy_port))
                sock.sendall(f"CONNECT 127.0.0.1:{upstream_port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                sock.close()  # RST instead of a clean close
            for _ in range(100):
                await asyncio.sleep(0.05)
                if self.opened == 20 and self.live == 0:
                    break
            return self.opened, self.live

    assert _proxy_scenario(tmp_path)(Body()) == (20, 0)


def test_proxy_drops_idle_tunnels_but_keeps_busy_ones(tmp_path: Path) -> None:
    class Body:
        closed = False

        async def upstream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while data := await reader.read(100):
                    writer.write(data)
                    await writer.drain()
            finally:
                self.closed = True
                writer.close()

        async def run(self, proxy_port: int, upstream_port: int) -> tuple[bool, bytes]:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            writer.write(f"CONNECT 127.0.0.1:{upstream_port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            await reader.readuntil(b"\r\n\r\n")
            alive = True
            for _ in range(8):  # 1.6 s of traffic, longer than the idle timeout
                writer.write(b"x")
                alive = alive and await asyncio.wait_for(reader.readexactly(1), 2) == b"x"
                await asyncio.sleep(0.2)
            eof = await asyncio.wait_for(reader.read(10), 5)  # then silence: the proxy must hang up
            await asyncio.sleep(0.1)
            return alive and self.closed, eof

    assert _proxy_scenario(tmp_path, idle_timeout=0.6)(Body()) == (True, b"")
