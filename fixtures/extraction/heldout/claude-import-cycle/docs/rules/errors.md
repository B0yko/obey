# Error handling

Errors are values in Go, and this server returns them to a single place in `cmd/pelican`
that decides how to report them.

## Rules

- Do not call `log.Fatal` or `os.Exit` in packages under `internal/`; return the error.
- Commit messages look like `area: short summary`, for example `cache: fix eviction race`.
- Wrap errors with context.

Release conventions are in @docs/rules/release.md.
