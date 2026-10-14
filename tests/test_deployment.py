"""Hosting entry point, root-relative paths, stdout, and finite conflict shutdown."""

import asyncio
from pathlib import Path
import os
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramConflictError, TelegramNetworkError
from aiogram.methods import GetUpdates
from aiogram.utils.backoff import BackoffConfig

from bot.config import load_config
from bot.db import init_db
from bot.main import main, run
from bot.services.polling import StopOnPollingConflict
from test_stage1 import BotTestCase, RecordingSession, TEST_TOKEN

ROOT = Path(__file__).resolve().parent.parent


class DeploymentUnitTests(unittest.TestCase):
    def test_app_invokes_original_module_only_when_executed(self):
        with patch("runpy.run_module") as launch:
            runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
            launch.assert_called_once_with("bot.main", run_name="__main__")
        with patch("runpy.run_module") as launch:
            runpy.run_path(str(ROOT / "app.py"), run_name="hosting_module")
            launch.assert_not_called()

    def test_run_configures_stdout_and_keeps_original_startup(self):
        with patch("bot.main.logging.basicConfig") as configure, patch("bot.main.main", new_callable=AsyncMock) as startup:
            run()
        startup.assert_awaited_once()
        self.assertIs(configure.call_args.kwargs["stream"], sys.stdout)
        self.assertTrue(configure.call_args.kwargs["force"])

    def test_startup_conflict_logs_actionable_message_and_exits_normally(self):
        conflict = TelegramConflictError(method=GetUpdates(), message="Conflict: terminated by other getUpdates request")
        with patch("bot.main.logging.basicConfig"), patch("bot.main.main", new_callable=AsyncMock, side_effect=conflict) as startup:
            with self.assertLogs("bot.services.polling", level="ERROR") as logs:
                self.assertIsNone(run())
        startup.assert_awaited_once()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("бот уже запущен в другом месте", logs.output[0])
        self.assertIn("запустите бот вручную", logs.output[0])
        self.assertNotIn(TEST_TOKEN, logs.output[0])

    def test_runtime_requirements_only_and_no_source_builds(self):
        from packaging.requirements import Requirement
        lines = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
        self.assertIn("--only-binary=:all:", lines)
        packages = {Requirement(line).name for line in lines if not line.startswith("--")}
        self.assertEqual(packages, {"aiogram", "aiosqlite", "matplotlib", "python-docx", "python-dotenv", "tzdata"})
        self.assertNotIn("pytest", packages)
        self.assertIn("-r requirements.txt", (ROOT / "requirements-dev.txt").read_text())


class DeploymentPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_root_env_and_db_ignore_working_directory_and_create_data(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "container"
            root.mkdir()
            outside = Path(temp) / "another-folder"
            outside.mkdir()
            (root / ".env").write_text(
                f"BOT_TOKEN={TEST_TOKEN}\nALLOWED_USER_IDS=101,202\nDB_PATH=data/bot.db\nBOT_TZ=Asia/Bishkek\nDEFAULT_LANG=ky\nACCESS_DENIED_REPLY=false\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(outside)
                with patch("bot.config.PROJECT_ROOT", root), patch.dict("os.environ", {"TZ": "Europe/Amsterdam"}, clear=True):
                    config = load_config()
                self.assertEqual(config.allowed_user_ids, frozenset({101, 202}))
                self.assertEqual(config.timezone.key, "Asia/Bishkek")
                self.assertEqual(config.db_path, root / "data" / "bot.db")
                self.assertFalse(config.db_path.parent.exists())
                await init_db(config.db_path)
                self.assertTrue(config.db_path.is_file())
                self.assertFalse((outside / "data").exists())
            finally:
                os.chdir(previous)


class PollingSession(RecordingSession):
    def __init__(self, conflict=True):
        super().__init__()
        self.conflict = conflict
        self.requests = 0
        self.connected = asyncio.Event()
        self.closed = False

    async def close(self):
        self.closed = True

    async def make_request(self, bot, method, timeout=None):
        if not isinstance(method, GetUpdates):
            return await super().make_request(bot, method, timeout)
        self.calls.append(method)
        self.requests += 1
        if self.conflict:
            raise TelegramConflictError(method=method, message="Conflict: terminated by other getUpdates request")
        if self.requests == 1:
            raise TelegramNetworkError(method=method, message="Temporary network failure")
        self.connected.set()
        await asyncio.Event().wait()


class PollingShutdownTests(BotTestCase):
    async def test_conflict_stops_real_dispatcher_after_one_request_and_closes_session(self):
        session = PollingSession()
        self.bot.session = session
        middleware = StopOnPollingConflict(self.dispatcher)
        session.middleware.register(middleware)
        with self.assertLogs("bot.services.polling", level="ERROR") as logs:
            await asyncio.wait_for(self.dispatcher.start_polling(self.bot, handle_signals=False), timeout=2)
        self.assertEqual(session.requests, 1)
        self.assertTrue(session.closed)
        self.assertTrue(middleware.conflict_detected)
        self.assertEqual(len(logs.output), 1)
        self.assertFalse(self.dispatcher._running_lock.locked())

    async def test_temporary_network_errors_still_retry(self):
        session = PollingSession(conflict=False)
        self.bot.session = session
        middleware = StopOnPollingConflict(self.dispatcher)
        session.middleware.register(middleware)
        with self.assertLogs("aiogram.dispatcher", level="WARNING"):
            polling = asyncio.create_task(self.dispatcher.start_polling(
                self.bot, handle_signals=False,
                backoff_config=BackoffConfig(min_delay=0.001, max_delay=0.01, factor=2, jitter=0),
            ))
            try:
                await asyncio.wait_for(session.connected.wait(), timeout=2)
                await asyncio.wait_for(self.dispatcher.stop_polling(), timeout=2)
                await polling
            finally:
                if not polling.done():
                    polling.cancel()
                    await asyncio.gather(polling, return_exceptions=True)
        self.assertEqual(session.requests, 2)
        self.assertFalse(middleware.conflict_detected)
        self.assertTrue(session.closed)

    async def test_main_attaches_conflict_middleware_and_preserves_polling_options(self):
        with patch("bot.main.load_config", return_value=self.config), patch("bot.main.Bot", return_value=self.bot), \
             patch.object(self.bot, "delete_webhook", new_callable=AsyncMock) as delete_webhook, \
             patch("bot.main.create_dispatcher", return_value=self.dispatcher), \
             patch.object(self.dispatcher, "start_polling", new_callable=AsyncMock) as polling:
            with self.assertLogs("bot.main", level="INFO") as logs:
                await main()
        delete_webhook.assert_awaited_once_with(drop_pending_updates=False)
        polling.assert_awaited_once_with(self.bot, allowed_updates=["message", "callback_query"])
        self.assertTrue(any(isinstance(item, StopOnPollingConflict) for item in self.bot.session.middleware))
        self.assertTrue(any(f"timezone: {self.config.timezone.key}" in line for line in logs.output))
