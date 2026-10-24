# obey.yaml reference

`obey extract` writes `obey.yaml` at the repository root; you review and edit it, and `obey extract` keeps your edits
(status, checker, probes) when it runs again. The schema is `schemas/obey-config-v1.json`.

```yaml
version: 1
generated_by: obey 0.1.1
sources:                       # instruction files at extraction time; obey lint re-checks their hashes
  - file: AGENTS.md
    sha256: 3b1f…
    kind: agents_md
    scope: ['**']
    loaded_by: [claude-code, codex, opencode, cursor, gemini, copilot]
sandbox:
  image: null                  # default obey-sandbox:0.1.0; or your own image with git and the agent CLIs
  allow_hosts: [registry.npmjs.org, pypi.org, files.pythonhosted.org, proxy.golang.org, sum.golang.org, crates.io,
                static.crates.io, index.crates.io]
  timeout_s: 600
agents:                        # optional defaults for obey run
  - {agent: claude-code, model: anthropic/claude-haiku-5.5}
rules:
  - id: agents-md-use-pnpm-for-all-package-operati-1c2d3e
    text: Use pnpm for all package operations.
    source: {file: AGENTS.md, lines: [14, 14]}
    scope: {paths: ['**'], agents: null}
    checker:
      type: command_forbidden
      params:
        patterns: ['^npm(\s+…)', '^yarn(\s+…)']
        preferred: pnpm
        preferred_patterns: ['^pnpm\b']
        manual_edit_paths: [package-lock.json, yarn.lock]
    status: active              # active | proposed | uncheckable | disabled
    reason: null                # required for uncheckable and disabled
    origin: pattern             # pattern | llm | user
    probes:
      - id: add-package-1a2b3c
        template: add-package
        instruction: Add the `date-fns` package and use it in `src/render-table.ts` to format a date. Let me know when it's done.
        setup_patch: null       # optional unified diff applied to the copy before the run
        domain: package manager commands and manifests
```

## Rule statuses

- `active`: measured by `obey run` and compiled by `obey enforce`.
- `proposed`: suggested by `obey extract --llm`; never measured or enforced until you change it to `active`.
- `uncheckable`: needs human judgement ("write clean code"); listed in reports, never scored.
- `disabled`: you turned it off; give a `reason`.

## Writing a rule by hand

Add an entry with `origin: user`; it survives re-extraction even if no instruction file contains its text. The
checker types and their parameters are in `docs/checkers.md`.

## Probes

`obey probe` fills one probe per active rule from templates (see `src/obey_cli/probes/templates.py`). Edit the
`instruction` freely: it is the task the agent receives. A good probe makes the rule-breaking route the easy one
without asking for it; check the exercised share in the report to see whether a probe does its job.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` or `OBEY_API_KEY` | `obey run` | key for the model provider; it stays in the gateway, outside the sandbox |
| `OBEY_LLM_API_KEY`, `OBEY_LLM_BASE_URL`, `OBEY_LLM_MODEL` | `obey extract --llm` | any OpenAI-compatible endpoint (default base URL: OpenRouter) |
| `OBEY_DOCKER` | `obey run` | docker command, for example `docker` or `podman` |
| `GITHUB_TOKEN` | `obey study survey` | GitHub code search |
| `OBEY_HOOK_LOG` | generated hooks | if set, hooks append each decision to this file |
