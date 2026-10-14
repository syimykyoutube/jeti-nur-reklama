"""Navigation and catalog keyboards."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.i18n import t
from bot.callbacks import (
    AnalyticsPeriodCallback, PeriodChoiceCallback,
    CatalogFormCallback, DeleteOrderCallback, OrderConfirmCallback,
    OrderPageCallback, ProductCallback, ReceiptCallback,
)
from bot.services.stats import Period, period_token


def language_keyboard(lang: str, include_menu: bool = False) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text=t("language_ru", lang), callback_data="lang:ru"),
        InlineKeyboardButton(text=t("language_ky", lang), callback_data="lang:ky"),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("menu_catalog", lang))],
            [KeyboardButton(text=t("menu_analytics", lang))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def product_keyboard(product_id: int, lang: str, *, editing: bool = False) -> InlineKeyboardMarkup:
    actions = (("btn_edit", "edit"), ("btn_delete", "delete")) if editing else (("btn_select", "select"),)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(key, lang), callback_data=ProductCallback(action=action, product_id=product_id).pack())
        for key, action in actions
    ]])


def catalog_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("btn_add", lang), callback_data="catalog:add")],
    ])


def cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t("btn_cancel", lang), callback_data="catalog:cancel",
    )]])


def catalog_form_keyboard(lang: str, token: str, confirm_delete: bool = False) -> InlineKeyboardMarkup:
    options = (("yes", "yes"), ("no", "no")) if confirm_delete else (("field_name", "name"), ("field_price", "price"))
    rows = [
        [InlineKeyboardButton(text=t(key, lang), callback_data=CatalogFormCallback(action=action, token=token).pack()) for key, action in options],
    ]
    if not confirm_delete:
        rows.append([InlineKeyboardButton(text=t("btn_cancel", lang), callback_data=CatalogFormCallback(action="cancel", token=token).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def receipt_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t("btn_back", lang), callback_data="order:cancel",
    )]])


def delete_order_button(order_id: int, page: int, lang: str, number: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t("delete_order_button", lang),
        callback_data=DeleteOrderCallback(order_id=order_id, page=page, number=number).pack(),
    )]])


def delete_orders_keyboard(labels, page: int, pages: int, lang: str) -> InlineKeyboardMarkup:
    navigation = [InlineKeyboardButton(text=t(key, lang), callback_data=OrderPageCallback(page=target).pack())
                  for target, key in ((page - 1, "page_previous"), (page + 1, "page_next"))
                  if 0 <= target < pages]
    return InlineKeyboardMarkup(inline_keyboard=[navigation] if navigation else [])


def confirm_order_keyboard(lang: str, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=t(action, lang), callback_data=OrderConfirmCallback(action=action, token=token).pack(),
        ) for action in ("yes", "no")
    ]])


def analytics_period_keyboard(mode: str, lang: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=t(key, lang), callback_data=PeriodChoiceCallback(period=token).pack())
               for key, token in (("period_today_button", "t"), ("period_7", "d7"),
                                  ("period_30", "d30"), ("period_custom_button", "custom"),
                                  ("period_all_button", "all"))]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:3], buttons[3:4], buttons[4:]])


def analytics_navigation(mode: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t("change_period", lang), callback_data="analytics:menu",
    )]])


def analytics_keyboard(lang: str, period: Period) -> InlineKeyboardMarkup:
    def button(mode):
        return InlineKeyboardButton(text=t(f"analytics_{mode}", lang), callback_data=AnalyticsPeriodCallback(
            mode=mode, period=period_token(period.key), anchor=period.anchor,
        ).pack())
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("top"), button("chart")], [button("orders")], [button("word")],
        analytics_navigation("summary", lang).inline_keyboard[0],
    ])


def receipt_button(order_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=t("btn_receipt", lang), callback_data=ReceiptCallback(order_id=order_id).pack(),
    )]])


def analytics_orders_navigation(period: Period, page: int, pages: int, lang: str) -> InlineKeyboardMarkup:
    navigation = [InlineKeyboardButton(text=t(key, lang), callback_data=AnalyticsPeriodCallback(
        mode="orders", period=period_token(period.key), anchor=period.anchor, page=target,
    ).pack()) for target, key in ((page - 1, "page_previous"), (page + 1, "page_next"))
        if 0 <= target < pages]
    return InlineKeyboardMarkup(inline_keyboard=[navigation] if navigation else [])
