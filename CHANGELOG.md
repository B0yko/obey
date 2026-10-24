# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and the project uses
semantic versioning.

## [0.1.1] - 2026-10-24

Documentation and packaging only; the CLI, the checkers and the hooks behave as in 0.1.0.

- The README opens with what obey is for and how to try it, installs from PyPI (`uvx --from obey-cli obey demo`),
  and uses absolute image and link URLs, so it also renders on PyPI.
- A new social preview, built from the study's numbers by `eval/make_social_preview.py`.
- Release assets are only the wheel and the sdist; study charts are written with stable element ids, so rebuilding
  them changes no bytes.

## [0.1.0] - 2026-10-24

First release.

- `obey extract`: rules from AGENTS.md (nested), CLAUDE.md with imports, GEMINI.md, Cursor `.mdc` rules and Copilot
  instruction files, mapped to twelve deterministic checker types; optional LLM proposals that are never accepted
  automatically.
- `obey probe`: a tempting task per rule from templates filled with repository facts.
- `obey run`: Claude Code, Codex CLI, OpenCode, Copilot CLI and Gemini CLI run headless in a container behind an
  allow-listing egress proxy and a key-holding model gateway; per-rule compliance with Wilson intervals, a no-rule
  baseline, budgets, `--estimate`, `--compare` with evasion counts, and `--unsafe-local`.
- `obey enforce`: hooks for Claude Code, Codex CLI, Cursor, Gemini CLI, Copilot CLI and OpenCode plus a git pre-commit
  check, all calling one standard-library rule engine; idempotent, JSON-preserving merges with `--dry-run` and
  `--remove`.
- `obey lint`, the GitHub Action, `.pre-commit-hooks.yaml`, `obey demo`, `obey doctor`, `obey init`.
- The study: a survey of 600 public AGENTS.md files, a pre-registered experiment on rule phrasing, and a before/after
  measurement of hooks with evasions (`study/REPORT.md`).
