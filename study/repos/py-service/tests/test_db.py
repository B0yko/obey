# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ledgerline.db import DEFAULT_MIGRATIONS_DIR, Database
from ledgerline.errors import NotFoundError, ValidationError
from ledgerline.models import Invoice, InvoiceLine, InvoiceStatus
from ledgerline.money import Money


def test_migrate_applies_every_file_once_and_in_order(tmp_path: Path) -> None:
    database = Database(tmp_path / "ledger.db")
    expected = sorted(p.stem for p in DEFAULT_MIGRATIONS_DIR.glob("*.sql"))
    assert expected[0] == "0001_init"
    assert database.migrate() == expected
    assert database.migrate() == []
    database.close()
    with pytest.raises(FileNotFoundError):
        Database(migrations_dir=tmp_path / "nope").migrate()


def test_customer_round_trip_and_unique_email(db: Database, now: datetime) -> None:
    created = db.add_customer("Ada Example", "ada@example.com", now)
    assert created.id is not None
    assert db.get_customer(created.id) == created
    assert db.find_customer_by_email("ada@example.com") == created
    assert db.find_customer_by_email("nobody@example.com") is None
    with pytest.raises(ValidationError):
        db.add_customer("Ada Again", "ada@example.com", now)
    with pytest.raises(NotFoundError):
        db.get_customer(999)


def test_invoice_round_trip_keeps_lines_and_due_date(db: Database, now: datetime) -> None:
    customer = db.add_customer("Bo Example", "bo@example.com", now)
    invoice = Invoice(
        id=None,
        number="INV-2026-00001",
        customer_id=customer.id,
        currency="EUR",
        status=InvoiceStatus.DRAFT,
        issued_at=date(2026, 3, 4),
        due_date=date(2026, 4, 3),
        lines=[InvoiceLine("SKU-1", "Widget", 2, Money(Decimal("4.25"), "EUR"))],
    )
    saved = db.save_invoice(invoice)
    assert saved.id is not None
    loaded = db.get_invoice(saved.id)
    assert loaded == saved
    assert loaded.total == Money(Decimal("8.50"), "EUR")
    assert db.list_invoices(status=InvoiceStatus.SENT) == []


def test_stock_adjustment(db: Database) -> None:
    db.upsert_stock("SKU-1", "Widget", 5)
    assert db.adjust_stock("SKU-1", -2).on_hand == 3
    with pytest.raises(NotFoundError):
        db.adjust_stock("SKU-404", 1)
