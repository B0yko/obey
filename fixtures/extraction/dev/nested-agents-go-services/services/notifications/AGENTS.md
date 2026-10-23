# services/notifications

Sends email and push messages from a queue.

- Do not add new queue or email libraries without approval.
- Never edit files under `internal/pb/`; they are generated from the protobuf definitions.
- Keep message text in `templates/`, not in Go files.
- Handler tests should use fake clocks.

## Commands

```bash
go test ./services/notifications/...
```
