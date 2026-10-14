"""Typed catalog and order callback payloads."""

from aiogram.filters.callback_data import CallbackData
from pydantic import Field, field_validator
from typing import Literal


AnalyticsMode = Literal["summary", "top", "chart", "orders", "word"]
AnalyticsPeriod = str


class ProductCallback(CallbackData, prefix="product"):
    action: str
    product_id: int = Field(gt=0, le=2**63 - 1)


class CatalogFormCallback(CallbackData, prefix="catalog_form"):
    action: str
    token: str


class OrderPageCallback(CallbackData, prefix="order_page"):
    page: int = Field(ge=0, le=2**31 - 1)


class DeleteOrderCallback(CallbackData, prefix="order_delete"):
    order_id: int = Field(gt=0, le=2**63 - 1)
    page: int = Field(ge=0, le=2**31 - 1)
    number: int = Field(default=0, ge=0, le=2**63 - 1)


class OrderConfirmCallback(CallbackData, prefix="order_confirm"):
    action: str
    token: str


class AnalyticsKindCallback(CallbackData, prefix="analytics"):
    mode: AnalyticsMode


class AnalyticsPeriodCallback(CallbackData, prefix="an"):
    mode: AnalyticsMode
    period: str = Field(pattern=r"^(t|all|d[1-9][0-9]?)$")
    anchor: int = Field(default=0, ge=0, le=253402300799999999)
    page: int = Field(default=0, ge=0, le=2**31 - 1)

    @field_validator("period", mode="before")
    @classmethod
    def normalize_period(cls, value):
        # Also accept the service's numeric key when building payloads internally.
        from bot.services.stats import period_token
        if isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= int(value) <= 99:
            return period_token(str(int(value)))
        return value


class PeriodChoiceCallback(CallbackData, prefix="period"):
    period: Literal["t", "d7", "d30", "all", "custom"]


class AnalyticsPageCallback(CallbackData, prefix="analytics_page"):
    period: AnalyticsPeriod
    anchor: int = Field(ge=0, le=253402300799999999)
    page: int = Field(ge=0, le=2**31 - 1)


class ReceiptCallback(CallbackData, prefix="receipt"):
    order_id: int = Field(gt=0, le=2**63 - 1)
