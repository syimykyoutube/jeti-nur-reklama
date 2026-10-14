"""Word export and a whitelist-protected manual database backup."""

from datetime import datetime, timezone
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from bot.config import Config
from bot.db import Database
from bot.i18n import t
from bot.services.backup import database_snapshot
from bot.services.report_docx import create_report, report_filename
from bot.services.stats import Period


async def send_word_report(message: Message, database: Database, config: Config, period: Period, lang: str) -> None:
    await message.answer(t("report_building", lang))
    generated_at = datetime.now(timezone.utc)
    with TemporaryDirectory(prefix="jeti-nur-report-") as directory:
        filename = report_filename(period, config.timezone, generated_at)
        output = Path(directory) / filename
        try:
            await create_report(database, output, period, config.timezone, lang, generated_at)
            await message.answer_document(FSInputFile(output, filename=filename))
        except Exception:
            logging.exception("Word report generation or delivery failed")
            await message.answer(t("report_failed", lang))


async def backup(message: Message, database: Database, config: Config, lang: str) -> None:
    await message.answer(t("backup_building", lang))
    filename = f"backup_{datetime.now(timezone.utc).astimezone(config.timezone):%Y-%m-%d_%H-%M-%S}.db"
    try:
        async with database_snapshot(database) as snapshot:
            await message.answer_document(FSInputFile(snapshot.path, filename=filename), caption=t("backup_ready", lang))
    except Exception:
        logging.exception("Database backup or delivery failed")
        await message.answer(t("backup_failed", lang))


def create_router() -> Router:
    router = Router(name="export")
    router.message.register(backup, Command("backup"))
    return router
