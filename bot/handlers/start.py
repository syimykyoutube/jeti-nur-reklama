"""Onboarding, language selection, public ID lookup, and navigation."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import Database
from bot.i18n import SUPPORTED_LANGUAGES, t
from bot.keyboards import language_keyboard, main_menu_keyboard, receipt_keyboard


async def show_language_picker(message: Message, lang: str, include_menu: bool = False) -> None:
    await message.answer(t("choose_lang", lang), reply_markup=language_keyboard(lang, include_menu))


async def show_main_menu(message: Message, lang: str) -> None:
    await message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))


async def my_id(message: Message, lang: str) -> None:
    if message.from_user is not None:
        await message.answer(t("my_id", lang, user_id=message.from_user.id))


async def start(message: Message, lang: str, language_selected: bool, state: FSMContext) -> None:
    await state.clear()
    if language_selected:
        await show_main_menu(message, lang)
    else:
        await show_language_picker(message, lang)


async def choose_language(message: Message, lang: str, language_selected: bool, state: FSMContext) -> None:
    await state.clear()
    await show_language_picker(message, lang)


async def set_language(callback: CallbackQuery, database: Database, lang: str, state: FSMContext) -> None:
    selected_lang = (callback.data or "").removeprefix("lang:")
    if selected_lang not in SUPPORTED_LANGUAGES or not isinstance(callback.message, Message):
        await callback.answer(t("invalid_button", lang), show_alert=True)
        return
    await database.set_user_language(callback.from_user.id, callback.from_user.full_name, selected_lang)
    await state.clear()
    await callback.answer(t("language_saved", selected_lang))
    await callback.message.answer(t("language_saved", selected_lang), reply_markup=main_menu_keyboard(selected_lang))


async def delete_unexpected_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        # Missing delete permissions / old messages must never break routing.
        pass


async def unknown_message(message: Message, state: FSMContext, lang: str) -> None:
    await delete_unexpected_message(message)
    # Invalid receipt types keep the existing reminder and never consume the draft.
    from bot.handlers.orders import OrderStates
    if await state.get_state() == OrderStates.awaiting_receipt.state:
        await message.answer(t("receipt_wrong", lang), reply_markup=receipt_keyboard(lang))


async def unknown_callback(callback: CallbackQuery, lang: str) -> None:
    await callback.answer(t("invalid_button", lang), show_alert=True)


def create_router() -> Router:
    router = Router(name="start")
    router.message.register(my_id, Command("myid"))
    router.message.register(start, CommandStart())
    router.message.register(start, Command("menu"))
    router.message.register(choose_language, Command("language"))
    router.callback_query.register(set_language, F.data.startswith("lang:"))
    return router


def create_fallback_router() -> Router:
    router = Router(name="fallback")
    router.message.register(unknown_message)
    router.callback_query.register(unknown_callback)
    return router
