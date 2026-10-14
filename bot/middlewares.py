"""Access control before message and callback filters."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Config
from bot.db import Database
from bot.i18n import normalize_language


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, config: Config, database: Database) -> None:
        self.config = config
        self.database = database
        self.public_command = Command("myid")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, (Message, CallbackQuery)):
            return None
        user = event.from_user
        if user is None or user.is_bot:
            return None

        is_public = isinstance(event, Message) and bool(
            await self.public_command(event, data["bot"])
        )
        if user.id not in self.config.allowed_user_ids:
            if is_public:
                data["lang"] = self.config.default_lang
                return await handler(event, data)
            return None

        saved_lang = await self.database.get_user_language(user.id)
        data["lang"] = normalize_language(saved_lang, self.config.default_lang)
        data["language_selected"] = saved_lang is not None
        return await handler(event, data)
