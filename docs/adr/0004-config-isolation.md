# 4. Per-agent configuration isolation

Date: 2026-10-23 · Status: accepted

## Context

A user's global instruction file (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`), global hooks, plugins and MCP
servers would change what the agent does and make results depend on the machine they ran on.

## Decision

Agents run in a fresh container with an empty home directory, so no global configuration exists to leak in. On
top of that each adapter sets the agent's own isolation switch (for example `CLAUDE_CONFIG_DIR` and `CODEX_HOME`
pointing at empty directories, `OPENCODE_DISABLE_CLAUDE_CODE=1`). `--unsafe-local` (no container) applies the
same switches in a temporary clone with an empty `HOME`, no credential variables and no git credential helpers.

Each adapter records which instruction files the agent reported loading when its stream exposes that. The
per-agent matrix, and how each switch was verified with a load probe, is in `docs/agents.md`.

## Consequences

- Results do not depend on the user's own agent setup.
- When an agent cannot report loaded files, the load probe in the contract tests is the evidence.
