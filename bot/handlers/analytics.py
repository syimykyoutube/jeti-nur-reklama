"""Period-first analytics with restart-safe callbacks and localized order cards."""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.callbacks import (
    AnalyticsKindCallback, AnalyticsPageCallback, AnalyticsPeriodCallback,
    PeriodChoiceCallback, ReceiptCallback,
)
from bot.config import Config
from bot.db import Database
from bot.handlers.catalog import usable_callback
from bot.handlers.start import show_language_picker
from bot.handlers.orders import order_card, deliver_receipt
from bot.handlers.export import send_word_report
from bot.i18n import format_money, t, variants
from bot.keyboards import (
    analytics_keyboard, analytics_navigation, analytics_orders_navigation,
    analytics_period_keyboard, main_menu_keyboard, receipt_button,
)
from bot.services.charts import chart_png
from bot.services.messages import edit_message, edit_or_send
from bot.services.stats import (
    Period, chart_weekly, fill_chart_buckets, make_period, period_from_anchor,
    period_key, period_label, validate_days,
)

class AnalyticsStates(StatesGroup):
    custom_days = State()


async def show_analytics_menu(message: Message, state: FSMContext, lang: str, language_selected: bool) -> None:
    await state.clear()
    if not language_selected:
        await show_language_picker(message, lang)
        return
    await message.answer(t("choose_period", lang), reply_markup=analytics_period_keyboard("summary", lang))


async def analytics_menu_callback(callback: CallbackQuery, state: FSMContext, lang: str, language_selected: bool) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    await callback.answer()
    await state.clear()
    await edit_message(callback.message, t("choose_period", lang), analytics_period_keyboard("summary", lang))


async def choose_period(callback: CallbackQuery, callback_data: AnalyticsKindCallback,
                        state: FSMContext, lang: str, language_selected: bool) -> None:
    # Old section buttons can still open the new period picker.
    await analytics_menu_callback(callback, state, lang, language_selected)


async def show_summary(message: Message, database: Database, period: Period, lang: str,
                       *, editing: bool = False, target: tuple[int, int] | None = None) -> None:
    summary = await database.get_order_summary(period)
    text = t("summary_result", lang, period=period_label(period.key, lang),
             count=summary.count, total=format_money(summary.total, lang))
    if not summary.count:
        text += "\n" + t("no_orders", lang)
    keyboard = analytics_keyboard(lang, period)
    if target:
        await edit_or_send(message.bot, *target, text, keyboard)
    elif editing:
        await edit_message(message, text, keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


async def select_period(callback: CallbackQuery, callback_data: PeriodChoiceCallback,
                        database: Database, config: Config, state: FSMContext,
                        lang: str, language_selected: bool) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    await state.clear()
    await callback.answer()
    if callback_data.period == "custom":
        await state.set_state(AnalyticsStates.custom_days)
        message_id = await edit_message(callback.message, t("ask_days", lang))
        await state.set_data({"period_chat_id": callback.message.chat.id, "period_message_id": message_id})
        return
    await show_summary(callback.message, database, make_period(period_key(callback_data.period), config.timezone), lang, editing=True)


async def custom_days(message: Message, database: Database, config: Config,
                      state: FSMContext, lang: str) -> None:
    try:
        key = validate_days(message.text)
    except ValueError:
        await message.answer(t("ask_days", lang))
        return
    data = await state.get_data()
    target = ((data["period_chat_id"], data["period_message_id"]) if "period_message_id" in data else None)
    await state.clear()
    await show_summary(message, database, make_period(key, config.timezone), lang, target=target)


async def cancel_custom_days(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer(t("cancelled", lang), reply_markup=main_menu_keyboard(lang))


async def show_orders(message: Message, database: Database, config: Config,
                      period: Period, lang: str, page: int = 0) -> None:
    result = await database.get_orders_page(page, start=period.start, end=period.end)
    if not result.orders:
        await message.answer(t("no_orders", lang), reply_markup=analytics_navigation("orders", lang))
        return
    for number, order in enumerate(result.orders, result.page * 10 + 1):
        await message.answer(order_card(order, number, config, lang), reply_markup=receipt_button(order.id, lang))
    if result.total > 10:
        await message.answer(t("pagination", lang),
                             reply_markup=analytics_orders_navigation(period, result.page, result.pages, lang))


async def show_result(callback: CallbackQuery, callback_data: AnalyticsPeriodCallback, database: Database,
                      config: Config, state: FSMContext, lang: str, language_selected: bool) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    try:
        key = period_key(callback_data.period)
        if callback_data.anchor:
            if callback_data.anchor > make_period("all", config.timezone).anchor:
                raise ValueError("Future analytics anchor")
            period = period_from_anchor(key, callback_data.anchor, config.timezone)
        else:
            period = make_period(key, config.timezone)
    except (ValueError, OverflowError, OSError):
        await callback.answer(t("invalid_button", lang), show_alert=True)
        return
    await state.clear()
    await callback.answer()
    message = callback.message
    mode = callback_data.mode
    if mode == "summary":
        await show_summary(message, database, period, lang, editing=True)
        return
    if mode == "word":
        await send_word_report(message, database, config, period, lang)
        return
    if mode == "orders":
        await show_orders(message, database, config, period, lang, callback_data.page)
        return
    navigation = analytics_navigation(mode, lang)
    if mode == "top":
        top = await database.get_top_products(period)
        if not top:
            await message.answer(t("no_orders", lang), reply_markup=navigation)
            return
        lines = [t("top_line", lang, rank=index, name=escape(item.name), count=item.count,
                   total=format_money(item.total, lang)) for index, item in enumerate(top, 1)]
        chunk = []
        length = 0
        for line in lines:
            # Split between whole escaped lines, never inside HTML entities.
            line_length = len(line.encode("utf-16-le")) // 2
            if chunk and length + 1 + line_length > 4000:
                await message.answer("\n".join(chunk))
                chunk, length = [], 0
            length += line_length + bool(chunk)
            chunk.append(line)
        await message.answer("\n".join(chunk), reply_markup=navigation)
        return
    summary = await database.get_order_summary(period)
    if not summary.count:
        await message.answer(t("no_orders", lang), reply_markup=navigation)
        return
    weekly = chart_weekly(period, summary.first_created_at, config.timezone)
    rows = await database.get_chart_buckets(period, config.timezone, weekly)
    series = fill_chart_buckets(rows, period, config.timezone, weekly)
    with chart_png(series, period.key, lang) as png:
        await message.answer_photo(BufferedInputFile(png, filename="chart.png"),
            caption=t("chart_caption", lang, period=period_label(period.key, lang),
                      grouping=t("chart_weeks" if weekly else "chart_days", lang)), reply_markup=navigation)


async def orders_page_callback(callback: CallbackQuery, callback_data: AnalyticsPageCallback,
                               database: Database, config: Config, state: FSMContext,
                               lang: str, language_selected: bool) -> None:
    # Compatibility with list buttons sent by v1.0; new buttons use the compact an prefix.
    try:
        payload = AnalyticsPeriodCallback(mode="orders", period=callback_data.period,
                                          anchor=callback_data.anchor, page=callback_data.page)
    except ValueError:
        await callback.answer(t("invalid_button", lang), show_alert=True)
        return
    await show_result(callback, payload, database, config, state, lang, language_selected)


async def send_receipt(callback: CallbackQuery, callback_data: ReceiptCallback, database: Database,
                       config: Config, lang: str, language_selected: bool) -> None:
    if not await usable_callback(callback, lang, language_selected):
        return
    order = await database.get_active_order(callback_data.order_id)
    if order is None:
        await callback.answer(t("order_unavailable", lang), show_alert=True)
        return
    if order.receipt_type not in {"photo", "document"}:
        await callback.answer(t("receipt_unavailable", lang), show_alert=True)
        return
    await callback.answer()
    await deliver_receipt(callback.message, order, config, lang)


def create_router() -> Router:
    router = Router(name="analytics")
    router.message.register(show_analytics_menu, F.text.in_(variants("menu_analytics")))
    router.message.register(cancel_custom_days, AnalyticsStates.custom_days, Command("cancel"))
    router.message.register(custom_days, AnalyticsStates.custom_days, F.text)
    router.callback_query.register(analytics_menu_callback, F.data == "analytics:menu")
    router.callback_query.register(select_period, PeriodChoiceCallback.filter())
    router.callback_query.register(choose_period, AnalyticsKindCallback.filter())
    router.callback_query.register(show_result, AnalyticsPeriodCallback.filter())
    router.callback_query.register(orders_page_callback, AnalyticsPageCallback.filter())
    router.callback_query.register(send_receipt, ReceiptCallback.filter())
    return router
