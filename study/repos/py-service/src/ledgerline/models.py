# SPDX-License-Identifier: Apache-2.0
"""Plain data classes shared by the database layer, the service and the importers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from ledgerline.money import Money, sum_money


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    VOID = "void"


@dataclass(frozen=True, slots=True)
class Customer:
    id: int | None
    name: str
    email: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    sku: str
    description: str
    quantity: int
    unit_price: Money

    @property
    def amount(self) -> Money:
        return self.unit_price * self.quantity


@dataclass(slots=True)
class Invoice:
    id: int | None
    number: str
    customer_id: int | None
    currency: str
    status: InvoiceStatus
    issued_at: date
    due_date: date | None
    lines: list[InvoiceLine] = field(default_factory=list)

    @property
    def total(self) -> Money:
        return sum_money((line.amount for line in self.lines), self.currency)


@dataclass(frozen=True, slots=True)
class StockItem:
    sku: str
    name: str
    on_hand: int
