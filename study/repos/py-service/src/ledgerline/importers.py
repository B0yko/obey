# SPDX-License-Identifier: Apache-2.0
"""Turn a third-party "order paid" webhook payload into an invoice.

The payload comes from a shop platform we do not control and has no published schema,
so every field is checked by hand before it reaches the domain models.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ledgerline.errors import PayloadError, ValidationError
from ledgerline.models import Invoice, InvoiceLine
from ledgerline.money import Money, parse_amount
from ledgerline.service import InvoiceService

logger = logging.getLogger(__name__)

SUPPORTED_EVENT = "order.paid"


@dataclass(frozen=True, slots=True)
class ImportedOrder:
    external_id: str
    customer_name: str
    customer_email: str
    currency: str
    created: date
    lines: list[InvoiceLine]


def load_payload(raw: str) -> dict[str, object]:
    """Decode a JSON document whose top level must be an object."""
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PayloadError(f"payload is not valid JSON: {exc.msg}") from exc
    return _mapping(decoded, "payload")


def parse_order_webhook(payload: dict[str, object]) -> ImportedOrder:
    """Validate an ``order.paid`` event and convert it to an :class:`ImportedOrder`."""
    event = _text(payload, "event", "payload")
    if event != SUPPORTED_EVENT:
        raise PayloadError(f"unsupported event: {event!r}")
    data = _mapping(payload.get("data"), "data")
    order = _mapping(data.get("order"), "data.order")
    customer = _mapping(order.get("customer"), "data.order.customer")
    currency = _text(order, "currency", "data.order").upper()
    items = order.get("items")
    if not isinstance(items, list) or not items:
        raise PayloadError("data.order.items must be a non-empty list")
    return ImportedOrder(
        external_id=_text(order, "id", "data.order"),
        customer_name=_text(customer, "name", "data.order.customer"),
        customer_email=_text(customer, "email", "data.order.customer"),
        currency=currency,
        created=_parse_date(_text(order, "created", "data.order")),
        lines=[_parse_item(item, position, currency) for position, item in enumerate(items)],
    )


def import_order(service: InvoiceService, order: ImportedOrder) -> Invoice:
    """Create a draft invoice for an imported order, registering the customer if needed."""
    customer = service.find_or_register_customer(order.customer_name, order.customer_email)
    if customer.id is None:
        raise ValidationError("customer was not persisted")
    invoice = service.create_invoice(customer.id, order.currency, order.lines)
    logger.info("imported order %s as invoice %s", order.external_id, invoice.number)
    return invoice


def _parse_item(item: object, position: int, currency: str) -> InvoiceLine:
    where = f"data.order.items[{position}]"
    fields = _mapping(item, where)
    quantity = fields.get("qty")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise PayloadError(f"{where}.qty must be an integer")
    return InvoiceLine(
        sku=_text(fields, "sku", where),
        description=_text(fields, "title", where),
        quantity=quantity,
        unit_price=Money(_amount(fields.get("price"), f"{where}.price"), currency),
    )


def _mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PayloadError(f"{where} must be an object")
    return value


def _text(mapping: dict[str, object], key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PayloadError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def _amount(value: object, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise PayloadError(f"{where} must be a number or a numeric string")
    try:
        return parse_amount(str(value))
    except ValidationError as exc:
        raise PayloadError(f"{where}: {exc}") from exc


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PayloadError(f"unrecognised date: {value!r}") from None
