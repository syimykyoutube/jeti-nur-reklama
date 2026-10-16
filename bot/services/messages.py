"""Safe in-place Telegram updates and restoration of catalog order drafts."""

from html import escape

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from bot.i18n import format_money, t
from bot.keyboards import product_keyboard


async def edit_or_send(bot: Bot, chat_id: int, message_id: int, text: str,
                       reply_markup: InlineKeyboardMarkup | None = None) -> int:
    """Return the actual message ID, including a replacement when editing is impossible."""
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup)
        return message_id
    except TelegramBadRequest as error:
        if "message is not modified" in error.message.lower():
            return message_id
        sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return sent.message_id


async def edit_message(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> int:
    return await edit_or_send(message.bot, message.chat.id, message.message_id, text, reply_markup)


async def restore_order_card(bot: Bot, draft: dict, lang: str) -> None:
    if draft.get("card_chat_id") is None or draft.get("card_message_id") is None:
        return
    lang = draft.get("card_lang", lang)
    await edit_or_send(bot, draft["card_chat_id"], draft["card_message_id"],
                       t("product_card", lang, name=escape(draft["product_name"]),
                         price=format_money(draft["price"], lang)),
                       product_keyboard(draft["product_id"], lang))


class RestoreOrderCardMiddleware(BaseMiddleware):
    """Restore an order prompt whenever navigation clears or replaces its draft."""

    async def __call__(self, handler, event, data):
        state = data["state"]
        before = await state.get_data()
        try:
            return await handler(event, data)
        finally:
            after = await state.get_data()
            previous = (before.get("card_chat_id"), before.get("card_message_id"))
            current = (after.get("card_chat_id"), after.get("card_message_id"))
            if previous != (None, None) and previous != current:
                await restore_order_card(data["bot"], before, data["lang"])
