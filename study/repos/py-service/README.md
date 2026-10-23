# ledgerline

A small invoicing and inventory library for Python 3.11+, backed by SQLite. It has no runtime
dependencies: only the standard library (`sqlite3`, `decimal`, `dataclasses`, `logging`).

## What it does

- Customers, invoices with line items, and stock-tracked SKUs.
- Invoice lifecycle: `draft` -> `sent` -> `paid` (or `void`). Sending an invoice takes tracked
  items out of stock; voiding a sent invoice puts them back.
- Exact money arithmetic (`Decimal`, rounded to each currency's minor unit).
- An importer that turns a shop platform's "order paid" webhook into a draft invoice.

```python
from ledgerline.db import Database
from ledgerline.service import InvoiceService

db = Database("ledger.db")
db.migrate()
service = InvoiceService(db)
customer = service.register_customer("Ada Example", "ada@example.com")
```

## Layout

```
src/ledgerline/   library code (generated/ is produced by scripts/gen_currency.py)
migrations/       numbered SQL migrations, applied in order by Database.migrate()
scripts/          maintenance scripts
tests/            pytest suite, one test module per source module
```

## Development

```
make test        # uv run pytest -q
make lint        # uv run ruff check .
make typecheck   # uv tool run mypy src
make gen         # regenerate src/ledgerline/generated/currency_codes.py
```

See `AGENTS.md` for the working agreement for contributors and coding agents.

This directory is part of the parent repository and is licensed under Apache-2.0 with it.
