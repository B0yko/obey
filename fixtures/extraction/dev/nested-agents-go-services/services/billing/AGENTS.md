# services/billing

Invoicing and payments. Amounts are stored as integer cents.

- Never use `float64` for amounts.
- Use `pkg/logx` instead of the standard `log` package.
- Name migration files `NNNN_description.sql`, for example `0004_add_refunds.sql`.
- Prefer idempotent handlers.

## Commands

```bash
go test ./services/billing/...
```
