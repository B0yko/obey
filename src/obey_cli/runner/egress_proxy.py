"""Allow-listing HTTP CONNECT proxy for the sandbox (standard library only).

The agent container sits on an internal Docker network with no route out; this proxy, in the sidecar container,
is its only way to the internet. It tunnels CONNECT requests to allow-listed hosts on port 443, refuses
everything else, and logs every attempt as one JSON line.

    python3 egress_proxy.py --listen 0.0.0.0:3128 --allow registry.npmjs.org --allow '*.pythonhosted.org' --log log
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from typing import Optional

MAX_HEADER = 16384


def host_allowed(host: str, port: int, allow: "list[str]", ports: "tuple[int, ...]" = (443,)) -> bool:
    host = host.lower().rstrip(".")
    if port not in ports:
        return False
    for pattern in allow:
        pattern = pattern.lower()
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


class Proxy:
    def __init__(self, allow: "list[str]", log_path: Optional[str], ports: "tuple[int, ...]" = (443,)):
        self.allow = allow
        self.ports = ports
        self.log_path = log_path

    def log(self, **fields: object) -> None:
        line = json.dumps({"ts": round(time.time(), 3), **fields}, sort_keys=True)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        else:
            print(line, flush=True)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
            writer.close()
            return
        if len(head) > MAX_HEADER:
            await self._refuse(writer, 431, "header too large")
            return
        request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = request_line.split()
        if len(parts) != 3:
            await self._refuse(writer, 400, "bad request")
            return
        method, target, _ = parts
        if method.upper() != "CONNECT":
            self.log(
                event="refused", method=method, target=target[:200], reason="only CONNECT is allowed", client=str(peer)
            )
            await self._refuse(writer, 405, "only CONNECT is allowed")
            return
        host, _, port_text = target.rpartition(":")
        host = host.strip("[]")
        try:
            port = int(port_text)
        except ValueError:
            await self._refuse(writer, 400, "bad port")
            return
        if not host_allowed(host, port, self.allow, self.ports):
            self.log(event="refused", host=host, port=port, client=str(peer))
            await self._refuse(writer, 403, "host not on the allow-list")
            return
        try:
            up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=20)
        except (OSError, asyncio.TimeoutError) as exc:
            self.log(event="upstream_error", host=host, port=port, error=type(exc).__name__)
            await self._refuse(writer, 502, "upstream unreachable")
            return
        self.log(event="allowed", host=host, port=port, client=str(peer))
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(self._pipe(reader, up_writer), self._pipe(up_reader, writer))

    @staticmethod
    async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    @staticmethod
    async def _refuse(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
        body = reason.encode()
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
        )
        with contextlib.suppress(Exception):
            await writer.drain()
            writer.close()


async def serve(listen: str, proxy: Proxy, ready: "Optional[asyncio.Event]" = None) -> None:
    host, _, port = listen.rpartition(":")
    server = await asyncio.start_server(proxy.handle, host or "127.0.0.1", int(port))
    if ready is not None:
        ready.set()
    async with server:
        await server.serve_forever()


def main(argv: "Optional[list[str]]" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listen", default="127.0.0.1:3128")
    parser.add_argument("--allow", action="append", default=[], help="host or *.suffix (repeatable)")
    parser.add_argument("--log", default=None, help="JSON-lines log file (default: stdout)")
    args = parser.parse_args(argv)
    asyncio.run(serve(args.listen, Proxy(args.allow, args.log)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
