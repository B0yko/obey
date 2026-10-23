# Gantry

A Go monorepo with two services (`services/billing` and `services/notifications`) and shared
code in `pkg/`. Each service has its own `AGENTS.md`.

## Repo-wide rules

- Do not commit unless asked.
- Do not push.
- Run `go vet ./...` from the repo root before finishing.
- Shared code in `pkg/` must stay free of service-specific logic.
