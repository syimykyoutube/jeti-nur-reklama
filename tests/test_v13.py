"""Receipt deep links, external Word relationships and in-place navigation."""

from dataclasses import replace
from html import escape
from io import BytesIO
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, GetMe, SendDocument, SendMessage, SendPhoto
from aiogram.types import Message
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.shared import Cm
from lxml import etree

from bot.callbacks import AnalyticsPeriodCallback, CatalogFormCallback, DeleteOrderCallback, OrderConfirmCallback, PeriodChoiceCallback, ProductCallback
from bot.config import ConfigError, load_config
from bot.handlers.orders import OrderStates, receipt_caption
from bot.i18n import t
from bot.main import create_dispatcher, main
from bot.services.report_docx import create_report
from bot.services.stats import make_period
from test_stage1 import BotTestCase, NOW, TEST_TOKEN
from test_stage3 import DOCUMENT, PHOTOS


class V13Tests(BotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.database.set_user_language(101, "Aibek", "ru")
        await self.database.set_user_language(202, "Aibek", "ky")
        self.product_id = await self.database.add_product("Машина <&>", 200)

    def state(self, user_id=101):
        return self.dispatcher.fsm.get_context(bot=self.bot, chat_id=user_id, user_id=user_id)

    def edits(self):
        return [call for call in self.session.calls if isinstance(call, EditMessageText)]

    async def select(self, message_id=711, user_id=101, product_id=None):
        await self.click(ProductCallback(action="select", product_id=product_id or self.product_id).pack(),
                         user_id, message_id=message_id)

    async def order(self, kind="photo"):
        with patch("bot.db.datetime") as clock:
            clock.now.return_value = NOW
            order_id = await self.database.add_order(
                product_id=self.product_id, product_name="Машина <&>", price=200,
                created_by=101, created_by_name="Автор <&>", receipt_file_id="PRIVATE_RECEIPT",
                receipt_file_unique_id="PRIVATE_UNIQUE", receipt_type=kind,
                receipt_file_name="private.pdf", description="Источник <&> " + "😀" * 680,
            )
        return await self.database.get_active_order(order_id)

    async def test_short_prompts_are_exact_in_both_languages_and_selection_only_edits(self):
        for user_id, lang, receipt_line, caption_line in (
            (101, "ru", "Отправьте чек (фото или документ).", "Напишите описание под фото!"),
            (202, "ky", "Чекти жөнөт (сүрөт же документ).", "Сүрөттүн астына описание жаз!"),
        ):
            self.session.calls.clear()
            await self.select(user_id=user_id)
            self.assertEqual(self.sent_messages(), [])
            self.assertIsInstance(self.session.calls[0], AnswerCallbackQuery)
            prompt = self.edits()[-1]
            self.assertEqual(prompt.text, f"<b>Машина &lt;&amp;&gt; — 200 сом</b>\n{receipt_line}\n{caption_line}")
            self.assertEqual((prompt.chat_id, prompt.message_id), (user_id, 711))
            self.assertEqual(prompt.reply_markup.inline_keyboard[0][0].text, t("btn_back", lang))
            data = await self.state(user_id).get_data()
            self.assertEqual((data["card_chat_id"], data["card_message_id"]), (user_id, 711))
            await self.send_message(None, user_id, photo=PHOTOS)
            self.assertEqual(self.sent_messages()[-1].text, "Чек получен ✅\nНапишите описание. Обязательно!" if lang == "ru"
                             else "Чек кабыл алынды ✅\nОписание жаз. Милдеттүү!")

    async def test_cancel_restores_original_card_at_both_steps_in_both_languages(self):
        for user_id, lang in ((101, "ru"), (202, "ky")):
            for with_receipt in (False, True):
                for action in ("/cancel", t("btn_back", lang), "order:cancel"):
                    await self.select(user_id=user_id)
                    if with_receipt:
                        await self.send_message(None, user_id, document=DOCUMENT)
                    self.session.calls.clear()
                    if action == "order:cancel":
                        await self.click(action, user_id, message_id=711)
                    else:
                        await self.send_message(action, user_id)
                    restored = self.edits()[-1]
                    self.assertEqual((restored.chat_id, restored.message_id), (user_id, 711))
                    self.assertEqual(restored.text, "<b>Машина &lt;&amp;&gt; — 200 сом</b>")
                    self.assertEqual(restored.reply_markup.inline_keyboard[0][0].text, t("btn_select", lang))
                    self.assertEqual((await self.database.get_orders_page()).total, 0)
                    self.assertEqual(await self.state(user_id).get_data(), {})
                    self.assertIsNone(await self.state(user_id).get_state())

    async def test_save_restores_card_and_keeps_confirmation_and_catalog_at_bottom(self):
        for separate_description in (False, True):
            await self.select()
            self.session.calls.clear()
            await self.send_message(None, photo=PHOTOS, caption=None if separate_description else "Источник рекламы")
            if separate_description:
                await self.send_message("Источник рекламы")
            self.assertEqual(self.edits()[-1].message_id, 711)
            self.assertEqual(self.edits()[-1].text, "<b>Машина &lt;&amp;&gt; — 200 сом</b>")
            self.assertIn(t("order_saved", "ru"), [m.text for m in self.sent_messages()])
            self.assertEqual(self.sent_messages()[-1].reply_markup.inline_keyboard[0][0].text, t("btn_select", "ru"))
        self.assertEqual((await self.database.get_orders_page()).total, 2)

    async def test_switching_cards_restores_previous_card_without_losing_new_quote(self):
        other = await self.database.add_product("Другой продукт", 300)
        await self.select()
        await self.send_message(None, photo=PHOTOS)
        self.session.calls.clear()
        await self.select(message_id=722, product_id=other)
        changes = {call.message_id: call for call in self.edits()}
        self.assertEqual(changes[711].text, "<b>Машина &lt;&amp;&gt; — 200 сом</b>")
        self.assertIn("Другой продукт — 300 сом", changes[722].text)
        data = await self.state().get_data()
        self.assertEqual((data["product_id"], data["price"], data["card_message_id"]), (other, 300, 722))
        self.assertNotIn("receipt_file_id", data)

    async def test_start_restores_card_but_preserves_v12_waiting_states(self):
        for with_receipt in (False, True):
            await self.select()
            if with_receipt:
                await self.send_message(None, photo=PHOTOS)
            draft = await self.state().get_data()
            current = await self.state().get_state()
            self.session.calls.clear()
            await self.send_message("/start")
            self.assertEqual(self.edits()[-1].message_id, 711)
            self.assertEqual(self.edits()[-1].text, "<b>Машина &lt;&amp;&gt; — 200 сом</b>")
            self.assertEqual(await self.state().get_state(), current)
            self.assertEqual(await self.state().get_data(), draft)

    async def test_other_navigation_also_restores_old_prompt(self):
        for action in ("/edit", "/menu", "/language", "/deleteorder", t("menu_analytics", "ru"), t("menu_catalog", "ru")):
            await self.select()
            self.session.calls.clear()
            await self.send_message(action)
            self.assertEqual(self.edits()[-1].message_id, 711)
            self.assertEqual(self.edits()[-1].text, "<b>Машина &lt;&amp;&gt; — 200 сом</b>")

    async def test_analytics_period_and_change_period_edit_same_message_in_both_languages(self):
        for user_id, lang in ((101, "ru"), (202, "ky")):
            await self.send_message(t("menu_analytics", lang), user_id)
            self.session.calls.clear()
            await self.click(PeriodChoiceCallback(period="d7").pack(), user_id, message_id=733)
            self.assertEqual(self.sent_messages(), [])
            summary = self.edits()[-1]
            self.assertEqual(summary.message_id, 733)
            self.assertIn(t("no_orders", lang), summary.text)
            self.assertEqual(summary.reply_markup.inline_keyboard[0][0].text, t("analytics_top", lang))
            self.session.calls.clear()
            await self.click("analytics:menu", user_id, message_id=733)
            self.assertEqual(self.sent_messages(), [])
            self.assertEqual((self.edits()[-1].message_id, self.edits()[-1].text), (733, t("choose_period", lang)))

    async def test_custom_period_updates_original_bot_message_after_text_input(self):
        await self.click(PeriodChoiceCallback(period="custom").pack(), message_id=744)
        self.assertEqual(self.edits()[-1].message_id, 744)
        self.session.calls.clear()
        await self.send_message("15")
        self.assertEqual(self.sent_messages(), [])
        self.assertEqual(self.edits()[-1].message_id, 744)
        self.assertIn("15", self.edits()[-1].text)
        self.assertIsNone(await self.state().get_state())

    async def test_section_results_remain_new_messages(self):
        await self.order()
        for mode, kind in (("top", SendMessage), ("chart", SendPhoto), ("orders", SendMessage), ("word", SendDocument)):
            self.session.calls.clear()
            await self.click(AnalyticsPeriodCallback(mode=mode, period="all").pack(), message_id=755)
            self.assertEqual(self.edits(), [])
            self.assertTrue(any(isinstance(call, kind) for call in self.session.calls))

    async def test_deleted_and_missing_deep_links_have_exact_localized_messages_then_menu(self):
        order = await self.order()
        await self.database.soft_delete_order(order.id, 101)
        for user_id, lang in ((101, "ru"), (202, "ky")):
            for order_id, expected in ((order.id, t("receipt_order_deleted", lang)), (999999999, t("receipt_order_not_found", lang))):
                self.session.calls.clear()
                await self.send_message(f"/start r{order_id}", user_id)
                self.assertEqual([m.text for m in self.sent_messages()], [expected, t("main_menu", lang)])
                self.assertFalse(any(isinstance(c, (SendPhoto, SendDocument)) for c in self.session.calls))

    async def test_existing_deep_links_deliver_photo_and_document_with_v12_caption(self):
        for kind, method in (("photo", SendPhoto), ("document", SendDocument)):
            order = await self.order(kind)
            for user_id, lang in ((101, "ru"), (202, "ky")):
                self.session.calls.clear()
                await self.send_message(f"/start@test_bot r{order.id}", user_id)
                delivery = next(c for c in self.session.calls if isinstance(c, method))
                self.assertEqual(delivery.caption, receipt_caption(order, self.config, lang))
                self.assertIn(escape(order.product_name), delivery.caption)
                self.assertEqual(self.sent_messages()[-1].text, t("main_menu", lang))

    async def test_deep_link_without_selected_language_uses_default_and_does_not_set_language(self):
        order = await self.order()
        for lang in ("ru", "ky"):
            config = replace(self.config, default_lang=lang)
            await self.dispatcher.fsm.close()
            self.dispatcher = create_dispatcher(config, self.database)
            with sqlite3.connect(self.path) as connection:
                connection.execute("DELETE FROM users WHERE tg_id = 101")
            self.session.calls.clear()
            await self.send_message(f"/start r{order.id}")
            self.assertTrue(any(isinstance(c, SendPhoto) for c in self.session.calls))
            self.assertEqual(self.sent_messages()[-1].text, t("main_menu", lang))
            self.assertIsNone(await self.database.get_user_language(101))

    async def test_invalid_payloads_do_not_query_receipts_and_outsiders_are_silent(self):
        with patch.object(self.database, "get_order_for_receipt_link", new_callable=AsyncMock) as lookup:
            for payload in ("r", "r-1", "r1x", "r1234567890", "r1 extra", "R1", "r١", "r1\n"):
                self.session.calls.clear()
                await self.send_message(f"/start {payload}")
                self.assertFalse(any(isinstance(c, (SendPhoto, SendDocument)) for c in self.session.calls))
                self.assertEqual(self.sent_messages()[-1].text, t("main_menu", "ru"))
            self.session.calls.clear()
            await self.send_message("/start r1", 999)
            self.assertEqual(self.session.calls, [])
            lookup.assert_not_awaited()

    async def test_both_delete_confirmations_edit_card_and_preserve_yes_no_behavior(self):
        order = await self.order()
        for user_id in (101, 202):
            for catalog in (True, False):
                for action in ("no", "yes"):
                    if catalog:
                        product_id = await self.database.add_product("Temporary", 100)
                        payload = ProductCallback(action="delete", product_id=product_id).pack()
                    else:
                        order = await self.order()
                        payload = DeleteOrderCallback(order_id=order.id, page=0).pack()
                    self.session.calls.clear()
                    await self.click(payload, user_id, message_id=766)
                    self.assertEqual(self.sent_messages(), [])
                    prompt = self.edits()[-1]
                    self.assertEqual(prompt.message_id, 766)
                    self.assertEqual([len(row) for row in prompt.reply_markup.inline_keyboard], [2])
                    token = (await self.state(user_id).get_data())["token"]
                    confirm = CatalogFormCallback if catalog else OrderConfirmCallback
                    await self.click(confirm(action=action, token=token).pack(), user_id, message_id=766)
                    kept = await (self.database.get_active_product(product_id) if catalog else self.database.get_active_order(order.id))
                    self.assertEqual(kept is None, action == "yes")

    async def test_not_modified_is_ignored_without_extra_message_and_old_message_falls_back(self):
        original = self.session.make_request
        async def not_modified(bot, method, timeout=None):
            if isinstance(method, EditMessageText):
                raise TelegramBadRequest(method=method, message="Bad Request: message is not modified")
            return await original(bot, method, timeout)
        with patch.object(self.session, "make_request", side_effect=not_modified):
            await self.select()
            await self.send_message("/cancel")
        self.assertFalse(any(m.text == t("ask_receipt", "ru", name=escape("Машина <&>"), price="200 сом") for m in self.sent_messages()))
        self.session.calls.clear()
        async def too_old(bot, method, timeout=None):
            if isinstance(method, EditMessageText) and method.message_id == 777:
                raise TelegramBadRequest(method=method, message="Bad Request: message can't be edited")
            return await original(bot, method, timeout)
        with patch.object(self.session, "make_request", side_effect=too_old):
            await self.select(message_id=777)
            self.assertEqual((await self.state().get_data())["card_message_id"], 900)
            self.assertEqual(len(self.sent_messages()), 1)
            await self.send_message("/cancel")
        self.assertEqual(self.edits()[-1].message_id, 900)

    async def test_analytics_edit_failure_sends_new_summary(self):
        original = self.session.make_request
        async def unavailable(bot, method, timeout=None):
            if isinstance(method, EditMessageText):
                raise TelegramBadRequest(method=method, message="message to edit not found")
            return await original(bot, method, timeout)
        with patch.object(self.session, "make_request", side_effect=unavailable):
            await self.click(PeriodChoiceCallback(period="d7").pack(), message_id=788)
        self.assertEqual(len(self.sent_messages()), 1)
        self.assertIn(t("no_orders", "ru"), self.sent_messages()[-1].text)

    async def test_word_external_relationships_landscape_widths_and_missing_receipt(self):
        photo = await self.order()
        doc = await self.order("document")
        missing = await self.order()
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE orders SET receipt_file_id = '' WHERE id = ?", (missing.id,))
        for lang in ("ru", "ky"):
            output = Path(self.temp.name) / f"links_{lang}.docx"
            await create_report(self.database, output, make_period("all", self.config.timezone), self.config.timezone,
                                lang, NOW, bot_username="jeti_nur_reklama_bot")
            document = Document(output)
            table = document.tables[-1]
            self.assertEqual(len(table.columns), 7)
            self.assertEqual(table.rows[0].cells[-1].text, "Чек")
            self.assertEqual(table.rows[1].cells[-1].text, "—")
            self.assertEqual(document.sections[0].orientation, WD_ORIENT.PORTRAIT)
            section = document.sections[-1]
            self.assertEqual(section.orientation, WD_ORIENT.LANDSCAPE)
            # Word serializes page sizes as integer twips, introducing tiny rounding.
            self.assertAlmostEqual(section.page_width / Cm(1), 29.7, places=2)
            self.assertAlmostEqual(section.page_height / Cm(1), 21, places=2)
            self.assertLessEqual(sum(c.width for c in table.columns), section.page_width - section.left_margin - section.right_margin)
            self.assertIsNotNone(table.rows[0]._tr.trPr.find(qn("w:tblHeader")))
            with ZipFile(output) as archive:
                xml = etree.fromstring(archive.read("word/document.xml"))
                relationships = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
                external = {r.get("Id"): r for r in relationships if r.get("Type").endswith("/hyperlink")}
                links = xml.findall(".//" + qn("w:hyperlink"))
                self.assertEqual(len(links), 2)
                targets = []
                for link in links:
                    relation = external[link.get(qn("r:id"))]
                    self.assertEqual(relation.get("TargetMode"), "External")
                    targets.append(relation.get("Target"))
                    self.assertEqual(link.find(".//" + qn("w:t")).text, "Чек")
                    self.assertEqual(link.find(".//" + qn("w:color")).get(qn("w:val")), "0563C1")
                    self.assertEqual(link.find(".//" + qn("w:u")).get(qn("w:val")), "single")
                self.assertEqual(set(targets), {f"https://t.me/jeti_nur_reklama_bot?start=r{o.id}" for o in (photo, doc)})
                self.assertNotIn(b"PRIVATE_RECEIPT", archive.read("word/document.xml"))

    async def test_export_passes_cached_username_to_report(self):
        self.config = replace(self.config, bot_username="configured_bot")
        await self.dispatcher.fsm.close()
        self.dispatcher = create_dispatcher(self.config, self.database)
        order = await self.order()
        await self.click(AnalyticsPeriodCallback(mode="word", period="all").pack())
        with ZipFile(BytesIO(self.session.uploaded_documents[-1][1])) as archive:
            self.assertIn(f"https://t.me/configured_bot?start=r{order.id}", archive.read("word/_rels/document.xml.rels").decode())

    async def test_delete_confirmation_fallback_tracks_new_message_and_rejects_old_one(self):
        original = self.session.make_request
        async def unavailable(bot, method, timeout=None):
            if isinstance(method, EditMessageText) and method.message_id == 799:
                raise TelegramBadRequest(method=method, message="message can't be edited")
            return await original(bot, method, timeout)
        for catalog in (True, False):
            if catalog:
                product_id = await self.database.add_product("Temporary", 100)
                payload = ProductCallback(action="delete", product_id=product_id).pack()
            else:
                order = await self.order()
                payload = DeleteOrderCallback(order_id=order.id, page=0).pack()
            with patch.object(self.session, "make_request", side_effect=unavailable):
                await self.click(payload, message_id=799)
                data = await self.state().get_data()
                self.assertEqual(data["message_id"], 900)
                confirm = CatalogFormCallback if catalog else OrderConfirmCallback
                await self.click(confirm(action="yes", token=data["token"]).pack(), message_id=799)
                kept = await (self.database.get_active_product(product_id) if catalog else self.database.get_active_order(order.id))
                self.assertIsNotNone(kept)
                await self.click(confirm(action="yes", token=data["token"]).pack(), message_id=900)
                kept = await (self.database.get_active_product(product_id) if catalog else self.database.get_active_order(order.id))
                self.assertIsNone(kept)

    async def test_startup_uses_env_username_or_resolves_once_and_caches_in_dispatcher(self):
        for configured, expected in (("configured_bot", "configured_bot"), (None, "test_bot")):
            config = replace(self.config, bot_username=configured)
            self.session.calls.clear()
            with patch("bot.main.load_config", return_value=config), patch("bot.main.Bot", return_value=self.bot), \
                 patch.object(self.bot, "delete_webhook", new_callable=AsyncMock), \
                 patch("bot.main.create_dispatcher", return_value=self.dispatcher) as factory, \
                 patch.object(self.dispatcher, "start_polling", new_callable=AsyncMock):
                await main()
            self.assertEqual(factory.call_args.args[0].bot_username, expected)
            self.assertEqual(sum(isinstance(c, GetMe) for c in self.session.calls), int(configured is None))

    async def test_username_env_parsing_and_validation(self):
        env = Path(self.temp.name) / "missing.env"
        for value, expected in (("", None), ("jeti_nur_reklama_bot", "jeti_nur_reklama_bot"), (" @test_bot ", "test_bot")):
            with patch.dict("os.environ", {"BOT_TOKEN": TEST_TOKEN, "BOT_USERNAME": value}, clear=True):
                self.assertEqual(load_config(env).bot_username, expected)
        for value in ("https://t.me/test_bot", "bad/name", "tiny", "a" * 33):
            with patch.dict("os.environ", {"BOT_TOKEN": TEST_TOKEN, "BOT_USERNAME": value}, clear=True), self.assertRaises(ConfigError):
                load_config(env)
