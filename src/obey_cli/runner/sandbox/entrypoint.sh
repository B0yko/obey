#!/bin/sh
# Runs one agent command with a deadline and keeps its stdout/stderr for obey to read back.
# Usage: obey-entrypoint <timeout-seconds> <command> [args...]
set -u
deadline="$1"; shift
mkdir -p /home/agent/.obey-out
cd /srv/obey/work || exit 97
if [ -n "${OBEY_LOCAL_FORWARD:-}" ]; then
  # Some CLIs accept plain HTTP only on localhost: forward 127.0.0.1:$OBEY_LOCAL_FORWARD to the gateway.
  python3 - "$OBEY_LOCAL_FORWARD" <<'PY' &
import asyncio, sys
async def pipe(r, w):
    try:
        while (data := await r.read(65536)):
            w.write(data); await w.drain()
    finally:
        w.close()
async def handle(r, w):
    ur, uw = await asyncio.open_connection("obey-gw", 8787)
    await asyncio.gather(pipe(r, uw), pipe(ur, w))
async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", int(sys.argv[1]))
    async with server:
        await server.serve_forever()
asyncio.run(main())
PY
  sleep 0.3
fi
timeout --signal=TERM --kill-after=10 "$deadline" "$@" \
  < /dev/null > /home/agent/.obey-out/stream.jsonl 2> /home/agent/.obey-out/stderr.log
code=$?
echo "$code" > /home/agent/.obey-out/exit_code
if [ -f /home/agent/.obey-tools/workspace.py ]; then
  # Read the end state here, so only small JSON files travel back to the host.
  python3 /home/agent/.obey-tools/workspace.py collect /srv/obey/work "${OBEY_BASE_SHA:-HEAD}" \
    /srv/obey/.remote/origin.git /home/agent/.obey-out/end-state.json 2> /home/agent/.obey-out/collect.log
fi
exit 0
