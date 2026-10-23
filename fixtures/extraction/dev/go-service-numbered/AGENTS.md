# Quillnote API (Go)

Quillnote is a note-sync HTTP API written in Go 1.23. The entry point is `cmd/quillnote`.
Packages under `internal/` are private to the service.

## Ground rules

1. Run `go vet ./...` after changing any `.go` file.
2. Do not add modules to `go.mod` without approval.
3. Use the standard library first.
4. Use `log/slog` for logging. Do not call `fmt.Println` or `fmt.Printf` in `internal/` or `cmd/`.
5. Never edit files under `vendor/`; run `go mod vendor` instead.
6. File names are lower snake_case, for example `note_store.go`.
7. Leave pushing to the maintainers: never run `git push`.
8. Prefer table-driven tests.
9. Wrap errors with context before returning them.
10. Keep exported API changes minimal and call them out in your reply.

## Useful commands

```bash
go test ./...
go run ./cmd/quillnote
```
