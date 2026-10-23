# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledgerline.db import Database
from ledgerline.errors import (
    InsufficientStockError,
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
)
from ledgerline.models import InvoiceLine, InvoiceStatus
from ledgerline.money import Money
from ledgerline.service import InvoiceService


def line(sku: str, quantity: int, price: str, currency: str = "EUR") -> InvoiceLine:
    return InvoiceLine(sku, f"Item {sku}", quantity, Money(Decimal(price), currency))


@pytest.fixture
def customer_id(service: InvoiceService) -> int:
    customer = service.register_customer("Cy Example", "Cy@Example.com")
    assert customer.id is not None
    return customer.id


def test_register_customer_normalises_and_validates(service: InvoiceService) -> None:
    customer = service.register_customer("  Cy Example ", "Cy@Example.com")
    assert (customer.name, customer.email) == ("Cy Example", "cy@example.com")
    with pytest.raises(ValidationError):
        service.register_customer("", "x@example.com")
    with pytest.raises(ValidationError):
        service.register_customer("No At", "not-an-email")


def test_create_invoice_numbers_sequentially_and_sets_due_date(
    service: InvoiceService, customer_id: int
) -> None:
    first = service.create_invoice(customer_id, "EUR", [line("A", 2, "10.00")])
    second = service.create_invoice(customer_id, "EUR", [line("A", 1, "10.00")], terms_days=14)
    assert (first.number, second.number) == ("INV-2026-00001", "INV-2026-00002")
    assert first.due_date == date(2026, 4, 3)
    assert second.due_date == date(2026, 3, 18)
    assert first.status is InvoiceStatus.DRAFT
    assert first.total == Money(Decimal("20.00"), "EUR")


def test_create_invoice_rejects_bad_input(service: InvoiceService, customer_id: int) -> None:
    with pytest.raises(ValidationError):
        service.create_invoice(customer_id, "EUR", [])
    with pytest.raises(ValidationError):
        service.create_invoice(customer_id, "XXX", [line("A", 1, "1")])
    with pytest.raises(ValidationError):
        service.create_invoice(customer_id, "EUR", [line("A", 1, "1", currency="USD")])
    with pytest.raises(NotFoundError):
        service.create_invoice(999, "EUR", [line("A", 1, "1")])


def test_send_invoice_takes_stock_out(
    service: InvoiceService, db: Database, customer_id: int
) -> None:
    service.receive_stock("A", "Item A", 5)
    invoice = service.create_invoice(customer_id, "EUR", [line("A", 2, "3"), line("SVC", 1, "50")])
    assert invoice.id is not None
    sent = service.send_invoice(invoice.id)
    assert sent.status is InvoiceStatus.SENT
    stock = db.get_stock("A")
    assert stock is not None and stock.on_hand == 3
    assert db.get_stock("SVC") is None


def test_send_invoice_with_too_little_stock_changes_nothing(
    service: InvoiceService, db: Database, customer_id: int
) -> None:
    service.receive_stock("A", "Item A", 1)
    service.receive_stock("B", "Item B", 1)
    invoice = service.create_invoice(customer_id, "EUR", [line("A", 1, "3"), line("B", 2, "3")])
    assert invoice.id is not None
    with pytest.raises(InsufficientStockError):
        service.send_invoice(invoice.id)
    stock = db.get_stock("A")
    assert stock is not None and stock.on_hand == 1
    assert db.get_invoice(invoice.id).status is InvoiceStatus.DRAFT


def test_status_transitions_are_enforced(service: InvoiceService, customer_id: int) -> None:
    invoice = service.create_invoice(customer_id, "EUR", [line("A", 1, "3")])
    assert invoice.id is not None
    with pytest.raises(InvalidTransitionError):
        service.mark_paid(invoice.id)
    service.send_invoice(invoice.id)
    assert service.mark_paid(invoice.id).status is InvoiceStatus.PAID
    with pytest.raises(InvalidTransitionError):
        service.void_invoice(invoice.id)


def test_void_sent_invoice_restores_stock(
    service: InvoiceService, db: Database, customer_id: int
) -> None:
    service.receive_stock("A", "Item A", 4)
    invoice = service.create_invoice(customer_id, "EUR", [line("A", 3, "3")])
    assert invoice.id is not None
    service.send_invoice(invoice.id)
    assert service.void_invoice(invoice.id).status is InvoiceStatus.VOID
    stock = db.get_stock("A")
    assert stock is not None and stock.on_hand == 4


def test_overdue_and_outstanding_balance(service: InvoiceService, customer_id: int) -> None:
    short = service.create_invoice(customer_id, "EUR", [line("A", 1, "10")], terms_days=5)
    long = service.create_invoice(customer_id, "USD", [line("A", 1, "7.50", "USD")], terms_days=60)
    for invoice in (short, long):
        assert invoice.id is not None
        service.send_invoice(invoice.id)
    assert [inv.number for inv in service.overdue_invoices(date(2026, 3, 20))] == [short.number]
    assert service.overdue_invoices(date(2026, 3, 4)) == []
    balance = service.outstanding_balance(customer_id)
    assert balance == {"EUR": Money(Decimal("10"), "EUR"), "USD": Money(Decimal("7.5"), "USD")}
