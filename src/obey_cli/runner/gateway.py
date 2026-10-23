"""Model gateway: holds the API key outside the agent's container (standard library only).

Agents get a dummy token and a base URL of the form http://<gateway>/r/<run_id>/<api>, where <api> is
`anthropic` (Messages API) or `openai` (Chat Completions / Responses). The gateway swaps in the real key,
pins the model, streams the response back, records token usage and cost per run in the ledger file, and
refuses calls once a run or the whole batch reaches its cap.

    OBEY_UPSTREAM_KEY=... python3 gateway.py --listen 0.0.0.0:8787 --model vendor/model --ledger ledger.jsonl \
        --price-prompt 3e-7 --price-completion 1.2e-6 --run-cap 0.5 --budget 20
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

UPSTREAMS = {
    "anthropic": "https://openrouter.ai/api",
    "openai": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com",
}
_PATH_RE = re.compile(r"^/r/([A-Za-z0-9._-]{1,80})/(anthropic|openai|gemini)(/.*)?$")
_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "authorization",
    "x-api-key",
    "accept-encoding",
}


class Config:
    def __init__(
        self,
        key: str,
        model: Optional[str],
        ledger: Optional[str],
        price: Dict[str, float],
        run_cap: Optional[float],
        budget: Optional[float],
        upstreams: Dict[str, str],
        allowed_hosts: Optional[List[str]] = None,
    ):
        self.key = key
        self.model = model
        self.ledger = ledger
        self.price = price
        self.run_cap = run_cap
        self.budget = budget
        self.upstreams = upstreams
        self.allowed_hosts = allowed_hosts
        self.lock = threading.Lock()
        self.spent: Dict[str, float] = {}
        self.total = 0.0
        if ledger and os.path.exists(ledger):
            with open(ledger, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        self._add(str(row.get("run_id")), float(row.get("cost_usd", 0.0)))

    def _add(self, run_id: str, cost: float) -> None:
        self.spent[run_id] = self.spent.get(run_id, 0.0) + cost
        self.total += cost

    def over_cap(self, run_id: str) -> Optional[str]:
        with self.lock:
            if self.budget is not None and self.total >= self.budget:
                return f"batch budget ${self.budget:.2f} reached"
            if self.run_cap is not None and self.spent.get(run_id, 0.0) >= self.run_cap:
                return f"per-run cap ${self.run_cap:.2f} reached"
        return None

    def record(self, run_id: str, requested: str, usage: Dict[str, int], provider_cost: Optional[float]) -> None:
        if provider_cost is not None:
            cost, source = provider_cost, "provider"
        else:
            cost, source = price_cost(self.price, usage), "price_table"
        entry = {
            "ts": round(time.time(), 3),
            "run_id": run_id,
            "kind": "agent",
            "model": self.model or requested,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_tokens", 0),
            "cache_write_tokens": usage.get("cache_write_tokens", 0),
            "cost_usd": cost,
            "cost_source": source,
        }
        with self.lock:
            self._add(run_id, cost)
            if self.ledger:
                with open(self.ledger, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, sort_keys=True) + "\n")


def price_cost(price: Dict[str, float], usage: Dict[str, int]) -> float:
    cached = usage.get("cache_read_tokens", 0)
    written = usage.get("cache_write_tokens", 0)
    fresh = max(0, usage.get("input_tokens", 0) - cached - written)
    prompt = price.get("prompt", 0.0)
    return (
        fresh * prompt
        + usage.get("output_tokens", 0) * price.get("completion", 0.0)
        + cached * price.get("cache_read", prompt)
        + written * price.get("cache_write", prompt)
    )


class UsageMeter:
    """Accumulates usage from a JSON body or from server-sent events, for both API styles."""

    def __init__(self) -> None:
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
        self.cost: Optional[float] = None
        self._buffer = b""

    def feed_json(self, body: Any) -> None:
        if not isinstance(body, dict):
            return
        if body.get("type") == "message_start" and isinstance(body.get("message"), dict):
            body = body["message"]
        if body.get("type") == "response.completed" and isinstance(body.get("response"), dict):
            body = body["response"]
        meta = body.get("usageMetadata")
        if isinstance(meta, dict):  # Gemini API
            self.usage["input_tokens"] = max(self.usage["input_tokens"], int(meta.get("promptTokenCount") or 0))
            self.usage["output_tokens"] = max(
                self.usage["output_tokens"],
                int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0),
            )
            self.usage["cache_read_tokens"] = max(
                self.usage["cache_read_tokens"], int(meta.get("cachedContentTokenCount") or 0)
            )
            return
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return
        if isinstance(usage.get("cost"), (int, float)):
            self.cost = (self.cost or 0.0) + float(usage["cost"])
        if "prompt_tokens" in usage or "completion_tokens" in usage:
            details = usage.get("prompt_tokens_details") or {}
            self.usage["input_tokens"] = max(self.usage["input_tokens"], int(usage.get("prompt_tokens") or 0))
            self.usage["output_tokens"] = max(self.usage["output_tokens"], int(usage.get("completion_tokens") or 0))
            self.usage["cache_read_tokens"] = max(
                self.usage["cache_read_tokens"], int(details.get("cached_tokens") or 0)
            )
            return
        if "input_tokens" in usage and "output_tokens" in usage and "input_tokens_details" in usage:
            details = usage.get("input_tokens_details") or {}  # Responses API
            self.usage["input_tokens"] = max(self.usage["input_tokens"], int(usage.get("input_tokens") or 0))
            self.usage["output_tokens"] = max(self.usage["output_tokens"], int(usage.get("output_tokens") or 0))
            self.usage["cache_read_tokens"] = max(
                self.usage["cache_read_tokens"], int(details.get("cached_tokens") or 0)
            )
            return
        read = int(usage.get("cache_read_input_tokens") or 0)
        write = int(usage.get("cache_creation_input_tokens") or 0)
        if "input_tokens" in usage:
            self.usage["input_tokens"] = max(
                self.usage["input_tokens"], int(usage.get("input_tokens") or 0) + read + write
            )
            self.usage["cache_read_tokens"] = max(self.usage["cache_read_tokens"], read)
            self.usage["cache_write_tokens"] = max(self.usage["cache_write_tokens"], write)
        if "output_tokens" in usage:
            self.usage["output_tokens"] = max(self.usage["output_tokens"], int(usage.get("output_tokens") or 0))

    def feed_sse(self, chunk: bytes) -> None:
        self._buffer += chunk
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            line = line.strip()
            if line.startswith(b"data:"):
                data = line[5:].strip()
                if data and data != b"[DONE]":
                    with contextlib.suppress(ValueError):
                        self.feed_json(json.loads(data))


def rewrite_body(api: str, raw: bytes, model: Optional[str]) -> Tuple[bytes, str]:
    """Pin the model and ask the provider to report usage. Returns (body, model the agent asked for)."""
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        return raw, ""
    if not isinstance(body, dict):
        return raw, ""
    requested = str(body.get("model", ""))
    if model and "model" in body:
        body["model"] = model
    if api == "openai":
        body["usage"] = {"include": True}
        if body.get("stream") and "messages" in body:
            options = body.get("stream_options")
            merged: Dict[str, Any] = dict(options) if isinstance(options, dict) else {}
            merged["include_usage"] = True
            body["stream_options"] = merged
    return json.dumps(body).encode(), requested


class Handler(BaseHTTPRequestHandler):
    server_version = "obey-gateway"
    protocol_version = "HTTP/1.1"
    config: Config

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _reply(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _guard(self) -> bool:
        cfg = self.config
        if self.headers.get("Origin"):
            self._reply(403, {"error": {"message": "browser requests are not accepted"}})
            return False
        host = (self.headers.get("Host") or "").lower()
        if cfg.allowed_hosts is not None and host not in cfg.allowed_hosts:
            self._reply(403, {"error": {"message": "unexpected Host header"}})
            return False
        return True

    def do_GET(self) -> None:
        self._forward("GET")

    def do_POST(self) -> None:
        self._forward("POST")

    def _forward(self, method: str) -> None:
        if not self._guard():
            return
        match = _PATH_RE.match(urlsplit(self.path).path)
        if not match:
            self._reply(404, {"error": {"message": "use /r/<run_id>/<anthropic|openai>/..."}})
            return
        run_id, api, rest = match.group(1), match.group(2), match.group(3) or "/"
        query = urlsplit(self.path).query
        reason = self.config.over_cap(run_id)
        if reason:
            self._reply(402, {"type": "error", "error": {"type": "budget_exceeded", "message": reason}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body, requested = rewrite_body(api, raw, self.config.model) if method == "POST" else (raw, "")
        base = urlsplit(self.config.upstreams[api])
        path = base.path.rstrip("/") + rest + (f"?{query}" if query else "")
        headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP_HEADERS}
        if api == "gemini":
            headers["x-goog-api-key"] = self.config.key
            if "key=" in query:
                query = "&".join(q for q in query.split("&") if not q.startswith("key="))
                path = base.path.rstrip("/") + rest + (f"?{query}" if query else "")
        else:
            headers["Authorization"] = f"Bearer {self.config.key}"
        headers["Content-Length"] = str(len(body))
        headers["Accept-Encoding"] = "identity"
        conn_cls = http.client.HTTPSConnection if base.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(base.netloc, timeout=600)
        meter = UsageMeter()
        try:
            conn.request(method, path, body=body if method == "POST" else None, headers=headers)
            resp = conn.getresponse()
            streaming = "text/event-stream" in (resp.getheader("Content-Type") or "")
            self.send_response(resp.status)
            for key, value in resp.getheaders():
                if key.lower() not in _HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            collected = b""
            while True:
                chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not chunk:
                    break
                if streaming:
                    meter.feed_sse(chunk)
                elif len(collected) < 8_000_000:
                    collected += chunk
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            if not streaming and collected:
                with contextlib.suppress(ValueError):
                    meter.feed_json(json.loads(collected))
        except (OSError, http.client.HTTPException) as exc:
            with contextlib.suppress(OSError):
                self._reply(502, {"error": {"message": f"upstream error: {type(exc).__name__}"}})
        finally:
            conn.close()
            if method == "POST" and (any(meter.usage.values()) or meter.cost):
                self.config.record(run_id, requested, meter.usage, meter.cost)


def make_server(listen: str, config: Config) -> ThreadingHTTPServer:
    host, _, port = listen.rpartition(":")
    handler = type("BoundHandler", (Handler,), {"config": config})
    server = ThreadingHTTPServer((host or "127.0.0.1", int(port)), handler)
    server.daemon_threads = True
    return server


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="obey model gateway")
    parser.add_argument("--listen", default="127.0.0.1:8787")
    parser.add_argument("--model", default=None, help="pin every request to this model")
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--price-prompt", type=float, default=0.0)
    parser.add_argument("--price-completion", type=float, default=0.0)
    parser.add_argument("--price-cache-read", type=float, default=None)
    parser.add_argument("--price-cache-write", type=float, default=None)
    parser.add_argument("--run-cap", type=float, default=None, help="USD per run")
    parser.add_argument("--budget", type=float, default=None, help="USD for everything in the ledger")
    parser.add_argument("--upstream", action="append", default=[], help="api=https://base (repeatable)")
    parser.add_argument("--allowed-host", action="append", default=None, help="accepted Host header (repeatable)")
    args = parser.parse_args(argv)
    key = os.environ.get("OBEY_UPSTREAM_KEY", "")
    if not key:
        print("OBEY_UPSTREAM_KEY is not set", file=sys.stderr)
        return 2
    upstreams = dict(UPSTREAMS)
    for item in args.upstream:
        api, _, url = item.partition("=")
        upstreams[api] = url
    price = {"prompt": args.price_prompt, "completion": args.price_completion}
    if args.price_cache_read is not None:
        price["cache_read"] = args.price_cache_read
    if args.price_cache_write is not None:
        price["cache_write"] = args.price_cache_write
    config = Config(
        key,
        args.model,
        args.ledger,
        price,
        args.run_cap,
        args.budget,
        upstreams,
        [h.lower() for h in args.allowed_host] if args.allowed_host else None,
    )
    server = make_server(args.listen, config)
    print(f"gateway listening on {args.listen}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
