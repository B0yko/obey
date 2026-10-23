# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from ledgerline.errors import ValidationError
from ledgerline.generated import currency_codes
from ledgerline.money import Money, format_money, parse_amount, quantize, sum_money

ROOT = Path(__file__).resolve().parents[1]


def test_money_rounds_to_the_currency_minor_unit() -> None:
    assert Money(Decimal("10.005"), "EUR").amount == Decimal("10.01")
    assert Money(Decimal("1234.5"), "JPY").amount == Decimal("1235")
    assert quantize(Decimal("1.0005"), "KWD") == Decimal("1.001")


def test_money_addition_and_multiplication() -> None:
    price = Money(Decimal("19.99"), "USD")
    assert price * 3 == Money(Decimal("59.97"), "USD")
    assert price + price == Money(Decimal("39.98"), "USD")
    assert sum_money([], "USD") == Money.zero("USD")


def test_mixed_and_unknown_currencies_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Money(Decimal(1), "EUR") + Money(Decimal(1), "USD")
    with pytest.raises(ValidationError):
        Money(Decimal(1), "XXX")


def test_parse_amount_accepts_thousands_separators_and_rejects_junk() -> None:
    assert parse_amount(" 1,234.50 ") == Decimal("1234.50")
    for bad in ("abc", "NaN", ""):
        with pytest.raises(ValidationError):
            parse_amount(bad)


def test_format_money_uses_minor_units() -> None:
    assert format_money(Money(Decimal("1234.5"), "EUR")) == "1,234.50 EUR"
    assert format_money(Money(Decimal("1200"), "JPY")) == "1,200 JPY"


def test_generated_currency_module_matches_its_generator() -> None:
    script = ROOT / "scripts" / "gen_currency.py"
    spec = importlib.util.spec_from_file_location("gen_currency", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    on_disk = Path(currency_codes.__file__).read_text(encoding="utf-8")
    assert on_disk == module.render()
