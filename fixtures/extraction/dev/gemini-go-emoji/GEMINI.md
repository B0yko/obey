# Larkspur

Larkspur is a command-line tool for managing seed catalogs. Go 1.23, cobra for commands,
SQLite for storage.

## Do

- ✅ Run `gofmt -l .` before you finish and fix anything it lists.
- ✅ Wrap errors with `fmt.Errorf("...: %w", err)`.
- ✅ Keep each cobra command in its own file under `cmd/`.
- 🧪 Add a test for every bug you fix.

## Don't

- 🚫 Don't call `panic(` in packages under `internal/`; return an error instead.
- 🚫 Don't edit anything in `internal/gen/`; it is produced by `go generate`.
- 🚫 Don't add new third-party modules.
- ⚠️ Commits are made by the maintainer, so don't run `git commit`.
- ⚠️ Never push to a remote.
- 💬 Be concise in your replies.
