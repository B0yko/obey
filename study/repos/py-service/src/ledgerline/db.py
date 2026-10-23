# SPDX-License-Identifier: Apache-2.0
"""SQLite persistence: migrations plus a small repository for each table."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from ledgerline.errors import NotFoundError, ValidationError
from ledgerline.models import Customer, Invoice, InvoiceLine, InvoiceStatus, StockItem
from ledgerline.money import Money

logger = logging.getLogger(__name__)

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class Database:
    """A single SQLite connection with schema migrations applied on demand."""

    def __init__(self, path: str | Path = ":memory:", migrations_dir: Path | None = None) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrations_dir = migrations_dir or DEFAULT_MIGRATIONS_DIR
        self._depth = 0

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success and roll back on error; nested uses join the outer transaction."""
        self._depth += 1
        try:
            yield self._conn
        except BaseException:
            if self._depth == 1:
                self._conn.rollback()
            raise
        else:
            if self._depth == 1:
                self._conn.commit()
        finally:
            self._depth -= 1

    # -- migrations ---------------------------------------------------------

    def migrate(self) -> list[str]:
        """Apply pending ``NNNN_name.sql`` files in order and return their versions."""
        if not self._migrations_dir.is_dir():
            raise FileNotFoundError(f"migrations directory not found: {self._migrations_dir}")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        rows = self._conn.execute("SELECT version FROM schema_migrations").fetchall()
        done = {row["version"] for row in rows}
        applied: list[str] = []
        for path in sorted(self._migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            if path.stem in done:
                continue
            logger.info("applying migration %s", path.name)
            self._conn.executescript(path.read_text(encoding="utf-8"))
            self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (path.stem, datetime.now(UTC).isoformat()),
            )
            self._conn.commit()
            applied.append(path.stem)
        return applied

    # -- customers ----------------------------------------------------------

    def add_customer(self, name: str, email: str, created_at: datetime) -> Customer:
        try:
            with self.transaction() as conn:
                cur = conn.execute(
                    "INSERT INTO customers (name, email, created_at) VALUES (?, ?, ?)",
                    (name, email, created_at.isoformat()),
                )
        except sqlite3.IntegrityError:
            raise ValidationError(f"email already registered: {email}") from None
        return Customer(cur.lastrowid, name, email, created_at)

    def get_customer(self, customer_id: int) -> Customer:
        row = self._conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"customer {customer_id} not found")
        return _customer(row)

    def find_customer_by_email(self, email: str) -> Customer | None:
        row = self._conn.execute("SELECT * FROM customers WHERE email = ?", (email,)).fetchone()
        return _customer(row) if row else None

    # -- invoices -----------------------------------------------------------

    def count_invoices_with_prefix(self, prefix: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM invoices WHERE number LIKE ?", (prefix + "%",)
        ).fetchone()
        return int(row["n"])

    def save_invoice(self, invoice: Invoice) -> Invoice:
        """Insert a new invoice with its lines and return it with ``id`` set."""
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO invoices (number, customer_id, currency, status, issued_at, due_date)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    invoice.number,
                    invoice.customer_id,
                    invoice.currency,
                    invoice.status.value,
                    invoice.issued_at.isoformat(),
                    invoice.due_date.isoformat() if invoice.due_date else None,
                ),
            )
            invoice.id = cur.lastrowid
            conn.executemany(
                "INSERT INTO invoice_lines (invoice_id, sku, description, quantity, unit_price)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (invoice.id, ln.sku, ln.description, ln.quantity, str(ln.unit_price.amount))
                    for ln in invoice.lines
                ],
            )
        return invoice

    def get_invoice(self, invoice_id: int) -> Invoice:
        row = self._conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        return self._hydrate(row)

    def list_invoices(
        self, status: InvoiceStatus | None = None, customer_id: int | None = None
    ) -> list[Invoice]:
        clauses: list[str] = []
        params: list[str | int] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if customer_id is not None:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(f"SELECT * FROM invoices{where} ORDER BY id", params).fetchall()
        return [self._hydrate(row) for row in rows]

    def set_invoice_status(self, invoice_id: int, status: InvoiceStatus) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE invoices SET status = ? WHERE id = ?", (status.value, invoice_id))

    def _hydrate(self, row: sqlite3.Row) -> Invoice:
        line_rows = self._conn.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY id", (row["id"],)
        ).fetchall()
        currency = row["currency"]
        lines = [
            InvoiceLine(
                sku=ln["sku"],
                description=ln["description"],
                quantity=ln["quantity"],
                unit_price=Money(Decimal(ln["unit_price"]), currency),
            )
            for ln in line_rows
        ]
        return Invoice(
            id=row["id"],
            number=row["number"],
            customer_id=row["customer_id"],
            currency=currency,
            status=InvoiceStatus(row["status"]),
            issued_at=date.fromisoformat(row["issued_at"]),
            due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
            lines=lines,
        )

    # -- stock --------------------------------------------------------------

    def upsert_stock(self, sku: str, name: str, on_hand: int) -> StockItem:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO stock_items (sku, name, on_hand) VALUES (?, ?, ?)"
                " ON CONFLICT(sku) DO UPDATE SET name = excluded.name, on_hand = excluded.on_hand",
                (sku, name, on_hand),
            )
        return StockItem(sku, name, on_hand)

    def get_stock(self, sku: str) -> StockItem | None:
        row = self._conn.execute("SELECT * FROM stock_items WHERE sku = ?", (sku,)).fetchone()
        return StockItem(row["sku"], row["name"], row["on_hand"]) if row else None

    def adjust_stock(self, sku: str, delta: int) -> StockItem:
        with self.transaction() as conn:
            conn.execute("UPDATE stock_items SET on_hand = on_hand + ? WHERE sku = ?", (delta, sku))
        item = self.get_stock(sku)
        if item is None:
            raise NotFoundError(f"stock item {sku!r} not found")
        return item


def _customer(row: sqlite3.Row) -> Customer:
    return Customer(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
