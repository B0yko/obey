"""Sidecar process for a sandbox batch: the model gateway and the egress proxy (standard library only).

OBEY_UPSTREAM_KEY=... python3 sidecar.py [gateway options] --allow host [--allow host ...]
"""

import argparse
import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import egress_proxy
import gateway

HOME = os.path.expanduser("~")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow", action="append", default=[])
    known, rest = parser.parse_known_args()
    rest += ["--listen", "0.0.0.0:8787", "--ledger", os.path.join(HOME, "ledger.jsonl")]
    rest += ["--allowed-host", "obey-gw:8787"]
    gateway_thread = threading.Thread(target=gateway.main, args=(rest,), daemon=True)
    gateway_thread.start()
    proxy = egress_proxy.Proxy(known.allow, os.path.join(HOME, "egress.jsonl"))
    asyncio.run(egress_proxy.serve("0.0.0.0:3128", proxy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
