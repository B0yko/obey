# SPDX-License-Identifier: Apache-2.0
"""Business rules: customers, invoice lifecycle and stock movements."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta

from ledgerline.db import Database
from ledgerline.errors import InsufficientStockError, InvalidTransitionError, ValidationError
from ledgerline.generated.currency_codes import CURRENCY_MINOR_UNITS
from ledgerline.models import Customer, Invoice, InvoiceLine, InvoiceStatus, StockItem
from ledgerline.money import Money, sum_money

logger = logging.getLogger(__name__)

DEFAULT_TERMS_DAYS = 30


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InvoiceService:
    """Coordinates the database layer; pass ``clock`` to control time in tests."""

    def __init__(self, db: Database, clock: Callable[[], datetime] = _utcnow) -> None:
        self._db = db
        self._clock = clock

    # -- customers ----------------------------------------------------------

    def register_customer(self, name: str, email: str) -> Customer:
        name = name.strip()
        email = email.strip().lower()
        if not name:
            raise ValidationError("customer name must not be empty")
        local, _, domain = email.partition("@")
        if not local or "." not in domain:
            raise ValidationError(f"invalid email address: {email!r}")
        customer = self._db.add_customer(name, email, self._clock())
        logger.info("registered customer %s", customer.id)
        return customer

    def find_or_register_customer(self, name: str, email: str) -> Customer:
        existing = self._db.find_customer_by_email(email.strip().lower())
        return existing if existing is not None else self.register_customer(name, email)

    # -- stock --------------------------------------------------------------

    def receive_stock(self, sku: str, name: str, quantity: int) -> StockItem:
        """Add units to a tracked SKU, creating it on first receipt."""
        if quantity <= 0:
            raise ValidationError("received quantity must be positive")
        current = self._db.get_stock(sku)
        if current is None:
            return self._db.upsert_stock(sku, name, quantity)
        return self._db.adjust_stock(sku, quantity)

    # -- invoices -----------------------------------------------------------

    def create_invoice(
        self,
        customer_id: int,
        currency: str,
        lines: Sequence[InvoiceLine],
        terms_days: int = DEFAULT_TERMS_DAYS,
    ) -> Invoice:
        """Create a draft invoice numbered ``INV-<year>-<sequence>``."""
        if currency not in CURRENCY_MINOR_UNITS:
            raise ValidationError(f"unknown currency: {currency!r}")
        if not lines:
            raise ValidationError("an invoice needs at least one line")
        for line in lines:
            if line.quantity <= 0:
                raise ValidationError(f"quantity for {line.sku} must be positive")
            if line.unit_price.currency != currency:
                raise ValidationError(f"line {line.sku} is priced in {line.unit_price.currency}")
        self._db.get_customer(customer_id)
        issued = self._clock().date()
        prefix = f"INV-{issued.year}-"
        number = f"{prefix}{self._db.count_invoices_with_prefix(prefix) + 1:05d}"
        invoice = Invoice(
            id=None,
            number=number,
            customer_id=customer_id,
            currency=currency,
            status=InvoiceStatus.DRAFT,
            issued_at=issued,
            due_date=issued + timedelta(days=terms_days),
            lines=list(lines),
        )
        saved = self._db.save_invoice(invoice)
        logger.info("created invoice %s", saved.number)
        return saved

    def send_invoice(self, invoice_id: int) -> Invoice:
        """Move a draft to ``sent`` and take its stock-tracked lines out of inventory."""
        invoice = self._db.get_invoice(invoice_id)
        self._require_status(invoice, InvoiceStatus.DRAFT, InvoiceStatus.SENT)
        with self._db.transaction():
            for line in invoice.lines:
                stock = self._db.get_stock(line.sku)
                if stock is None:
                    continue  # untracked SKU, for example a service
                if stock.on_hand < line.quantity:
                    raise InsufficientStockError(
                        f"{line.sku}: need {line.quantity}, have {stock.on_hand}"
                    )
                self._db.adjust_stock(line.sku, -line.quantity)
            self._db.set_invoice_status(invoice_id, InvoiceStatus.SENT)
        logger.info("sent invoice %s", invoice.number)
        return self._db.get_invoice(invoice_id)

    def mark_paid(self, invoice_id: int) -> Invoice:
        invoice = self._db.get_invoice(invoice_id)
        self._require_status(invoice, InvoiceStatus.SENT, InvoiceStatus.PAID)
        self._db.set_invoice_status(invoice_id, InvoiceStatus.PAID)
        logger.info("invoice %s paid", invoice.number)
        return self._db.get_invoice(invoice_id)

    def void_invoice(self, invoice_id: int) -> Invoice:
        """Void a draft or sent invoice; a sent one puts its stock back."""
        invoice = self._db.get_invoice(invoice_id)
        if invoice.status not in (InvoiceStatus.DRAFT, InvoiceStatus.SENT):
            raise InvalidTransitionError(f"cannot void a {invoice.status} invoice")
        with self._db.transaction():
            if invoice.status is InvoiceStatus.SENT:
                for line in invoice.lines:
                    if self._db.get_stock(line.sku) is not None:
                        self._db.adjust_stock(line.sku, line.quantity)
            self._db.set_invoice_status(invoice_id, InvoiceStatus.VOID)
        logger.info("voided invoice %s", invoice.number)
        return self._db.get_invoice(invoice_id)

    # -- reports ------------------------------------------------------------

    def overdue_invoices(self, today: date | None = None) -> list[Invoice]:
        """Sent invoices whose due date is before ``today`` (default: the clock's date)."""
        cutoff = today or self._clock().date()
        sent = self._db.list_invoices(status=InvoiceStatus.SENT)
        return [inv for inv in sent if inv.due_date is not None and inv.due_date < cutoff]

    def outstanding_balance(self, customer_id: int) -> dict[str, Money]:
        """Unpaid (sent) totals for a customer, one entry per currency."""
        balances: dict[str, Money] = {}
        for invoice in self._db.list_invoices(InvoiceStatus.SENT, customer_id):
            current = balances.get(invoice.currency, Money.zero(invoice.currency))
            balances[invoice.currency] = sum_money([current, invoice.total], invoice.currency)
        return balances

    @staticmethod
    def _require_status(invoice: Invoice, expected: InvoiceStatus, target: InvoiceStatus) -> None:
        if invoice.status is not expected:
            raise InvalidTransitionError(
                f"invoice {invoice.number} is {invoice.status}; only {expected} can become {target}"
            )
