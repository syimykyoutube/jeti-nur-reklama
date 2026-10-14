"""Application entry point: python -m bot.main."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.filters import Command
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand, ErrorEvent

from bot.config import Config, ConfigError, load_config
from bot.db import Database, init_db
from bot.handlers.analytics import create_router as create_analytics_router
from bot.handlers.catalog import create_router as create_catalog_router, open_catalog_editor
from bot.handlers.orders import create_router as create_orders_router
from bot.handlers.export import create_router as create_export_router
from bot.handlers.start import create_fallback_router, create_router
from bot.i18n import SUPPORTED_LANGUAGES, t
from bot.middlewares import WhitelistMiddleware
from bot.services.polling import StopOnPollingConflict, log_polling_conflict


logger = logging.getLogger(__name__)


async def log_error(event: ErrorEvent) -> bool:
    logging.exception(
        "Unhandled Telegram update error (update_id=%s)",
        event.update.update_id,
        exc_info=event.exception,
    )
    return True


def create_dispatcher(config: Config, database: Database) -> Dispatcher:
    dispatcher = Dispatcher(config=config, database=database, events_isolation=SimpleEventIsolation())
    middleware = WhitelistMiddleware(config, database)
    dispatcher.message.outer_middleware(middleware)
    dispatcher.callback_query.outer_middleware(middleware)
    # Global navigation must run before FSM text handlers and the final deletion fallback.
    dispatcher.message.register(open_catalog_editor, Command("edit"))
    dispatcher.include_routers(
        create_router(), create_export_router(), create_orders_router(), create_analytics_router(), create_catalog_router(), create_fallback_router(),
    )
    dispatcher.errors.register(log_error)
    return dispatcher


async def register_commands(bot: Bot, lang: str, language_code: str | None = None) -> None:
    commands = [
        BotCommand(command=command, description=t(key, lang))
        for command, key in (
            ("start", "command_start"),
            ("menu", "command_menu"),
            ("language", "command_language"),
            ("edit", "command_edit"),
            ("deleteorder", "command_deleteorder"),
            ("myid", "command_myid"),
            ("cancel", "command_cancel"),
        )
    ]
    await bot.set_my_commands(commands, language_code=language_code)


async def main() -> None:
    config = load_config()
    await init_db(config.db_path)
    database = Database(config.db_path)
    dispatcher = create_dispatcher(config, database)

    if not config.allowed_user_ids:
        logger.info("Whitelist is empty. Only /myid is available until IDs are added and the bot is restarted.")
    logger.info("Database initialized: %s; timezone: %s", config.db_path, config.timezone.key)

    async with Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
        bot.session.middleware.register(StopOnPollingConflict(dispatcher))
        await bot.delete_webhook(drop_pending_updates=False)
        await register_commands(bot, "ky")
        for lang in SUPPORTED_LANGUAGES:
            await register_commands(bot, lang, lang)
        await dispatcher.start_polling(bot, allowed_updates=["message", "callback_query"])


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stdout, force=True)
    try:
        asyncio.run(main())
    except ConfigError as error:
        logger.error("Configuration error: %s", error)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
    except TelegramConflictError:
        # A conflict during startup also terminates normally (exit code 0).
        log_polling_conflict()
    except Exception:
        logging.exception("Bot startup or polling failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
