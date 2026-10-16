"""Stage 2 acceptance checks through the dispatcher and temporary SQLite."""

import asyncio
from datetime import datetime
import unittest

import aiosqlite
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from aiogram.types import PhotoSize

from bot.callbacks import CatalogFormCallback, ProductCallback
from bot.db import Database, init_db
from bot.handlers.catalog import CatalogStates
from bot.i18n import format_money, t
from bot.services.catalog import validate_name, validate_price
from test_stage1 import BotTestCase


class CatalogTests(BotTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.database.set_user_language(101, "Aibek", "ru")
        await self.database.set_user_language(202, "Test", "ky")

    def context(self, user_id=101):
        return self.dispatcher.fsm.get_context(bot=self.bot, chat_id=user_id, user_id=user_id)

    async def action(self, action: str, product_id: int, user_id=101) -> None:
        await self.click(ProductCallback(action=action, product_id=product_id).pack(), user_id)

    async def form_action(self, action: str, user_id=101, token=None) -> None:
        if token is None:
            token = (await self.context(user_id).get_data())["token"]
        await self.click(CatalogFormCallback(action=action, token=token).pack(), user_id)

    async def test_empty_catalog_and_individual_cards_in_id_order(self) -> None:
        await self.send_message(t("menu_catalog", "ru"))
        self.assertEqual([message.text for message in self.sent_messages()],
                         [t("catalog_empty", "ru"), t("catalog_edit_hint", "ru")])
        self.assertTrue(all(message.reply_markup is None for message in self.sent_messages()))
        first = await self.database.add_product("Машина", 200)
        second = await self.database.add_product("Үй", 300.5)
        self.session.calls.clear()
        await self.send_message(t("menu_catalog", "ky"), 202)
        messages = self.sent_messages()
        self.assertEqual([m.text for m in messages], ["<b>Машина — 200 сом</b>", "<b>Үй — 300.5 сом</b>"])
        self.assertEqual([b.text for b in messages[0].reply_markup.inline_keyboard[0]], ["✅ Тандоо"])
        for card, product_id in zip(messages, (first, second)):
            self.assertEqual([len(row) for row in card.reply_markup.inline_keyboard], [1])
            callback = ProductCallback.unpack(card.reply_markup.inline_keyboard[0][0].callback_data)
            self.assertEqual((callback.product_id, callback.action), (product_id, "select"))

    async def test_edit_add_block_is_identical_for_empty_and_populated_catalog_in_both_languages(self) -> None:
        for user_id, lang, text, label in (
            (101, "ru", "Чтобы добавить карточку, нажмите кнопку ниже", "➕ Добавить карточку"),
            (202, "ky", "Жаңы карточка кошуу үчүн ылдыйдагы баскычты бас", "➕ Карточка кошуу"),
        ):
            for populated in (False, True):
                with self.subTest(lang=lang, populated=populated):
                    if populated:
                        product_id = await self.database.add_product("Машина", 200)
                    self.session.calls.clear()
                    await self.send_message("/edit", user_id)
                    messages = self.sent_messages()
                    self.assertEqual(messages[-1].text, text)
                    self.assertNotIn("➕", messages[-1].text)
                    rows = messages[-1].reply_markup.inline_keyboard
                    self.assertEqual([len(row) for row in rows], [1])
                    self.assertEqual(rows[0][0].text, label)
                    self.assertEqual(rows[0][0].callback_data, "catalog:add")
                    if not populated:
                        self.assertEqual(messages[-2].text, t("catalog_empty", lang))
                    await self.click(rows[0][0].callback_data, user_id)
                    self.assertEqual(await self.context(user_id).get_state(), CatalogStates.add_name.state)
                    self.assertEqual(self.sent_messages()[-1].text, t("ask_name", lang))
                    await self.click("catalog:cancel", user_id)
                    if populated:
                        await self.database.soft_delete_product(product_id)

    async def test_delete_no_edits_confirmation_clears_buttons_and_invalidates_old_token(self) -> None:
        for user_id, lang, labels, cancelled_text in (
            (101, "ru", ["Да", "Нет"], "Удаление отменено"),
            (202, "ky", ["Ооба", "Жок"], "Жокко чыгарылды"),
        ):
            with self.subTest(lang=lang):
                product_id = await self.database.add_product("Машина <&>", 200)
                before = await self.database.get_active_product(product_id)
                await self.action("delete", product_id, user_id)
                confirmation = self.displayed_messages()[-1]
                self.assertIn(t("confirm_delete", lang), confirmation.text)
                self.assertIn("Машина &lt;&amp;&gt;", confirmation.text)
                rows = confirmation.reply_markup.inline_keyboard
                self.assertEqual([len(row) for row in rows], [2])
                self.assertEqual([button.text for button in rows[0]], labels)
                token = (await self.context(user_id).get_data())["token"]
                self.session.calls.clear()
                await self.form_action("no", user_id, token)
                self.assertIsInstance(self.session.calls[0], AnswerCallbackQuery)
                edit = next(call for call in self.session.calls if isinstance(call, EditMessageText))
                self.assertIsInstance(edit, EditMessageText)
                self.assertEqual(edit.text, cancelled_text)
                self.assertEqual(edit.message_id, 900)
                self.assertIsNone(edit.reply_markup)
                self.assertEqual(self.sent_messages()[0].text, t("catalog_edit_mode", lang))
                self.assertEqual(self.sent_messages()[-1].text, t("catalog_actions", lang))
                self.assertIsNone(await self.context(user_id).get_state())
                self.assertEqual(await self.context(user_id).get_data(), {})
                self.assertEqual(await self.database.get_active_product(product_id), before)
                for action in ("no", "yes"):
                    await self.form_action(action, user_id, token)
                    self.assertIsInstance(self.session.calls[-1], AnswerCallbackQuery)
                    self.assertEqual(self.session.calls[-1].text, t("form_expired", lang))
                    self.assertEqual(await self.database.get_active_product(product_id), before)
                await self.action("delete", product_id, user_id)
                new_data = await self.context(user_id).get_data()
                await self.form_action("no", user_id, token)
                self.assertEqual(await self.context(user_id).get_data(), new_data)
                self.assertEqual(await self.context(user_id).get_state(), CatalogStates.delete_confirm.state)
                await self.form_action("yes", user_id)
                self.assertIsNone(await self.database.get_active_product(product_id))
                async with aiosqlite.connect(self.path) as connection:
                    async with connection.execute("SELECT is_active FROM products WHERE id = ?", (product_id,)) as cursor:
                        self.assertEqual(await cursor.fetchone(), (0,))

    async def test_add_validates_inputs_and_saves_only_after_price(self) -> None:
        await self.click("catalog:add")
        for value in (" ", "x" * 61):
            await self.send_message(value)
            self.assertEqual(await self.context().get_state(), CatalogStates.add_name.state)
            self.assertEqual(self.sent_messages()[-1].text, t("invalid_name", "ru"))
        await self.send_message("  Машина  ")
        self.assertEqual(await self.context().get_state(), CatalogStates.add_price.state)
        self.assertEqual(await self.database.list_active_products(), [])
        for value in ("0", "-1", "1000000", "NaN", "inf", "1e3", "1,2.3", "abc"):
            await self.send_message(value)
            self.assertEqual(await self.context().get_state(), CatalogStates.add_price.state)
            self.assertEqual(self.sent_messages()[-1].text, t("invalid_price", "ru"))
            self.assertEqual(await self.database.list_active_products(), [])
        await self.send_message("200,50")
        products = await self.database.list_active_products()
        self.assertEqual([(p.name, p.price) for p in products], [("Машина", 200.5)])
        self.assertIsNone(await self.context().get_state())
        self.assertEqual(await self.context().get_data(), {})
        self.assertEqual(datetime.fromisoformat(products[0].created_at).utcoffset().total_seconds(), 0)
        self.assertIn("Добавлено ✅", [m.text for m in self.sent_messages()])

    async def test_cancel_in_each_add_step_writes_nothing(self) -> None:
        await self.click("catalog:add")
        await self.send_message(t("btn_cancel", "ky"))
        self.assertIsNone(await self.context().get_state())
        await self.click("catalog:add")
        await self.send_message("Машина")
        await self.send_message("/cancel")
        await self.send_message("200")
        self.assertEqual(await self.database.list_active_products(), [])
        self.assertEqual(await self.context().get_data(), {})

    async def test_edit_name_and_price_use_same_validation(self) -> None:
        product_id = await self.database.add_product("Машина", 200)
        await self.action("edit", product_id)
        await self.form_action("name")
        await self.send_message("x" * 61)
        self.assertEqual((await self.database.get_active_product(product_id)).name, "Машина")
        self.assertEqual(await self.context().get_state(), CatalogStates.edit_name.state)
        await self.send_message("Авто")
        self.assertEqual((await self.database.get_active_product(product_id)).name, "Авто")
        await self.action("edit", product_id)
        await self.form_action("price")
        for value in ("0", "1000000", None):
            await self.send_message(value)
            self.assertEqual((await self.database.get_active_product(product_id)).price, 200)
            self.assertEqual(await self.context().get_state(), CatalogStates.edit_price.state)
        await self.send_message("250.75")
        self.assertEqual((await self.database.get_active_product(product_id)).price, 250.75)
        self.assertIsNone(await self.context().get_state())

    async def test_cancel_in_all_edit_steps_preserves_product(self) -> None:
        product_id = await self.database.add_product("Машина", 200)
        for field in (None, "name", "price"):
            await self.action("edit", product_id)
            if field is None:
                await self.form_action("cancel")
            else:
                await self.form_action(field)
                await self.send_message(t("btn_cancel", "ru"))
            product = await self.database.get_active_product(product_id)
            self.assertEqual((product.name, product.price), ("Машина", 200))
            self.assertIsNone(await self.context().get_state())

    async def test_delete_requires_yes_and_retains_database_row(self) -> None:
        product_id = await self.database.add_product("Машина", 200)
        for action in ("no", "cancel"):
            await self.action("delete", product_id)
            self.assertIsNotNone(await self.database.get_active_product(product_id))
            await self.form_action(action)
            self.assertIsNotNone(await self.database.get_active_product(product_id))
        await self.action("delete", product_id)
        old_token = (await self.context().get_data())["token"]
        await self.form_action("yes")
        self.assertIsNone(await self.database.get_active_product(product_id))
        self.assertEqual(await self.database.list_active_products(), [])
        async with aiosqlite.connect(self.path) as connection:
            async with connection.execute("SELECT name, price, is_active FROM products WHERE id = ?", (product_id,)) as cursor:
                self.assertEqual(await cursor.fetchone(), ("Машина", 200.0, 0))
        await self.form_action("yes", token=old_token)
        self.assertEqual(self.session.calls[-1].text, t("form_expired", "ru"))
        for action in ("select", "edit", "delete"):
            await self.action(action, product_id)
            self.assertIsInstance(self.session.calls[-1], AnswerCallbackQuery)
            self.assertEqual(self.session.calls[-1].text, t("product_unavailable", "ru"))

    async def test_stale_confirmation_cannot_delete_different_product(self) -> None:
        first = await self.database.add_product("First", 100)
        second = await self.database.add_product("Second", 200)
        await self.action("delete", first)
        old_token = (await self.context().get_data())["token"]
        await self.action("delete", second)
        await self.form_action("yes", token=old_token)
        self.assertEqual(self.session.calls[-1].text, t("form_expired", "ru"))
        self.assertEqual(len(await self.database.list_active_products()), 2)
        await self.form_action("yes")
        self.assertIsNotNone(await self.database.get_active_product(first))
        self.assertIsNone(await self.database.get_active_product(second))

    async def test_two_users_have_separate_dialogs_and_share_catalog(self) -> None:
        await self.click("catalog:add", 101)
        await self.click("catalog:add", 202)
        await self.send_message("Машина", 101)
        await self.send_message("Үй", 202)
        await self.send_message("200", 101)
        self.assertEqual(await self.context(202).get_state(), CatalogStates.add_price.state)
        await self.send_message("300", 202)
        await self.send_message(t("menu_catalog", "ru"), 101)
        self.assertEqual([(p.name, p.price) for p in await self.database.list_active_products()], [("Машина", 200), ("Үй", 300)])

    async def test_deleted_by_another_user_during_edit_is_not_restored(self) -> None:
        product_id = await self.database.add_product("Машина", 200)
        await self.action("edit", product_id, 101)
        await self.form_action("price", 101)
        await self.action("delete", product_id, 202)
        await self.form_action("yes", 202)
        await self.send_message("400", 101)
        self.assertIsNone(await self.context(101).get_state())
        self.assertIsNone(await self.database.get_active_product(product_id))
        self.assertFalse(await self.database.update_product_name(product_id, "Restored"))

    async def test_navigation_clears_drafts_and_old_confirmation(self) -> None:
        product_id = await self.database.add_product("Машина", 200)
        for text in ("/start", "/menu", "/language", t("menu_catalog", "ru"), t("menu_analytics", "ru")):
            await self.click("catalog:add")
            await self.send_message("Draft")
            await self.send_message(text)
            self.assertIsNone(await self.context().get_state())
            self.assertEqual(await self.context().get_data(), {})
        await self.action("delete", product_id)
        old_token = (await self.context().get_data())["token"]
        await self.send_message("/menu")
        await self.form_action("yes", token=old_token)
        self.assertIsNotNone(await self.database.get_active_product(product_id))

    async def test_whitelist_blocks_catalog_messages_and_callbacks(self) -> None:
        product_id = await self.database.add_product("Машина", 200)
        self.session.calls.clear()
        await self.send_message(t("menu_catalog", "ru"), 999)
        await self.click("catalog:add", 999)
        for action in ("select", "edit", "delete"):
            await self.action(action, product_id, 999)
        await self.form_action("yes", 999, token="forged")
        self.assertEqual(self.session.calls, [])
        self.assertEqual(len(await self.database.list_active_products()), 1)
        self.assertIsNone(await self.context(999).get_state())

    async def test_select_waits_for_receipt_and_cancel_creates_no_orders(self) -> None:
        product_id = await self.database.add_product("Машина", 200)
        await self.action("select", product_id)
        self.assertEqual(self.displayed_messages()[-1].text, t("ask_receipt", "ru", name="Машина", price="200 сом"))
        await self.send_message("/cancel")
        await self.send_message(None, photo=[PhotoSize(file_id="photo", file_unique_id="unique", width=10, height=10)])
        async with aiosqlite.connect(self.path) as connection:
            async with connection.execute("SELECT COUNT(*) FROM orders") as cursor:
                self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_product_changes_preserve_existing_order_snapshot(self) -> None:
        product_id = await self.database.add_product("Машина", 200)
        # A fixture proves catalog operations never update future order snapshots.
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute(
                """INSERT INTO orders (product_id, product_name, price, created_by, created_at, receipt_file_id, receipt_type)
                VALUES (?, 'Машина', 200, 101, '2026-10-13T06:00:00+00:00', 'fixture', 'photo')""",
                (product_id,),
            )
            await connection.commit()
        await self.database.update_product_name(product_id, "Авто")
        await self.database.update_product_price(product_id, 500)
        await self.database.soft_delete_product(product_id)
        async with aiosqlite.connect(self.path) as connection:
            async with connection.execute("SELECT product_name, price, receipt_file_id FROM orders") as cursor:
                self.assertEqual(await cursor.fetchone(), ("Машина", 200.0, "fixture"))

    async def test_rapid_duplicate_price_messages_add_only_once(self) -> None:
        await self.click("catalog:add")
        await self.send_message("Машина")
        await asyncio.gather(self.send_message("200"), self.send_message("200"))
        self.assertEqual(len(await self.database.list_active_products()), 1)

    async def test_products_survive_reinitialization_and_small_prices_are_displayed(self) -> None:
        await self.click("catalog:add")
        await self.send_message("Small")
        await self.send_message("0,000001")
        await init_db(self.path)
        products = await Database(self.path).list_active_products()
        self.assertEqual(products[0].price, 0.000001)
        self.assertEqual(format_money(products[0].price, "ru"), "0.000001 сом")


class CatalogValidationTests(unittest.TestCase):
    def test_price_boundaries_and_decimal_formats(self) -> None:
        for text, expected in (("200", 200), ("200,50", 200.5), ("200.50", 200.5), (".5", 0.5), ("0.001", 0.001), ("999999.99", 999999.99)):
            self.assertEqual(validate_price(text), expected)
        for text in (None, "", " ", "0", "-1", "1000000", "1000000.1", "NaN", "Infinity", "1e3", "200 сом", "1,000.50", "1 000", "999999.999999999999999"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_price(text)

    def test_name_boundaries(self) -> None:
        self.assertEqual(validate_name(" x "), "x")
        self.assertEqual(validate_name("я" * 60), "я" * 60)
        for text in (None, "", " \n\t ", "я" * 61, "bad\x00name"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_name(text)
