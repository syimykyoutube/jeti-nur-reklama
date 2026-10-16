"""Product cards and isolated, cancellable catalog dialogs."""

from uuid import uuid4
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.callbacks import CatalogFormCallback, ProductCallback
from bot.db import Database, Product
from bot.handlers.start import show_language_picker
from bot.i18n import format_money, t, variants
from bot.keyboards import (
    cancel_keyboard, catalog_form_keyboard, catalog_keyboard,
    main_menu_keyboard, product_keyboard,
)
from bot.services.catalog import validate_name, validate_price
from bot.services.messages import edit_message


class CatalogStates(StatesGroup):
    add_name = State()
    add_price = State()
    edit_choice = State()
    edit_name = State()
    edit_price = State()
    delete_confirm = State()


def product_card(product: Product, lang: str) -> str:
    return t("product_card", lang, name=escape(product.name), price=format_money(product.price, lang))


async def show_catalog(message: Message, database: Database, lang: str, *, editing: bool = False) -> None:
    if editing:
        await message.answer(t("catalog_edit_mode", lang), reply_markup=main_menu_keyboard(lang))
    products = await database.list_active_products()
    for product in products:
        await message.answer(product_card(product, lang), reply_markup=product_keyboard(product.id, lang, editing=editing))
    if not products:
        await message.answer(t("catalog_empty", lang))
        if not editing:
            await message.answer(t("catalog_edit_hint", lang))
    if editing:
        await message.answer(t("catalog_actions", lang), reply_markup=catalog_keyboard(lang))


async def show_catalog_editor(message: Message, database: Database, lang: str) -> None:
    await show_catalog(message, database, lang, editing=True)


async def open_catalog(message: Message, database: Database, state: FSMContext, lang: str, language_selected: bool) -> None:
    await state.clear()
    if not language_selected:
        await show_language_picker(message, lang)
        return
    await show_catalog(message, database, lang)


async def open_catalog_editor(message: Message, database: Database, state: FSMContext, lang: str, language_selected: bool) -> None:
    await state.clear()
    if not language_selected:
        await show_language_picker(message, lang)
        return
    await show_catalog_editor(message, database, lang)


async def usable_callback(callback: CallbackQuery, lang: str, language_selected: bool) -> bool:
    if not isinstance(callback.message, Message):
        await callback.answer(t("invalid_button", lang), show_alert=True)
        return False
    if not language_selected:
        await callback.answer()
        await show_language_picker(callback.message, lang)
        return False
    return True


async def begin_dialog(state: FSMContext, step: State, product_id: int | None = None) -> str:
    await state.clear()
    token = uuid4().hex[:16]
    await state.set_data({"token": token, "product_id": product_id})
    await state.set_state(step)
    return token


async def add_product(callback: CallbackQuery, state: FSMContext, lang: str, language_selected: bool) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    await callback.answer()
    await begin_dialog(state, CatalogStates.add_name)
    await callback.message.answer(t("ask_name", lang), reply_markup=cancel_keyboard(lang))


async def product_action(
    callback: CallbackQuery, callback_data: ProductCallback, database: Database,
    state: FSMContext, lang: str, language_selected: bool,
) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    if callback_data.action not in {"edit", "delete"}:
        await callback.answer(t("invalid_button", lang), show_alert=True)
        return
    product = await database.get_active_product(callback_data.product_id)
    if product is None:
        await callback.answer(t("product_unavailable", lang), show_alert=True)
        return
    await callback.answer()
    is_delete = callback_data.action == "delete"
    token = await begin_dialog(
        state, CatalogStates.delete_confirm if is_delete else CatalogStates.edit_choice, product.id,
    )
    text = t("confirm_product_delete", lang, card=product_card(product, lang), question=t("confirm_delete", lang)) if is_delete else t("edit_field", lang)
    keyboard = catalog_form_keyboard(lang, token, confirm_delete=is_delete)
    if is_delete:
        message_id = await edit_message(callback.message, text, keyboard)
        await state.update_data(message_id=message_id)
    else:
        await callback.message.answer(text, reply_markup=keyboard)


async def cancelled(message: Message, database: Database, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer(t("cancelled", lang), reply_markup=main_menu_keyboard(lang))
    await show_catalog_editor(message, database, lang)


async def cancel_inline(callback: CallbackQuery, database: Database, state: FSMContext,
                        lang: str, language_selected: bool) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    if await state.get_state() not in CatalogStates.__all_states_names__:
        await callback.answer(t("form_expired", lang), show_alert=True)
        return
    await callback.answer()
    await cancelled(callback.message, database, state, lang)


async def cancel_message(message: Message, database: Database, state: FSMContext, lang: str, language_selected: bool) -> None:
    if not language_selected:
        await state.clear()
        await show_language_picker(message, lang)
        return
    if await state.get_state() in CatalogStates.__all_states_names__:
        await cancelled(message, database, state, lang)
    else:
        await state.clear()
        await message.answer(t("cancelled", lang), reply_markup=main_menu_keyboard(lang))
        await show_catalog(message, database, lang)


async def finish_change(message: Message, database: Database, state: FSMContext, lang: str, changed: bool) -> None:
    await state.clear()
    await message.answer(t("updated" if changed else "product_unavailable", lang), reply_markup=main_menu_keyboard(lang))
    await show_catalog_editor(message, database, lang)


async def form_action(
    callback: CallbackQuery, callback_data: CatalogFormCallback, database: Database,
    state: FSMContext, lang: str, language_selected: bool,
) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    data = await state.get_data()
    step = await state.get_state()
    if not step or data.get("token") != callback_data.token:
        await callback.answer(t("form_expired", lang), show_alert=True)
        return
    if step == CatalogStates.delete_confirm.state and data.get("message_id") != callback.message.message_id:
        await callback.answer(t("form_expired", lang), show_alert=True)
        return
    action = callback_data.action
    if step == CatalogStates.delete_confirm.state and action in {"no", "cancel"}:
        await callback.answer()
        await state.clear()
        await edit_message(callback.message, t("delete_cancelled", lang))
        await show_catalog_editor(callback.message, database, lang)
        return
    if action == "cancel":
        await callback.answer()
        await cancelled(callback.message, database, state, lang)
        return
    if step == CatalogStates.edit_choice.state and action in {"name", "price"}:
        product = await database.get_active_product(data["product_id"])
        await callback.answer()
        if product is None:
            await finish_change(callback.message, database, state, lang, False)
            return
        await state.set_state(CatalogStates.edit_name if action == "name" else CatalogStates.edit_price)
        await callback.message.answer(t("ask_name" if action == "name" else "ask_price", lang), reply_markup=cancel_keyboard(lang))
        return
    if step == CatalogStates.delete_confirm.state and action == "yes":
        changed = await database.soft_delete_product(data["product_id"])
        await state.clear()
        await callback.answer()
        await callback.message.answer(t("product_deleted" if changed else "product_unavailable", lang))
        await show_catalog_editor(callback.message, database, lang)
        return
    await callback.answer(t("form_expired", lang), show_alert=True)


async def add_name(message: Message, state: FSMContext, lang: str) -> None:
    try:
        name = validate_name(message.text)
    except ValueError:
        await message.answer(t("invalid_name", lang), reply_markup=cancel_keyboard(lang))
        return
    await state.update_data(name=name)
    await state.set_state(CatalogStates.add_price)
    await message.answer(t("ask_price", lang), reply_markup=cancel_keyboard(lang))


async def add_price(message: Message, database: Database, state: FSMContext, lang: str) -> None:
    try:
        price = validate_price(message.text)
    except ValueError:
        await message.answer(t("invalid_price", lang), reply_markup=cancel_keyboard(lang))
        return
    data = await state.get_data()
    await database.add_product(data["name"], price)
    await state.clear()
    await message.answer(t("added", lang), reply_markup=main_menu_keyboard(lang))
    await show_catalog_editor(message, database, lang)


async def edit_value(message: Message, database: Database, state: FSMContext, lang: str) -> None:
    step = await state.get_state()
    data = await state.get_data()
    if await database.get_active_product(data["product_id"]) is None:
        await finish_change(message, database, state, lang, False)
        return
    is_name = step == CatalogStates.edit_name.state
    try:
        value = validate_name(message.text) if is_name else validate_price(message.text)
    except ValueError:
        await message.answer(t("invalid_name" if is_name else "invalid_price", lang), reply_markup=cancel_keyboard(lang))
        return
    changed = await database.update_product_name(data["product_id"], value) if is_name else await database.update_product_price(data["product_id"], value)
    await finish_change(message, database, state, lang, changed)


def create_router() -> Router:
    router = Router(name="catalog")
    router.message.register(open_catalog, F.text.in_(variants("menu_catalog")))
    router.message.register(cancel_message, Command("cancel"))
    router.message.register(cancel_message, F.text.in_(variants("btn_cancel")))
    router.callback_query.register(add_product, F.data == "catalog:add")
    router.callback_query.register(cancel_inline, F.data == "catalog:cancel")
    router.callback_query.register(product_action, ProductCallback.filter())
    router.callback_query.register(form_action, CatalogFormCallback.filter())
    router.message.register(add_name, CatalogStates.add_name, F.text)
    router.message.register(add_price, CatalogStates.add_price, F.text)
    router.message.register(edit_value, CatalogStates.edit_name, F.text)
    router.message.register(edit_value, CatalogStates.edit_price, F.text)
    return router
