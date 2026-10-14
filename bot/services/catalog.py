"""Catalog input validation, independent of Telegram and SQLite."""

from decimal import Decimal
import math
import re


PRICE_PATTERN = re.compile(r"(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)")


def validate_name(value: str | None) -> str:
    if value is None:
        raise ValueError("Product name must be text")
    name = " ".join(value.split())
    if not 1 <= len(name) <= 60 or not name.isprintable():
        raise ValueError("Product name must contain 1 to 60 printable characters")
    return name


def validate_price(value: str | None) -> float:
    """Accept decimal comma or dot; reject non-finite and ambiguous input."""
    if value is None:
        raise ValueError("Product price must be text")
    text = value.strip()
    if len(text) > 100 or PRICE_PATTERN.fullmatch(text) is None:
        raise ValueError("Product price must be a decimal number")
    number = Decimal(text.replace(",", "."))
    return validate_price_amount(number)


def validate_price_amount(value: Decimal | float | int) -> float:
    """Validate numeric values again at the database boundary."""
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Product price must be finite")
    if not 0 < number < 1_000_000:
        raise ValueError("Product price must be greater than 0 and less than 1000000")
    price = float(number)
    if not math.isfinite(price) or not 0 < price < 1_000_000:
        raise ValueError("Product price cannot be stored within the allowed range")
    return price
