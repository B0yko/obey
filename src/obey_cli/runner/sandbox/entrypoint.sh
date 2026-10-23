#!/bin/sh
# Runs one agent command with a deadline and keeps its stdout/stderr for obey to read back.
# Usage: obey-entrypoint <timeout-seconds> <command> [args...]
set -u
deadline="$1"; shift
mkdir -p /home/agent/.obey-out
cd /home/agent/work || exit 97
timeout --signal=TERM --kill-after=10 "$deadline" "$@" \
  < /dev/null > /home/agent/.obey-out/stream.jsonl 2> /home/agent/.obey-out/stderr.log
code=$?
echo "$code" > /home/agent/.obey-out/exit_code
exit 0
