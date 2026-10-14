"""Receipt-backed orders and paginated, confirmed soft deletion."""

from datetime import datetime
from html import escape
from uuid import uuid4

from aiogram import F, Router
from aiogram.enums import ContentType
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.callbacks import (
    DeleteOrderCallback, OrderConfirmCallback, OrderPageCallback, ProductCallback,
)
from bot.config import Config
from bot.db import Database, Order
from bot.handlers.catalog import open_catalog, show_catalog, usable_callback
from bot.handlers.start import show_language_picker, delete_unexpected_message
from bot.i18n import format_datetime, format_money, t, variants
from bot.keyboards import (
    confirm_order_keyboard, delete_orders_keyboard, delete_order_button, main_menu_keyboard, receipt_keyboard,
)


class OrderStates(StatesGroup):
    awaiting_receipt = State()
    delete_choice = State()
    delete_confirm = State()


def order_card(order: Order, number: int, config: Config, lang: str) -> str:
    return t("order_card", lang, number=number, name=escape(order.product_name),
             price=format_money(order.price, lang),
             date=format_datetime(datetime.fromisoformat(order.created_at), lang, config.timezone),
             author=escape(order.created_by_name or str(order.created_by)))


async def select_product(
    callback: CallbackQuery, callback_data: ProductCallback, database: Database,
    state: FSMContext, lang: str, language_selected: bool,
) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    product = await database.get_active_product(callback_data.product_id)
    if product is None:
        await callback.answer(t("product_unavailable", lang), show_alert=True)
        return
    await state.clear()
    # Quote the current product once; a later catalog edit must not change it.
    await state.set_data({"product_id": product.id, "product_name": product.name, "price": product.price})
    await state.set_state(OrderStates.awaiting_receipt)
    await callback.answer()
    await callback.message.answer(
        t("ask_receipt", lang, name=escape(product.name), price=format_money(product.price, lang)),
        reply_markup=receipt_keyboard(lang),
    )


async def receive_receipt(message: Message, database: Database, state: FSMContext, lang: str) -> None:
    if message.content_type == ContentType.PHOTO:
        receipt = message.photo[-1]
        receipt_type = "photo"
        file_name = None
    elif message.content_type == ContentType.DOCUMENT:
        receipt = message.document
        receipt_type = "document"
        file_name = receipt.file_name
    else:
        await delete_unexpected_message(message)
        await message.answer(t("receipt_wrong", lang), reply_markup=receipt_keyboard(lang))
        return
    data = await state.get_data()
    await database.add_order(
        product_id=data["product_id"], product_name=data["product_name"], price=data["price"],
        created_by=message.from_user.id, created_by_name=message.from_user.full_name,
        receipt_file_id=receipt.file_id, receipt_file_unique_id=receipt.file_unique_id,
        receipt_type=receipt_type, receipt_file_name=file_name,
    )
    await state.clear()
    await message.answer(t("order_saved", lang), reply_markup=main_menu_keyboard(lang))
    await show_catalog(message, database, lang)


async def show_delete_page(
    message: Message, database: Database, state: FSMContext, config: Config, lang: str, page: int = 0,
) -> None:
    result = await database.get_orders_page(page)
    await state.clear()
    await state.set_data({"page": result.page})
    await state.set_state(OrderStates.delete_choice)
    if not result.orders:
        await message.answer(t("no_orders_to_delete", lang))
        return
    for number, order in enumerate(result.orders, result.page * 10 + 1):
        await message.answer(order_card(order, number, config, lang),
                             reply_markup=delete_order_button(order.id, result.page, lang, number))
    if result.total > 10:
        await message.answer(t("pagination", lang),
                             reply_markup=delete_orders_keyboard([], result.page, result.pages, lang))


async def open_delete_orders(
    message: Message, database: Database, state: FSMContext, config: Config,
    lang: str, language_selected: bool,
) -> None:
    await state.clear()
    if not language_selected:
        await show_language_picker(message, lang)
        return
    await show_delete_page(message, database, state, config, lang)


async def page_callback(
    callback: CallbackQuery, callback_data: OrderPageCallback, database: Database,
    state: FSMContext, config: Config, lang: str, language_selected: bool,
) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    await callback.answer()
    await show_delete_page(callback.message, database, state, config, lang, callback_data.page)


async def choose_delete_order(
    callback: CallbackQuery, callback_data: DeleteOrderCallback, database: Database,
    state: FSMContext, config: Config, lang: str, language_selected: bool,
) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    order = await database.get_active_order(callback_data.order_id)
    if order is None:
        await callback.answer(t("order_unavailable", lang), show_alert=True)
        return
    token = uuid4().hex
    await state.clear()
    page = await database.get_orders_page(callback_data.page)
    position = next((index for index, item in enumerate(page.orders, 1) if item.id == order.id), 1)
    await state.set_data({"order_id": order.id, "page": page.page, "token": token,
                          "number": callback_data.number or page.page * 10 + position,
                          "message_id": callback.message.message_id})
    await state.set_state(OrderStates.delete_confirm)
    await callback.answer()
    await callback.message.edit_text(
        t("confirm_delete", lang),
        reply_markup=confirm_order_keyboard(lang, token),
    )


async def confirm_delete_order(
    callback: CallbackQuery, callback_data: OrderConfirmCallback, database: Database,
    state: FSMContext, config: Config, lang: str, language_selected: bool,
) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    data = await state.get_data()
    if (
        await state.get_state() != OrderStates.delete_confirm.state
        or data.get("token") != callback_data.token
        or data.get("message_id") != callback.message.message_id
        or callback_data.action not in {"yes", "no"}
    ):
        await callback.answer(t("order_dialog_expired", lang), show_alert=True)
        return
    await callback.answer()
    if callback_data.action == "no":
        await state.clear()
        await callback.message.edit_text(t("delete_cancelled", lang), reply_markup=None)
        return
    if callback_data.action == "yes":
        changed = await database.soft_delete_order(data["order_id"], callback.from_user.id)
        await callback.message.edit_text(t("order_deleted" if changed else "order_unavailable", lang))
    await state.clear()


async def cancel_order(message: Message, database: Database, state: FSMContext, lang: str) -> None:
    waiting_for_receipt = await state.get_state() == OrderStates.awaiting_receipt.state
    await state.clear()
    await message.answer(t("cancelled", lang), reply_markup=main_menu_keyboard(lang))
    if waiting_for_receipt:
        await show_catalog(message, database, lang)


async def cancel_receipt_callback(callback: CallbackQuery, database: Database, state: FSMContext,
                                  lang: str, language_selected: bool) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    if await state.get_state() != OrderStates.awaiting_receipt.state:
        await callback.answer(t("order_dialog_expired", lang), show_alert=True)
        return
    await callback.answer()
    await cancel_order(callback.message, database, state, lang)


def create_router() -> Router:
    router = Router(name="orders")
    states = StateFilter(OrderStates.awaiting_receipt, OrderStates.delete_choice, OrderStates.delete_confirm)
    router.message.register(open_delete_orders, Command("deleteorder"))
    router.message.register(open_catalog, F.text.in_(variants("menu_catalog")))
    router.message.register(cancel_order, states, Command("cancel"))
    router.message.register(cancel_order, states, F.text.in_(variants("btn_cancel")))
    router.message.register(cancel_order, OrderStates.awaiting_receipt, F.text.in_(variants("btn_back")))
    router.callback_query.register(cancel_receipt_callback, F.data == "order:cancel")
    router.callback_query.register(select_product, ProductCallback.filter(F.action == "select"))
    router.callback_query.register(page_callback, OrderPageCallback.filter())
    router.callback_query.register(choose_delete_order, DeleteOrderCallback.filter())
    router.callback_query.register(confirm_delete_order, OrderConfirmCallback.filter())
    router.message.register(receive_receipt, OrderStates.awaiting_receipt,
                            F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
    return router
