# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from ledgerline.db import Database
from ledgerline.errors import PayloadError
from ledgerline.importers import import_order, load_payload, parse_order_webhook
from ledgerline.money import Money
from ledgerline.service import InvoiceService

MUG: dict[str, object] = {"sku": "MUG-01", "title": "Enamel mug", "qty": 2, "price": "8.50"}
TOTE: dict[str, object] = {"sku": "TOTE-02", "title": "Tote bag", "qty": 1, "price": 12}


def make_payload(
    event: str = "order.paid",
    created: str = "2026-03-04",
    email: str = "dee@example.com",
    items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "event": event,
        "data": {
            "order": {
                "id": "ord_1001",
                "created": created,
                "currency": "eur",
                "customer": {"name": "Dee Example", "email": email},
                "items": [MUG, TOTE] if items is None else items,
            }
        },
    }


def test_parse_order_webhook_happy_path() -> None:
    order = parse_order_webhook(make_payload())
    assert order.external_id == "ord_1001"
    assert order.currency == "EUR"
    assert order.created == date(2026, 3, 4)
    assert [ln.sku for ln in order.lines] == ["MUG-01", "TOTE-02"]
    assert order.lines[0].unit_price == Money(Decimal("8.50"), "EUR")
    assert order.lines[1].unit_price == Money(Decimal("12"), "EUR")


def test_load_payload_requires_a_json_object() -> None:
    assert load_payload(json.dumps(make_payload()))["event"] == "order.paid"
    with pytest.raises(PayloadError):
        load_payload("{not json")
    with pytest.raises(PayloadError):
        load_payload("[1, 2]")


@pytest.mark.parametrize(
    "payload",
    [
        make_payload(event="order.refunded"),
        make_payload(created="04/03/2026"),
        make_payload(items=[{**MUG, "qty": "2"}]),
    ],
    ids=["event", "date", "qty-type"],
)
def test_parse_order_webhook_rejects_malformed_payloads(payload: dict[str, object]) -> None:
    with pytest.raises(PayloadError):
        parse_order_webhook(payload)


def test_import_order_creates_one_customer_and_a_draft_invoice(
    service: InvoiceService, db: Database
) -> None:
    order = parse_order_webhook(make_payload())
    first = import_order(service, order)
    second = import_order(service, order)
    assert first.number != second.number
    assert first.customer_id == second.customer_id
    assert first.total == Money(Decimal("29"), "EUR")
    assert len(db.list_invoices()) == 2
