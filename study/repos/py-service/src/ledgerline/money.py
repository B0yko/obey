# SPDX-License-Identifier: Apache-2.0
"""Exact money arithmetic on top of Decimal."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ledgerline.errors import ValidationError
from ledgerline.generated.currency_codes import CURRENCY_MINOR_UNITS


def minor_units(currency: str) -> int:
    """Return the number of decimal digits the currency uses (JPY: 0, EUR: 2, KWD: 3)."""
    try:
        return CURRENCY_MINOR_UNITS[currency]
    except KeyError:
        raise ValidationError(f"unknown currency: {currency!r}") from None


def quantize(amount: Decimal, currency: str) -> Decimal:
    """Round an amount to the currency's minor unit, half up."""
    step = Decimal(1).scaleb(-minor_units(currency))
    return amount.quantize(step, rounding=ROUND_HALF_UP)


def parse_amount(text: str) -> Decimal:
    """Parse a user-typed amount such as ``"1,234.50"``."""
    cleaned = text.strip().replace(",", "").replace(" ", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValidationError(f"not a valid amount: {text!r}") from None
    if not value.is_finite():
        raise ValidationError(f"not a valid amount: {text!r}")
    return value


@dataclass(frozen=True, slots=True)
class Money:
    """An amount in a single currency, always rounded to that currency's minor unit."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", quantize(self.amount, self.currency))

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal(0), currency)

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if other.currency != self.currency:
            raise ValidationError(f"cannot add {other.currency} to {self.currency}")
        return Money(self.amount + other.amount, self.currency)

    def __mul__(self, factor: int | Decimal) -> Money:
        return Money(self.amount * factor, self.currency)

    def __str__(self) -> str:
        return format_money(self)


def format_money(money: Money) -> str:
    """Format as ``"1,234.50 EUR"``."""
    digits = minor_units(money.currency)
    return f"{money.amount:,.{digits}f} {money.currency}"


def sum_money(items: Iterable[Money], currency: str) -> Money:
    """Sum money values; an empty iterable gives zero in ``currency``."""
    result = Money.zero(currency)
    for item in items:
        result = result + item
    return result
