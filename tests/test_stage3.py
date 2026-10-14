"""Receipt and soft-delete acceptance tests against isolated temporary data."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import aiosqlite
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from aiogram.types import Animation, Dice, Document, PhotoSize, Voice

from bot.callbacks import DeleteOrderCallback, OrderConfirmCallback, OrderPageCallback, ProductCallback
from bot.db import Database, init_db
from bot.handlers.orders import OrderStates
from bot.i18n import t
from bot.main import create_dispatcher
from test_stage1 import BotTestCase, NOW


PHOTOS = [
    PhotoSize(file_id="small", file_unique_id="small-unique", width=10, height=10),
    PhotoSize(file_id="large", file_unique_id="large-unique", width=100, height=100),
]
DOCUMENT = Document(file_id="pdf", file_unique_id="pdf-unique", file_name="receipt.pdf", mime_type="application/pdf")


class OrderTests(BotTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.database.set_user_language(101, "Aibek", "ru")
        await self.database.set_user_language(202, "Test", "ky")
        self.product_id = await self.database.add_product("Машина", 200)

    def context(self, user_id=101):
        return self.dispatcher.fsm.get_context(bot=self.bot, chat_id=user_id, user_id=user_id)

    async def select(self, user_id=101, product_id=None) -> None:
        await self.click(ProductCallback(action="select", product_id=product_id or self.product_id).pack(), user_id)

    async def all_rows(self) -> list[dict]:
        # Audit read for tests only: production lookups filter out deleted rows.
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute("SELECT * FROM orders ORDER BY id") as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def make_order(self, created_by=101, name="Машина", price=200) -> int:
        with patch("bot.db.datetime") as clock:
            clock.now.return_value = NOW
            return await self.database.add_order(
                product_id=self.product_id, product_name=name, price=price,
                created_by=created_by, created_by_name=f"User {created_by}",
                receipt_file_id="fixture", receipt_file_unique_id="fixture-unique", receipt_type="photo",
            )

    async def choose_order(self, order_id, page=0, user_id=101) -> None:
        await self.click(DeleteOrderCallback(order_id=order_id, page=page).pack(), user_id)

    async def confirm(self, action="yes", user_id=101, token=None) -> None:
        if token is None:
            token = (await self.context(user_id).get_data())["token"]
        await self.click(OrderConfirmCallback(action=action, token=token).pack(), user_id)

    def order_buttons(self):
        buttons = []
        for message in self.sent_messages():
            keyboard = message.reply_markup
            if keyboard is None or not hasattr(keyboard, "inline_keyboard"):
                continue
            for row in keyboard.inline_keyboard:
                for button in row:
                    if button.callback_data.startswith("order_delete:"):
                        buttons.append((DeleteOrderCallback.unpack(button.callback_data), message.text))
        return buttons

    def edited_messages(self):
        return [call for call in self.session.calls if isinstance(call, EditMessageText)]

    async def test_select_then_photo_records_metadata_and_returns_catalog(self) -> None:
        await self.select()
        self.assertEqual(self.sent_messages()[-1].text, "Машина — 200 сом. Отправьте чек.")
        self.assertEqual(self.sent_messages()[-1].reply_markup.inline_keyboard[0][0].text, "❌ Назад")
        self.assertEqual(await self.all_rows(), [])
        await self.send_message(None, photo=PHOTOS, caption="Payment")
        rows = await self.all_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["product_id"], row["product_name"], row["price"]), (self.product_id, "Машина", 200))
        self.assertEqual((row["receipt_file_id"], row["receipt_file_unique_id"], row["receipt_type"], row["receipt_file_name"]), ("large", "large-unique", "photo", None))
        self.assertEqual((row["created_by"], row["created_by_name"]), (101, "Aibek"))
        self.assertEqual(datetime.fromisoformat(row["created_at"]).utcoffset().total_seconds(), 0)
        self.assertIsNone(row["deleted_at"])
        self.assertIsNone(row["deleted_by"])
        self.assertIsNone(await self.context().get_state())
        self.assertEqual(await self.context().get_data(), {})
        self.assertIn("Заказ сохранён ✅", [m.text for m in self.sent_messages()])
        self.assertEqual(ProductCallback.unpack(self.sent_messages()[-1].reply_markup.inline_keyboard[0][0].callback_data).action, "select")

    async def test_document_and_kyrgyz_prompts(self) -> None:
        await self.select(202)
        self.assertEqual(self.sent_messages()[-1].text, "Машина — 200 сом. Чекти жөнөт.")
        self.assertEqual(self.sent_messages()[-1].reply_markup.inline_keyboard[0][0].text, "❌ Артка")
        await self.send_message(None, 202, document=DOCUMENT)
        row = (await self.all_rows())[0]
        self.assertEqual((row["receipt_type"], row["receipt_file_id"], row["receipt_file_unique_id"], row["receipt_file_name"]), ("document", "pdf", "pdf-unique", "receipt.pdf"))
        self.assertEqual(row["created_by"], 202)
        self.assertIn("Заказ сакталды ✅", [m.text for m in self.sent_messages()])

    async def test_document_without_filename_is_accepted(self) -> None:
        await self.select()
        await self.send_message(None, document=Document(file_id="file", file_unique_id="unique"))
        self.assertIsNone((await self.all_rows())[0]["receipt_file_name"])

    async def test_other_types_remind_without_changing_state_or_saving(self) -> None:
        await self.select()
        original_data = await self.context().get_data()
        for text, content in (
            ("hello", {}),
            (None, {"voice": Voice(file_id="voice", file_unique_id="voice-unique", duration=1)}),
            (None, {"dice": Dice(emoji="🎲", value=3)}),
            # Telegram includes a document alongside animations for compatibility.
            (None, {"animation": Animation(file_id="gif", file_unique_id="gif-unique", width=10, height=10, duration=1), "document": DOCUMENT}),
        ):
            await self.send_message(text, **content)
            self.assertEqual(self.sent_messages()[-1].text, t("receipt_wrong", "ru"))
            self.assertEqual(await self.context().get_state(), OrderStates.awaiting_receipt.state)
            self.assertEqual(await self.context().get_data(), original_data)
            self.assertEqual(await self.all_rows(), [])

    async def test_back_cancel_and_navigation_discard_without_order(self) -> None:
        for text in (t("btn_back", "ru"), t("btn_back", "ky"), "/cancel", t("btn_cancel", "ru"), "/start", "/menu", "/language", t("menu_catalog", "ru"), t("menu_analytics", "ru")):
            await self.select()
            await self.send_message(text)
            self.assertIsNone(await self.context().get_state())
            await self.send_message(None, photo=PHOTOS)
            self.assertEqual(await self.all_rows(), [])
        await self.select()
        await self.click("order:cancel")
        self.assertIsNone(await self.context().get_state())

    async def test_quote_snapshot_survives_catalog_changes_before_and_after_receipt(self) -> None:
        await self.select()
        await self.database.update_product_name(self.product_id, "Авто")
        await self.database.update_product_price(self.product_id, 500)
        await self.database.soft_delete_product(self.product_id)
        await self.send_message(None, document=DOCUMENT)
        row = (await self.all_rows())[0]
        self.assertEqual((row["product_name"], row["price"]), ("Машина", 200))
        self.assertIsNotNone(await self.database.get_active_order(row["id"]))
        self.assertIsNone(await self.database.get_active_product(self.product_id))

    async def test_reselect_replaces_pending_snapshot(self) -> None:
        other_id = await self.database.add_product("Үй", 300)
        await self.select()
        await self.select(product_id=other_id)
        await self.send_message(None, photo=PHOTOS)
        self.assertEqual([(r["product_name"], r["price"]) for r in await self.all_rows()], [("Үй", 300)])

    async def test_two_users_receipts_and_rapid_duplicate_delivery(self) -> None:
        await self.select(101)
        await self.select(202)
        await asyncio.gather(self.send_message(None, 101, photo=PHOTOS), self.send_message(None, 101, photo=PHOTOS))
        self.assertEqual(len(await self.all_rows()), 1)
        self.assertEqual(await self.context(202).get_state(), OrderStates.awaiting_receipt.state)
        await self.send_message(None, 202, document=DOCUMENT)
        self.assertEqual([r["created_by"] for r in await self.all_rows()], [101, 202])

    async def test_analytics_opens_five_sections(self) -> None:
        await self.send_message(t("menu_analytics", "ru"))
        self.assertEqual(self.sent_messages()[-1].text, t("choose_period", "ru"))
        self.assertEqual(sum(len(row) for row in self.sent_messages()[-1].reply_markup.inline_keyboard), 5)

    async def test_pagination_lists_ten_all_users_newest_first_and_local_time(self) -> None:
        ids = [await self.make_order(created_by=101 if i % 2 else 202, name=f"Product {i}") for i in range(23)]
        await self.send_message("/deleteorder")
        self.assertEqual([cb.order_id for cb, _ in self.order_buttons()], ids[::-1][:10])
        self.assertIn("12:00 · 13.10.2026", self.order_buttons()[0][1])
        self.assertIn("User 202", self.order_buttons()[0][1])
        self.assertEqual(self.sent_messages()[-1].text, t("pagination", "ru"))
        self.session.calls.clear()
        await self.click(OrderPageCallback(page=1).pack())
        self.assertEqual([cb.order_id for cb, _ in self.order_buttons()], ids[::-1][10:20])
        navigation = self.sent_messages()[-1].reply_markup.inline_keyboard[0]
        self.assertEqual([b.text for b in navigation], ["◀", "▶"])
        self.session.calls.clear()
        await self.click(OrderPageCallback(page=2).pack())
        self.assertEqual([cb.order_id for cb, _ in self.order_buttons()], ids[::-1][20:])
        self.session.calls.clear()
        await self.click(OrderPageCallback(page=0).pack())
        self.assertEqual(len(self.order_buttons()), 10)

    async def test_empty_list_and_kyrgyz_delete_confirmation(self) -> None:
        await self.send_message("/deleteorder", 202)
        self.assertEqual(self.sent_messages()[-1].text, t("no_orders_to_delete", "ky"))
        order_id = await self.make_order()
        await self.choose_order(order_id, user_id=202)
        self.assertEqual(self.edited_messages()[-1].text, "Чын эле өчүрөсүңбү?")
        self.assertEqual([b.text for b in self.edited_messages()[-1].reply_markup.inline_keyboard[0]], ["Ооба", "Жок"])
        await self.confirm(user_id=202)
        self.assertEqual(self.edited_messages()[-1].text, t("order_deleted", "ky"))

    async def test_no_and_cancel_keep_order_yes_retains_receipt_and_audit_fields(self) -> None:
        order_id = await self.make_order(created_by=101)
        await self.choose_order(order_id, user_id=202)
        await self.confirm("no", user_id=202)
        self.assertIsNotNone(await self.database.get_active_order(order_id))
        await self.choose_order(order_id, user_id=202)
        await self.send_message("/cancel", 202)
        self.assertIsNone(await self.context(202).get_state())
        self.assertIsNotNone(await self.database.get_active_order(order_id))
        before = (await self.all_rows())[0]
        await self.choose_order(order_id, user_id=202)
        await self.send_message("Да", 202)
        self.assertIsNotNone(await self.database.get_active_order(order_id))
        await self.confirm("yes", user_id=202)
        after = (await self.all_rows())[0]
        self.assertEqual(after["deleted_by"], 202)
        self.assertEqual(datetime.fromisoformat(after["deleted_at"]).utcoffset().total_seconds(), 0)
        self.assertEqual({k: v for k, v in after.items() if not k.startswith("deleted_")}, {k: v for k, v in before.items() if not k.startswith("deleted_")})
        self.assertIsNone(await self.database.get_active_order(order_id))
        self.assertEqual((await self.database.get_orders_page()).total, 0)

    async def test_no_finishes_confirmation_in_both_languages_without_changing_order(self) -> None:
        for user_id, lang, labels, cancelled_text in (
            (101, "ru", ["Да", "Нет"], "Удаление отменено"),
            (202, "ky", ["Ооба", "Жок"], "Жокко чыгарылды"),
        ):
            with self.subTest(lang=lang):
                order_id = await self.make_order()
                before = await self.all_rows()
                await self.choose_order(order_id, user_id=user_id)
                confirmation = self.edited_messages()[-1]
                self.assertEqual(confirmation.text, t("confirm_delete", lang))
                rows = confirmation.reply_markup.inline_keyboard
                self.assertEqual([len(row) for row in rows], [2])
                self.assertEqual([button.text for button in rows[0]], labels)
                token = (await self.context(user_id).get_data())["token"]
                self.session.calls.clear()
                await self.confirm("no", user_id, token)
                self.assertIsInstance(self.session.calls[0], AnswerCallbackQuery)
                edit = self.edited_messages()[-1]
                self.assertEqual(edit.text, cancelled_text)
                self.assertEqual(edit.message_id, confirmation.message_id)
                self.assertIsNone(edit.reply_markup)
                self.assertEqual(self.sent_messages(), [])
                self.assertIsNone(await self.context(user_id).get_state())
                self.assertEqual(await self.context(user_id).get_data(), {})
                self.assertEqual(await self.all_rows(), before)
                for action in ("no", "yes"):
                    await self.confirm(action, user_id, token)
                    self.assertIsInstance(self.session.calls[-1], AnswerCallbackQuery)
                    self.assertEqual(self.session.calls[-1].text, t("order_dialog_expired", lang))
                    self.assertEqual(await self.all_rows(), before)
                # An old confirmation must not consume a subsequent receipt draft.
                await self.select(user_id)
                draft = await self.context(user_id).get_data()
                await self.confirm("no", user_id, token)
                self.assertEqual(await self.context(user_id).get_state(), OrderStates.awaiting_receipt.state)
                self.assertEqual(await self.context(user_id).get_data(), draft)
                await self.send_message("/cancel", user_id)
                await self.choose_order(order_id, user_id=user_id)
                await self.confirm("yes", user_id)
                row = next(item for item in await self.all_rows() if item["id"] == order_id)
                self.assertIsNotNone(row["deleted_at"])
                self.assertEqual(row["deleted_by"], user_id)
                self.assertEqual(row["receipt_file_id"], "fixture")
                self.assertIsNone(await self.database.get_active_order(order_id))

    async def test_stale_confirmation_cannot_delete_new_selection(self) -> None:
        first = await self.make_order()
        second = await self.make_order()
        await self.choose_order(first)
        old_token = (await self.context().get_data())["token"]
        await self.choose_order(second)
        await self.confirm(token=old_token)
        self.assertEqual(self.session.calls[-1].text, t("order_dialog_expired", "ru"))
        self.assertIsNotNone(await self.database.get_active_order(first))
        self.assertIsNotNone(await self.database.get_active_order(second))
        await self.confirm()
        self.assertIsNone(await self.database.get_active_order(second))
        await self.confirm(token=old_token)
        self.assertIsNotNone(await self.database.get_active_order(first))

    async def test_deleted_by_other_user_does_not_overwrite_original_audit(self) -> None:
        order_id = await self.make_order()
        await self.choose_order(order_id, user_id=101)
        await self.choose_order(order_id, user_id=202)
        await self.confirm(user_id=202)
        first_deletion = (await self.all_rows())[0]
        await self.confirm(user_id=101)
        self.assertEqual((await self.all_rows())[0], first_deletion)
        await self.choose_order(order_id)
        self.assertEqual(self.session.calls[-1].text, t("order_unavailable", "ru"))
        self.assertFalse(await self.database.soft_delete_order(order_id, 101))

    async def test_last_page_is_clamped_after_delete_and_deleted_orders_are_excluded(self) -> None:
        ids = [await self.make_order() for _ in range(11)]
        await self.choose_order(ids[0], page=1)
        await self.confirm()
        self.assertEqual(self.edited_messages()[-1].text, t("order_deleted", "ru"))
        self.session.calls.clear()
        await self.click(OrderPageCallback(page=1).pack())
        self.assertEqual(len(self.order_buttons()), 10)
        self.assertNotIn(ids[0], [cb.order_id for cb, _ in self.order_buttons()])
        page = await self.database.get_orders_page(2**31 - 1)
        self.assertEqual((page.page, page.pages, page.total), (0, 1, 10))
        for order_id in ids[1:]:
            await self.database.soft_delete_order(order_id, 101)
        self.assertEqual((await self.database.get_orders_page()).orders, [])
        self.assertEqual(len(await self.all_rows()), 11)

    async def test_receipt_and_confirmation_after_restart_cannot_write(self) -> None:
        saved_id = await self.make_order()
        await self.select()
        await self.dispatcher.fsm.close()
        self.dispatcher = create_dispatcher(self.config, self.database)
        await self.send_message(None, photo=PHOTOS)
        self.assertEqual(len(await self.all_rows()), 1)
        await self.choose_order(saved_id)
        token = (await self.context().get_data())["token"]
        await self.dispatcher.fsm.close()
        await init_db(self.path)
        self.database = Database(self.path)
        self.dispatcher = create_dispatcher(self.config, self.database)
        await self.confirm(token=token)
        self.assertEqual(self.session.calls[-1].text, t("order_dialog_expired", "ru"))
        self.assertIsNotNone(await self.database.get_active_order(saved_id))

    async def test_whitelist_blocks_receipts_deletion_and_confirmation(self) -> None:
        order_id = await self.make_order()
        await self.choose_order(order_id)
        token = (await self.context().get_data())["token"]
        self.session.calls.clear()
        await self.select(user_id=999)
        await self.send_message(None, 999, photo=PHOTOS)
        await self.send_message(None, 999, document=DOCUMENT)
        await self.send_message(t("menu_delete_order", "ru"), 999)
        self.session.calls.clear()
        await self.click(OrderPageCallback(page=0).pack(), 999)
        await self.choose_order(order_id, user_id=999)
        await self.confirm(user_id=999, token=token)
        self.assertEqual(self.session.calls, [])
        self.assertIsNotNone(await self.database.get_active_order(order_id))
        self.assertEqual(len(await self.all_rows()), 1)

    async def test_confirmations_expire_after_navigation_or_receipt_selection(self) -> None:
        order_id = await self.make_order()
        for command in ("/start", "/menu", "/language", "/cancel", t("menu_catalog", "ru")):
            await self.choose_order(order_id)
            token = (await self.context().get_data())["token"]
            await self.send_message(command)
            await self.confirm(token=token)
            self.assertIsNotNone(await self.database.get_active_order(order_id))
        await self.choose_order(order_id)
        token = (await self.context().get_data())["token"]
        await self.select()
        await self.confirm(token=token)
        self.assertEqual(await self.context().get_state(), OrderStates.awaiting_receipt.state)

    async def test_midnight_timezone_conversion_and_creation_time_not_message_time(self) -> None:
        await self.select()
        utc = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
        with patch("bot.db.datetime") as clock:
            clock.now.return_value = utc
            await self.send_message(None, document=DOCUMENT)
        self.assertEqual((await self.all_rows())[0]["created_at"], utc.isoformat(timespec="microseconds"))
        await self.send_message("/deleteorder")
        self.assertIn("01:00 · 13.10.2026", self.order_buttons()[0][1])

    async def test_database_refuses_missing_or_wrong_receipt(self) -> None:
        for receipt_type, receipt_id in (("text", "file"), ("photo", "")):
            with self.assertRaises(ValueError):
                await self.database.add_order(
                    product_id=self.product_id, product_name="Машина", price=200,
                    created_by=101, created_by_name="Aibek", receipt_file_id=receipt_id,
                    receipt_file_unique_id=None, receipt_type=receipt_type,
                )
        self.assertEqual(await self.all_rows(), [])
