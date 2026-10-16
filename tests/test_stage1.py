"""Stage 1 acceptance checks using real routing and a mocked Telegram session."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import aiosqlite
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, GetMe, SendDocument, SendMessage, SendPhoto, DeleteMessage, EditMessageText, SetMyCommands
from aiogram.types import CallbackQuery, Chat, FSInputFile, Message, PhotoSize, Update, User

from bot.config import Config, ConfigError, load_config
from bot.db import Database, init_db
from bot.i18n import TEXTS, format_datetime, format_money, t
from bot.main import create_dispatcher


TEST_TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
NOW = datetime(2026, 10, 13, 6, 0, tzinfo=timezone.utc)


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []
        self.uploaded_documents = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendDocument) and isinstance(method.document, FSInputFile):
            self.uploaded_documents.append((method.document.filename, Path(method.document.path).read_bytes()))
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="Test", username="test_bot")
        if isinstance(method, (SendMessage, SendPhoto, SendDocument, EditMessageText)):
            return Message(
                message_id=getattr(method, "message_id", None) or 900,
                date=NOW,
                chat=Chat(id=int(method.chat_id), type="private"),
                from_user=User(id=123456, is_bot=True, first_name="Test"),
                text=method.text if isinstance(method, (SendMessage, EditMessageText)) else None,
            )
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage, SetMyCommands)):
            return True
        raise AssertionError(f"Unexpected Telegram request: {type(method).__name__}")

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        raise AssertionError("File downloads are outside Stage 1")
        yield b""


class BotTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "nested" / "bot.db"
        await init_db(self.path)
        self.database = Database(self.path)
        self.config = Config(TEST_TOKEN, frozenset({101, 202}), self.path, ZoneInfo("Asia/Bishkek"))
        self.session = RecordingSession()
        self.bot = Bot(TEST_TOKEN, session=self.session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dispatcher = create_dispatcher(self.config, self.database)
        self.update_id = 0

    async def asyncTearDown(self) -> None:
        await self.dispatcher.fsm.close()
        await self.bot.session.close()
        self.temp.cleanup()

    async def send_message(self, text: str | None, user_id: int = 101, **content) -> None:
        self.update_id += 1
        message = Message(
            message_id=self.update_id,
            date=NOW,
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Aibek"),
            text=text,
            **content,
        )
        await self.dispatcher.feed_update(self.bot, Update(update_id=self.update_id, message=message))

    async def click(self, data: str, user_id: int = 101, message_id: int = 900) -> None:
        self.update_id += 1
        callback = CallbackQuery(
            id=f"callback-{self.update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="Aibek"),
            chat_instance="test",
            data=data,
            message=Message(
                message_id=message_id,
                date=NOW,
                chat=Chat(id=user_id, type="private"),
                from_user=User(id=123456, is_bot=True, first_name="Test"),
                text=t("choose_lang", "ky"),
            ),
        )
        await self.dispatcher.feed_update(self.bot, Update(update_id=self.update_id, callback_query=callback))

    def sent_messages(self) -> list[SendMessage]:
        return [call for call in self.session.calls if isinstance(call, SendMessage)]

    def displayed_messages(self):
        return [call for call in self.session.calls if isinstance(call, (SendMessage, EditMessageText))]


class StageOneTests(BotTestCase):
    async def test_schema_is_idempotent_and_empty(self) -> None:
        await init_db(self.path)
        async with aiosqlite.connect(self.path) as connection:
            for table in ("users", "products", "orders"):
                async with connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                    self.assertEqual((await cursor.fetchone())[0], 0)
            async with connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'") as cursor:
                names = {row[0] for row in await cursor.fetchall()}
            self.assertTrue({"idx_orders_created_at", "idx_orders_deleted_at"} <= names)

    async def test_first_start_and_persistent_language(self) -> None:
        await self.send_message("/start")
        picker = self.sent_messages()[-1]
        self.assertEqual(picker.text, t("choose_lang", "ky"))
        self.assertEqual([b.text for b in picker.reply_markup.inline_keyboard[0]], ["Русский", "Кыргызча"])
        self.assertIsNone(await self.database.get_user_language(101))

        await self.click("lang:ru")
        menu = self.sent_messages()[-1]
        self.assertEqual(menu.text, t("language_saved", "ru"))
        self.assertEqual(len([b for row in menu.reply_markup.keyboard for b in row]), 2)
        self.assertEqual(await self.database.get_user_language(101), "ru")
        self.assertIsNone(await self.database.get_user_language(202))

        async with aiosqlite.connect(self.path) as connection:
            async with connection.execute("SELECT created_at FROM users WHERE tg_id = 101") as cursor:
                original_created_at = (await cursor.fetchone())[0]
        self.assertEqual(datetime.fromisoformat(original_created_at).utcoffset().total_seconds(), 0)

        original_created_at = "2020-01-01T00:00:00+00:00"
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("UPDATE users SET created_at = ? WHERE tg_id = 101", (original_created_at,))
            await connection.commit()

        await init_db(self.path)
        self.database = Database(self.path)
        self.dispatcher = create_dispatcher(self.config, self.database)
        await self.send_message("/start")
        self.assertEqual(self.sent_messages()[-1].text, t("main_menu", "ru"))

        await self.send_message("/language")
        self.assertEqual(self.sent_messages()[-1].text, "Выберите язык")
        self.assertEqual(len(self.sent_messages()[-1].reply_markup.inline_keyboard), 1)
        await self.click("lang:ky")
        self.assertEqual(await self.database.get_user_language(101), "ky")
        self.assertEqual(self.sent_messages()[-1].text, t("language_saved", "ky"))
        async with aiosqlite.connect(self.path) as connection:
            async with connection.execute("SELECT COUNT(*), created_at FROM users WHERE tg_id = 101") as cursor:
                count, created_at = await cursor.fetchone()
        self.assertEqual(count, 1)
        self.assertEqual(created_at, original_created_at)

    async def test_whitelist_blocks_all_messages_and_callbacks(self) -> None:
        for text in ("/start", "/language", "/menu", "Меню", "hello", t("menu_catalog", "ky"), "/myid_extra", None):
            await self.send_message(text, 999)
        await self.send_message(None, 999, photo=[PhotoSize(file_id="photo", file_unique_id="unique", width=10, height=10)])
        await self.click("lang:ru", 999)
        await self.click("unknown", 999)
        await self.click("menu:main", 999)
        self.assertEqual(self.session.calls, [])
        self.assertIsNone(await self.database.get_user_language(999))

    async def test_removing_user_from_whitelist_blocks_old_buttons(self) -> None:
        await self.click("lang:ru")
        self.session.calls.clear()
        self.dispatcher = create_dispatcher(replace(self.config, allowed_user_ids=frozenset({202})), self.database)
        await self.click("lang:ky")
        await self.send_message("/language")
        self.assertEqual(self.session.calls, [])
        self.assertEqual(await self.database.get_user_language(101), "ru")

    async def test_users_have_independent_language_preferences(self) -> None:
        await self.click("lang:ru", 101)
        await self.click("lang:ky", 202)
        await self.send_message("/start", 101)
        self.assertEqual(self.sent_messages()[-1].text, t("main_menu", "ru"))
        await self.send_message("/start", 202)
        self.assertEqual(self.sent_messages()[-1].text, t("main_menu", "ky"))

    async def test_public_myid_and_bot_mentions(self) -> None:
        for text in ("/myid", "/myid@test_bot"):
            await self.send_message(text, 999)
            self.assertEqual(self.sent_messages()[-1].text, t("my_id", "ky", user_id=999))
        count = len(self.sent_messages())
        await self.send_message("/myid@other_bot", 999)
        self.assertEqual(len(self.sent_messages()), count)
        self.assertIsNone(await self.database.get_user_language(999))

    async def test_empty_whitelist_allows_only_myid(self) -> None:
        self.dispatcher = create_dispatcher(replace(self.config, allowed_user_ids=frozenset()), self.database)
        await self.send_message("/start")
        await self.click("lang:ru")
        self.assertEqual(self.session.calls, [])
        await self.send_message("/myid")
        self.assertIn("101", self.sent_messages()[-1].text)
        self.assertIsNone(await self.database.get_user_language(101))

    async def test_legacy_denial_setting_still_ignores_outsiders_silently(self) -> None:
        self.dispatcher = create_dispatcher(replace(self.config, access_denied_reply=True, default_lang="ru"), self.database)
        await self.send_message("/start", 999)
        await self.click("lang:ky", 999)
        self.assertEqual(self.session.calls, [])
        self.assertIsNone(await self.database.get_user_language(999))
        await self.send_message("/myid", 999)
        self.assertEqual(self.sent_messages()[-1].text, t("my_id", "ru", user_id=999))

    async def test_analytics_menu_and_old_language_labels(self) -> None:
        await self.click("lang:ky")
        for lang in ("ru", "ky"):
            for key in ("menu_analytics",):
                await self.send_message(t(key, lang))
                self.assertEqual(self.sent_messages()[-1].text, t("choose_period", "ky"))
                self.assertEqual(sum(len(row) for row in self.sent_messages()[-1].reply_markup.inline_keyboard), 5)
        for text in ("/start", "/menu"):
            await self.send_message(text)
            self.assertEqual(self.sent_messages()[-1].text, t("main_menu", "ky"))
        async with aiosqlite.connect(self.path) as connection:
            for table in ("products", "orders"):
                async with connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                    self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_invalid_language_callback_cannot_write(self) -> None:
        await self.click("lang:en")
        self.assertIsNone(await self.database.get_user_language(101))
        self.assertIsInstance(self.session.calls[-1], AnswerCallbackQuery)
        with self.assertRaises(ValueError):
            await self.database.set_user_language(101, "Aibek", "en")


class ConfigurationAndLocalizationTests(unittest.TestCase):
    def config(self, **values: str) -> Config:
        with TemporaryDirectory() as temp, patch.dict("os.environ", {"BOT_TOKEN": TEST_TOKEN, **values}, clear=True):
            return load_config(Path(temp) / "missing.env")

    def test_defaults_and_parsing(self) -> None:
        config = self.config()
        self.assertEqual(config.default_lang, "ky")
        self.assertEqual(config.timezone.key, "Asia/Bishkek")
        self.assertEqual(config.allowed_user_ids, frozenset())
        self.assertTrue(config.db_path.is_absolute())
        self.assertNotIn(TEST_TOKEN, repr(config))
        config = self.config(ALLOWED_USER_IDS="101, 202,101", DEFAULT_LANG="ru", ACCESS_DENIED_REPLY="true")
        self.assertEqual(config.allowed_user_ids, frozenset({101, 202}))
        self.assertTrue(config.access_denied_reply)

    def test_invalid_configuration_is_rejected(self) -> None:
        for values in (
            {"BOT_TOKEN": ""}, {"BOT_TOKEN": "invalid"},
            {"ALLOWED_USER_IDS": "0"}, {"ALLOWED_USER_IDS": "-1"},
            {"ALLOWED_USER_IDS": "101,abc"}, {"ALLOWED_USER_IDS": "101,"},
            {"DEFAULT_LANG": "en"}, {"TZ": "Invalid/Zone"},
            {"BOT_TZ": "Invalid/Zone", "TZ": "Asia/Bishkek"},
            {"ACCESS_DENIED_REPLY": "maybe"}, {"DB_PATH": ""}, {"DB_PATH": ":memory:"},
        ):
            with self.subTest(values=values), self.assertRaises(ConfigError):
                self.config(**values)

    def test_env_file_and_environment_precedence(self) -> None:
        with TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text(f"BOT_TOKEN={TEST_TOKEN}\nALLOWED_USER_IDS=101\nDEFAULT_LANG=ru\n", encoding="utf-8")
            with patch.dict("os.environ", {"DEFAULT_LANG": "ky"}, clear=True):
                config = load_config(env_file)
            self.assertEqual(config.default_lang, "ky")
            self.assertEqual(config.allowed_user_ids, frozenset({101}))

    def test_bot_timezone_priority_fallback_and_defaults(self) -> None:
        for values, expected in (
            ({"BOT_TZ": "Asia/Bishkek", "TZ": "Europe/Amsterdam"}, "Asia/Bishkek"),
            ({"BOT_TZ": " UTC ", "TZ": "Invalid/Zone"}, "UTC"),
            ({"BOT_TZ": "Europe/Amsterdam"}, "Europe/Amsterdam"),
            ({"TZ": "Europe/Amsterdam"}, "Europe/Amsterdam"),
            ({"BOT_TZ": " ", "TZ": "UTC"}, "UTC"),
            ({"BOT_TZ": "", "TZ": ""}, "Asia/Bishkek"),
            ({}, "Asia/Bishkek"),
        ):
            with self.subTest(values=values):
                self.assertEqual(self.config(**values).timezone.key, expected)

    def test_bot_timezone_from_env_file_overrides_container_tz(self) -> None:
        with TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text(f"BOT_TOKEN={TEST_TOKEN}\nBOT_TZ=Asia/Bishkek\n", encoding="utf-8")
            with patch.dict("os.environ", {"TZ": "Europe/Amsterdam"}, clear=True):
                self.assertEqual(load_config(env_file).timezone.key, "Asia/Bishkek")
            with patch.dict("os.environ", {"TZ": "Europe/Amsterdam", "BOT_TZ": "UTC"}, clear=True):
                self.assertEqual(load_config(env_file).timezone.key, "UTC")

    def test_both_languages_and_display_formats(self) -> None:
        for key, translations in TEXTS.items():
            self.assertEqual(set(translations), {"ru", "ky"}, key)
            self.assertTrue(all(translations.values()), key)
        tz = ZoneInfo("Asia/Bishkek")
        self.assertEqual(format_datetime(NOW, "ru", tz), "12:00 · 13.10.2026")
        self.assertEqual(format_datetime(NOW, "ky", tz), "12:00 · 13.10.2026")
        midnight = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
        self.assertEqual(format_datetime(midnight, "ru", tz), "01:00 · 13.10.2026")
        self.assertEqual(format_money(4200, "ru"), "4 200 сом")
        self.assertEqual(format_money(200.5, "ky"), "200.5 сом")
        with self.assertRaises(ValueError):
            format_datetime(datetime(2026, 10, 13), "ru", tz)


if __name__ == "__main__":
    unittest.main()
