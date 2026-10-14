"""Separate ordering catalog and /edit navigation, CRUD return paths and fallback."""

from aiogram.methods import DeleteMessage

from bot.callbacks import CatalogFormCallback, ProductCallback
from bot.handlers.analytics import AnalyticsStates
from bot.handlers.catalog import CatalogStates
from bot.handlers.orders import OrderStates
from bot.i18n import t
from test_stage1 import BotTestCase
from test_stage3 import PHOTOS


class CatalogEditTests(BotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.database.set_user_language(101, "Aibek", "ru")
        await self.database.set_user_language(202, "Aibek", "ky")
        self.product_id = await self.database.add_product("Машина <&>", 200)

    def context(self, user_id=101):
        return self.dispatcher.fsm.get_context(bot=self.bot, chat_id=user_id, user_id=user_id)

    def assert_editor(self, lang):
        messages = self.sent_messages()
        heading = max(index for index, message in enumerate(messages) if message.text == t("catalog_edit_mode", lang))
        editor = messages[heading:]
        self.assertEqual(editor[-1].text, t("catalog_actions", lang))
        self.assertEqual([len(row) for row in editor[-1].reply_markup.inline_keyboard], [1])
        self.assertEqual(editor[-1].reply_markup.inline_keyboard[0][0].callback_data, "catalog:add")
        cards = [message for message in editor if message.text.startswith("<b>")]
        for card in cards:
            rows = card.reply_markup.inline_keyboard
            self.assertEqual([len(row) for row in rows], [2])
            self.assertEqual([button.text for button in rows[0]], ["✏️", "🗑"])
            self.assertEqual([ProductCallback.unpack(button.callback_data).action for button in rows[0]], ["edit", "delete"])
        return cards

    async def form(self, action, user_id=101, token=None):
        token = token or (await self.context(user_id).get_data())["token"]
        await self.click(CatalogFormCallback(action=action, token=token).pack(), user_id)

    async def test_normal_and_editor_layouts_in_both_languages(self):
        for user_id, lang in ((101, "ru"), (202, "ky")):
            self.session.calls.clear()
            await self.send_message(t("menu_catalog", lang), user_id)
            messages = self.sent_messages()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].text, "<b>Машина &lt;&amp;&gt; — 200 сом</b>")
            rows = messages[0].reply_markup.inline_keyboard
            self.assertEqual([len(row) for row in rows], [1])
            self.assertEqual(rows[0][0].text, t("btn_select", lang))
            self.assertEqual(ProductCallback.unpack(rows[0][0].callback_data).action, "select")
            self.session.calls.clear()
            await self.send_message("/edit", user_id)
            self.assertEqual(self.sent_messages()[0].text, t("catalog_edit_mode", lang))
            self.assertEqual(len(self.assert_editor(lang)), 1)
            self.assertEqual(self.sent_messages()[-1].reply_markup.inline_keyboard[0][0].text, t("btn_add", lang))

    async def test_empty_normal_catalog_has_edit_hint_and_no_add_button(self):
        await self.database.soft_delete_product(self.product_id)
        for user_id, lang in ((101, "ru"), (202, "ky")):
            self.session.calls.clear()
            await self.send_message("📋 Каталог", user_id)
            messages = self.sent_messages()
            self.assertEqual([message.text for message in messages], [t("catalog_empty", lang), t("catalog_edit_hint", lang)])
            self.assertTrue(all(message.reply_markup is None for message in messages))
            self.assertIn("/edit", messages[-1].text)
            self.session.calls.clear()
            await self.send_message("/edit", user_id)
            self.assertEqual(len(self.assert_editor(lang)), 0)
            self.assertEqual(self.sent_messages()[1].text, t("catalog_empty", lang))

    async def test_all_catalog_actions_return_to_editor_in_both_languages(self):
        for user_id, lang in ((101, "ru"), (202, "ky")):
            await self.send_message("/edit", user_id)
            await self.click("catalog:add", user_id)
            await self.send_message("Новый", user_id)
            self.session.calls.clear()
            await self.send_message("100,5", user_id)
            self.assert_editor(lang)
            product = (await self.database.list_active_products())[-1]
            for field, value in (("name", "Изменённый <&>"), ("price", "150")):
                await self.click(ProductCallback(action="edit", product_id=product.id).pack(), user_id)
                await self.form(field, user_id)
                self.session.calls.clear()
                await self.send_message(value, user_id)
                cards = self.assert_editor(lang)
                self.assertTrue(any("Изменённый &lt;&amp;&gt;" in card.text for card in cards))
                self.assertIsNone(await self.context(user_id).get_state())
            for action in ("no", "yes"):
                await self.click(ProductCallback(action="delete", product_id=product.id).pack(), user_id)
                token = (await self.context(user_id).get_data())["token"]
                self.session.calls.clear()
                await self.form(action, user_id, token)
                self.assert_editor(lang)
                self.assertIsNone(await self.context(user_id).get_state())
                self.assertEqual(await self.context(user_id).get_data(), {})
                if action == "no":
                    self.assertIsNotNone(await self.database.get_active_product(product.id))
                else:
                    self.assertIsNone(await self.database.get_active_product(product.id))
                await self.form("yes", user_id, token)
                self.assertEqual(self.session.calls[-1].text, t("form_expired", lang))
            for step in (None, "name"):
                await self.click("catalog:add", user_id)
                if step:
                    await self.send_message("Draft", user_id)
                self.session.calls.clear()
                await self.send_message("/cancel", user_id)
                self.assert_editor(lang)
                self.assertIsNone(await self.context(user_id).get_state())

    async def test_edit_command_is_not_deleted_or_consumed_by_fsm(self):
        before = await self.database.list_active_products()
        for step in (*CatalogStates.__all_states__, OrderStates.awaiting_receipt, OrderStates.delete_confirm, AnalyticsStates.custom_days):
            await self.context().set_state(step)
            await self.context().set_data({"token": "old", "product_id": self.product_id})
            self.session.calls.clear()
            await self.send_message("/edit")
            self.assert_editor("ru")
            self.assertIsNone(await self.context().get_state())
            self.assertEqual(await self.context().get_data(), {})
            self.assertFalse(any(isinstance(call, DeleteMessage) for call in self.session.calls))
            self.assertEqual(await self.database.list_active_products(), before)
        self.session.calls.clear()
        await self.send_message("/edit@test_bot")
        self.assert_editor("ru")
        self.assertFalse(any(isinstance(call, DeleteMessage) for call in self.session.calls))
        self.session.calls.clear()
        await self.send_message("/edit", 999)
        self.assertEqual(self.session.calls, [])
        await self.database.set_user_language(101, "Aibek", "ru")
        await self.send_message("/menu")
        self.assertIn("/edit — Редактировать каталог", self.sent_messages()[-1].text)

    async def test_normal_catalog_navigation_and_receipts_do_not_return_to_editor(self):
        await self.send_message("/edit")
        await self.click("catalog:add")
        await self.send_message("Draft")
        self.session.calls.clear()
        await self.send_message("📋 Каталог")
        self.assertEqual(len(self.sent_messages()), 1)
        self.assertIsNone(await self.context().get_state())
        self.assertEqual(ProductCallback.unpack(self.sent_messages()[0].reply_markup.inline_keyboard[0][0].callback_data).action, "select")
        for save in (False, True):
            await self.click(ProductCallback(action="select", product_id=self.product_id).pack())
            self.session.calls.clear()
            if save:
                await self.send_message(None, photo=PHOTOS)
            else:
                await self.click("order:cancel")
            self.assertFalse(any(message.text == t("catalog_edit_mode", "ru") for message in self.sent_messages()))
            last = self.sent_messages()[-1]
            self.assertEqual([len(row) for row in last.reply_markup.inline_keyboard], [1])
            self.assertEqual(ProductCallback.unpack(last.reply_markup.inline_keyboard[0][0].callback_data).action, "select")
        self.assertEqual((await self.database.get_orders_page()).total, 1)
