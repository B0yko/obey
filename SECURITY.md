# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's private vulnerability reporting
(Security → Report a vulnerability) on https://github.com/B0yko/obey. Do not open a public issue. You can expect a
first answer within a week.

## What obey does that matters for security

- `obey run` sends your repository's tracked files and the probe task to the model provider you configure. Only files
  listed by `git ls-files` enter a run; `.env` files and ignored files never do.
- Agents run in a container on an internal Docker network. Their only way out is an allow-listing proxy (by default the
  npm, PyPI, Go and crates registries) and obey's model gateway. Every egress attempt is logged.
- Your API key stays in the gateway, outside the agent's container; agents get a dummy token. The gateway enforces a
  per-run and a per-batch spend cap.
- `--unsafe-local` runs the agent directly on your machine (no container): read the README section before using it.
- Generated hooks run on your machine whenever your agent uses a tool. They use only the Python standard library, read
  only `.obey/hooks/rules.json` and the payload, and fail open on internal errors.
- `obey enforce` writes only inside your repository and never to `~/.claude`, `~/.codex`, `~/.cursor` or similar.

## Supported versions

The latest release receives fixes.
