"""Stop a duplicate polling process instead of retrying Telegram conflicts."""

import logging

from aiogram import Dispatcher
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramConflictError
from aiogram.methods import GetUpdates


logger = logging.getLogger(__name__)


def log_polling_conflict() -> None:
    logger.error(
        "Конфликт Telegram getUpdates: бот уже запущен в другом месте. "
        "Остановите вторую копию на компьютере или сервере, затем запустите бот вручную. "
        "Этот процесс завершается с кодом 0 без повторных запросов getUpdates."
    )


class StopOnPollingConflict(BaseRequestMiddleware):
    def __init__(self, dispatcher: Dispatcher) -> None:
        self.dispatcher = dispatcher
        self.conflict_detected = False

    async def __call__(self, make_request, bot, method):
        try:
            return await make_request(bot, method)
        except TelegramConflictError:
            if not isinstance(method, GetUpdates):
                raise
            self.conflict_detected = True
            log_polling_conflict()
            # stop_polling signals the coordinator, which cancels this request.
            # Do not forward the conflict into aiogram's exception/backoff loop.
            await self.dispatcher.stop_polling()
            return []
