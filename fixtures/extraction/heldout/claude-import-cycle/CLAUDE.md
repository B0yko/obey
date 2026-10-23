# Pelican Cache

Pelican Cache is an in-memory cache server written in Go. Packages: `cmd/pelican` and
`internal/`.

Error-handling rules: @docs/rules/errors.md

## Rules

1. Never run `go get -u` (blanket upgrades churn `go.sum`); pin versions explicitly.
2. Do not push to the remote.
3. Think about eviction behaviour before changing the cache core.
