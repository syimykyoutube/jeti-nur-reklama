"""Period boundaries, SQL aggregates, analytics routing, receipt and chart checks."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import aiosqlite
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendDocument, SendPhoto
from aiogram.types import BufferedInputFile
from PIL import Image

from bot.callbacks import (
    AnalyticsKindCallback, AnalyticsPageCallback, AnalyticsPeriodCallback, PeriodChoiceCallback, ProductCallback, ReceiptCallback,
)
from bot.i18n import format_money, t
from bot.main import create_dispatcher
from bot.services.charts import chart_png, plt
from bot.services.stats import (
    ANALYTICS_MODES, PERIOD_KEYS, ChartBucket, ChartSeries, bucket_date, chart_weekly,
    fill_chart_buckets, make_period, period_from_anchor,
)
from test_stage1 import BotTestCase, NOW


TZ = ZoneInfo("Asia/Bishkek")


class PeriodTests(unittest.TestCase):
    def test_all_calendar_periods_and_utc_bounds(self) -> None:
        starts = {
            "1": (2026, 10, 12), "3": (2026, 10, 10), "7": (2026, 10, 6),
            "10": (2026, 10, 3), "20": (2026, 9, 23), "30": (2026, 9, 13),
            "60": (2026, 8, 14), "90": (2026, 7, 15),
        }
        for key, (year, month, day) in starts.items():
            period = make_period(key, TZ, NOW)
            self.assertEqual(period.start, datetime(year, month, day, 18, tzinfo=timezone.utc), key)
            self.assertEqual(period.end, NOW)
        self.assertIsNone(make_period("all", TZ, NOW).start)

    def test_local_midnight_and_dst_follow_configured_timezone(self) -> None:
        period = make_period("1", TZ, datetime(2026, 10, 12, 18, tzinfo=timezone.utc))
        self.assertEqual(period.start, period.end)
        ny = ZoneInfo("America/New_York")
        period = make_period("3", ny, datetime(2026, 11, 2, 17, tzinfo=timezone.utc))
        self.assertEqual(period.start, datetime(2026, 10, 31, 4, tzinfo=timezone.utc))

    def test_anchors_round_trip_and_invalid_periods(self) -> None:
        for key in PERIOD_KEYS:
            period = make_period(key, TZ, NOW.replace(microsecond=123456))
            self.assertEqual(period_from_anchor(key, period.anchor, TZ), period)
        with self.assertRaises(ValueError):
            make_period("365", TZ, NOW)
        with self.assertRaises(ValueError):
            make_period("1", TZ, NOW.replace(tzinfo=None))

    def test_daily_weekly_threshold_and_monday_buckets(self) -> None:
        self.assertFalse(chart_weekly(make_period("30", TZ, NOW), NOW.isoformat(), TZ))
        for key in ("60", "90"):
            self.assertTrue(chart_weekly(make_period(key, TZ, NOW), NOW.isoformat(), TZ))
        period = make_period("all", TZ, NOW)
        self.assertFalse(chart_weekly(period, (NOW - timedelta(days=30)).isoformat(), TZ))
        self.assertTrue(chart_weekly(period, (NOW - timedelta(days=31)).isoformat(), TZ))
        self.assertEqual(bucket_date("2026-10-11T19:00:00+00:00", TZ, True), date(2026, 10, 12))

    def test_gaps_are_zero_and_week_edges_stay_partial(self) -> None:
        period = make_period("3", TZ, NOW)
        series = fill_chart_buckets([ChartBucket(date(2026, 10, 13), 200)], period, TZ, False)
        self.assertEqual([(b.day, b.total) for b in series.buckets], [(date(2026, 10, 11), 0), (date(2026, 10, 12), 0), (date(2026, 10, 13), 200)])
        series = fill_chart_buckets([ChartBucket(date(2026, 10, 12), 200)], make_period("60", TZ, NOW), TZ, True)
        self.assertEqual(series.buckets[0].day, date(2026, 8, 10))
        self.assertEqual(sum(b.total for b in series.buckets), 200)

    def test_sum_format_avoids_float_artifacts(self) -> None:
        self.assertEqual(format_money(200.1 + 300.2, "ru"), "500.3 сом")
        self.assertEqual(format_money(4200, "ky"), "4 200 сом")
        self.assertEqual(format_money(0.000001, "ru"), "0.000001 сом")


class AnalyticsTests(BotTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.database.set_user_language(101, "Aibek", "ru")
        await self.database.set_user_language(202, "Aibek", "ky")
        self.product_id = await self.database.add_product("Машина", 200)

    async def order(self, name="Машина", price=200, when=NOW, author=101, kind="photo") -> int:
        order_id = await self.database.add_order(
            description="Fixture description",
            product_id=self.product_id, product_name=name, price=price,
            created_by=author, created_by_name=f"User {author}",
            receipt_file_id=f"receipt-{kind}", receipt_file_unique_id="unique", receipt_type=kind,
            receipt_file_name="receipt.pdf" if kind == "document" else None,
        )
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("UPDATE orders SET created_at = ? WHERE id = ?", (when.isoformat(), order_id))
            await connection.commit()
        return order_id

    async def result(self, mode, period="all", user_id=101):
        await self.click(AnalyticsPeriodCallback(mode=mode, period=period).pack(), user_id)

    async def click(self, data: str, user_id=101) -> None:
        with patch("bot.handlers.analytics.make_period", side_effect=lambda key, tz: make_period(key, tz, NOW)):
            await super().click(data, user_id)

    def list_order_ids(self):
        ids = []
        for message in self.sent_messages():
            keyboard = message.reply_markup
            if keyboard is not None and hasattr(keyboard, "inline_keyboard"):
                for row in keyboard.inline_keyboard:
                    for button in row:
                        if button.callback_data.startswith("receipt:"):
                            ids.append(ReceiptCallback.unpack(button.callback_data).order_id)
        return ids

    async def test_period_picker_then_summary_and_four_actions(self) -> None:
        await self.send_message(t("menu_analytics", "ru"))
        self.assertEqual(self.sent_messages()[-1].text, t("choose_period", "ru"))
        keyboard = self.sent_messages()[-1].reply_markup.inline_keyboard
        periods = [PeriodChoiceCallback.unpack(button.callback_data).period for row in keyboard for button in row]
        self.assertEqual(periods, ["t", "d7", "d30", "custom", "all"])
        await self.click(PeriodChoiceCallback(period="d7").pack())
        actions = self.displayed_messages()[-1].reply_markup.inline_keyboard
        self.assertEqual([len(row) for row in actions], [2, 1, 1, 1])
        self.assertEqual([AnalyticsPeriodCallback.unpack(b.callback_data).mode for row in actions[:3] for b in row],
                         ["top", "chart", "orders", "word"])

    async def test_start_boundary_seconds_and_microseconds_and_future_rows(self) -> None:
        start = datetime(2026, 10, 12, 18, tzinfo=timezone.utc)
        await self.order(price=100, when=start - timedelta(microseconds=1))
        await self.order(price=200, when=start)
        await self.order(price=300, when=start + timedelta(microseconds=1))
        await self.order(price=400, when=NOW)
        await self.order(price=500, when=NOW + timedelta(microseconds=1))
        period = make_period("1", TZ, NOW)
        summary = await self.database.get_order_summary(period)
        self.assertEqual((summary.count, summary.total), (3, 900))
        page = await self.database.get_orders_page(start=period.start, end=period.end)
        self.assertEqual((page.total, len(page.orders)), (3, 3))
        await self.result("summary", "1")
        self.assertIn("Заказов: 3\nСумма: 900 сом", self.displayed_messages()[-1].text)

    async def test_every_period_filters_correct_calendar_day(self) -> None:
        # Noon on each local date avoids accidental boundary overlap.
        for age in (0, 1, 2, 3, 6, 7, 9, 10, 19, 20, 29, 30, 59, 60, 89, 90, 200):
            await self.order(when=NOW - timedelta(days=age))
        expected = {"1": 1, "3": 3, "7": 5, "10": 7, "20": 9, "30": 11, "60": 13, "90": 15, "all": 17}
        for key, count in expected.items():
            summary = await self.database.get_order_summary(make_period(key, TZ, NOW))
            self.assertEqual(summary.count, count, key)

    async def test_deleted_rows_excluded_from_all_aggregates_list_and_receipts(self) -> None:
        kept = await self.order(price=200)
        deleted = await self.order(name="Deleted", price=900)
        await self.database.soft_delete_order(deleted, 202)
        period = make_period("all", TZ, NOW)
        self.assertEqual((await self.database.get_order_summary(period)).total, 200)
        self.assertEqual([row.name for row in await self.database.get_top_products(period)], ["Машина"])
        self.assertEqual(sum(b.total for b in await self.database.get_chart_buckets(period, TZ, False)), 200)
        await self.result("orders")
        self.assertEqual(self.list_order_ids(), [kept])
        await self.click(ReceiptCallback(order_id=deleted).pack())
        self.assertEqual(self.session.calls[-1].text, t("order_unavailable", "ru"))
        self.assertFalse(any(isinstance(call, (SendPhoto, SendDocument)) for call in self.session.calls))

    async def test_top_all_products_count_then_sum_and_snapshot_names(self) -> None:
        for name, prices in (("Машина", [200, 200, 200]), ("Үй", [500, 500]), ("Авто", [300, 300]), ("A", [50]), ("B", [40]), ("C", [30])):
            for price in prices:
                await self.order(name=name, price=price)
        await self.database.update_product_name(self.product_id, "Renamed")
        await self.database.soft_delete_product(self.product_id)
        top = await self.database.get_top_products(make_period("all", TZ, NOW))
        self.assertEqual([item.name for item in top], ["Машина", "Үй", "Авто", "A", "B", "C"])
        await self.result("top")
        self.assertIn("1. Машина: 3 раз, 600 сом", self.displayed_messages()[-1].text)
        self.assertIn("5. B: 1 раз, 40 сом", self.displayed_messages()[-1].text)
        self.assertNotIn("Renamed", self.displayed_messages()[-1].text)

    async def test_exact_top_example(self) -> None:
        for _ in range(15):
            await self.order()
        await self.result("top")
        self.assertIn("1. Машина: 15 раз, 3 000 сом", self.displayed_messages()[-1].text)

    async def test_all_empty_views_send_only_localized_no_orders(self) -> None:
        for user_id, lang in ((101, "ru"), (202, "ky")):
            for mode in ("summary", "top", "chart", "orders"):
                self.session.calls.clear()
                await self.result(mode, "7", user_id)
                self.assertIn(t("no_orders", lang), self.displayed_messages()[-1].text)
                self.assertFalse(any(isinstance(call, (SendPhoto, SendDocument)) for call in self.session.calls))

    async def test_daily_and_weekly_aggregation_use_local_days_not_utc(self) -> None:
        await self.order(price=100, when=datetime(2026, 10, 11, 17, 59, tzinfo=timezone.utc))
        await self.order(price=200, when=datetime(2026, 10, 11, 18, tzinfo=timezone.utc))
        await self.order(price=300, when=datetime(2026, 10, 12, 18, tzinfo=timezone.utc))
        period = make_period("7", TZ, NOW)
        daily = await self.database.get_chart_buckets(period, TZ, False)
        self.assertEqual([(b.day, b.total) for b in daily], [(date(2026, 10, 11), 100), (date(2026, 10, 12), 200), (date(2026, 10, 13), 300)])
        weekly = await self.database.get_chart_buckets(make_period("60", TZ, NOW), TZ, True)
        self.assertEqual([(b.day, b.total) for b in weekly], [(date(2026, 10, 5), 100), (date(2026, 10, 12), 500)])

    async def test_chart_png_sent_as_photo_and_figure_closed_after_send(self) -> None:
        await self.order()
        baseline = plt.get_fignums()
        original = self.session.make_request

        async def observe(bot, method, timeout=None):
            if isinstance(method, SendPhoto):
                self.assertEqual(len(plt.get_fignums()), len(baseline) + 1)
            return await original(bot, method, timeout)

        with patch.object(self.session, "make_request", side_effect=observe):
            await self.result("chart", "7")
        photo = next(call for call in self.session.calls if isinstance(call, SendPhoto))
        self.assertIsInstance(photo.photo, BufferedInputFile)
        self.assertTrue(photo.photo.data.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(photo.photo.data)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 600)
        self.assertIn("Дни", photo.caption)
        self.assertEqual(plt.get_fignums(), baseline)
        await self.result("chart", "60", 202)
        self.assertIn("Апталар", self.session.calls[-1].caption)
        self.assertEqual(plt.get_fignums(), baseline)

    async def test_order_list_pagination_keeps_period_and_shows_snapshot_format(self) -> None:
        old = await self.order(when=NOW - timedelta(days=40))
        ids = [await self.order(author=101 if i % 2 else 202) for i in range(12)]
        await self.result("orders", "7")
        self.assertEqual(self.list_order_ids(), ids[::-1][:10])
        self.assertNotIn(old, self.list_order_ids())
        self.assertEqual(self.sent_messages()[0].text, "<b>1. Машина — 200 сом</b>\nFixture description\n<i>12:00 · 13.10.2026 · User 101</i>")
        navigation = self.sent_messages()[-1].reply_markup.inline_keyboard[0][0]
        payload = AnalyticsPeriodCallback.unpack(navigation.callback_data)
        self.assertEqual((payload.period, payload.anchor, payload.page), ("d7", make_period("7", TZ, NOW).anchor, 1))
        # Add a later order after page 1 was displayed; the fixed end excludes it.
        await self.order(when=NOW + timedelta(hours=1))
        self.session.calls.clear()
        await self.click(payload.pack())
        self.assertEqual(self.list_order_ids(), ids[::-1][10:])
        previous = self.sent_messages()[-1].reply_markup.inline_keyboard[0][0]
        self.assertEqual(previous.text, "◀")

    async def test_receipt_delivery_photo_document_and_kyrgyz_dates(self) -> None:
        photo = await self.order()
        document = await self.order(kind="document")
        await self.click(ReceiptCallback(order_id=photo).pack())
        self.assertIsInstance(self.session.calls[-1], SendPhoto)
        self.assertEqual(self.session.calls[-1].photo, "receipt-photo")
        await self.click(ReceiptCallback(order_id=document).pack())
        self.assertIsInstance(self.session.calls[-1], SendDocument)
        self.assertEqual(self.session.calls[-1].document, "receipt-document")
        await self.result("orders", "all", 202)
        self.assertTrue(any("12:00 · 13.10.2026" in m.text for m in self.sent_messages()))

    async def test_last_page_clamps_after_deletion_without_leaking_other_period(self) -> None:
        ids = [await self.order() for _ in range(11)]
        await self.order(when=NOW - timedelta(days=20))
        await self.database.soft_delete_order(ids[0], 101)
        payload = AnalyticsPageCallback(period="1", anchor=make_period("1", TZ, NOW).anchor, page=1)
        await self.click(payload.pack())
        self.assertEqual(len(self.list_order_ids()), 10)
        self.assertFalse(any(m.text == t("pagination", "ru") for m in self.sent_messages()))
        self.assertTrue(self.sent_messages()[0].text.startswith("<b>1."))

    async def test_whitelist_blocks_every_analytics_callback_and_receipt(self) -> None:
        order_id = await self.order()
        await self.send_message(t("menu_analytics", "ru"), 999)
        for data in ("analytics:menu", AnalyticsKindCallback(mode="summary").pack(), AnalyticsPeriodCallback(mode="chart", period="all").pack(), AnalyticsPageCallback(period="1", anchor=make_period("1", TZ, NOW).anchor, page=0).pack(), ReceiptCallback(order_id=order_id).pack()):
            await self.click(data, 999)
        self.assertEqual(self.session.calls, [])

    async def test_analytics_navigation_cancels_pending_order_and_confirmation(self) -> None:
        await self.click(ProductCallback(action="select", product_id=self.product_id).pack())
        await self.send_message(t("menu_analytics", "ru"))
        state = self.dispatcher.fsm.get_context(bot=self.bot, chat_id=101, user_id=101)
        self.assertIsNone(await state.get_state())
        self.assertEqual(await state.get_data(), {})
        await self.click("analytics:menu")
        self.assertEqual(self.sent_messages()[-1].text, t("choose_period", "ru"))

    async def test_invalid_and_future_payloads_are_rejected_without_queries(self) -> None:
        for data in ("analytics:excel", "analytics_period:summary:365", "analytics_page:1:-1:0", "receipt:-1"):
            await self.click(data)
            self.assertEqual(self.session.calls[-1].text, t("invalid_button", "ru"))
        await self.click(AnalyticsPageCallback(period="all", anchor=253402300799999999, page=0).pack())
        self.assertEqual(self.session.calls[-1].text, t("invalid_button", "ru"))

    async def test_configured_timezone_used_in_summary_and_order_dates(self) -> None:
        config = replace(self.config, timezone=ZoneInfo("UTC"))
        await self.dispatcher.fsm.close()
        self.dispatcher = create_dispatcher(config, self.database)
        await self.order(when=datetime(2026, 10, 12, 19, tzinfo=timezone.utc))
        await self.result("summary", "1")
        self.assertIn(t("no_orders", "ru"), self.displayed_messages()[-1].text)
        await self.result("orders", "all")
        self.assertTrue(any("19:00 · 12.10.2026" in m.text for m in self.sent_messages()))

    async def test_telegram_receipt_error_has_localized_reply(self) -> None:
        order_id = await self.order()
        original = self.session.make_request

        async def unavailable(bot, method, timeout=None):
            if isinstance(method, SendPhoto):
                raise TelegramBadRequest(method=method, message="invalid file id")
            return await original(bot, method, timeout)

        with patch.object(self.session, "make_request", side_effect=unavailable), self.assertLogs(level="ERROR"):
            await self.click(ReceiptCallback(order_id=order_id).pack())
        self.assertEqual(self.sent_messages()[-1].text, t("receipt_unavailable", "ru"))


class ChartCleanupTests(unittest.TestCase):
    def test_figures_close_on_render_or_send_failure_and_titles_are_localized(self) -> None:
        baseline = plt.get_fignums()
        series = ChartSeries([ChartBucket(date(2026, 10, 13), 200)], False)
        with self.assertRaises(RuntimeError):
            with chart_png(series, "1", "ky"):
                figure = plt.gcf()
                self.assertIn("Заказдардын", figure.axes[0].get_title())
                self.assertEqual(figure.axes[0].get_xlabel(), "Күндөр")
                raise RuntimeError("Simulated send failure")
        self.assertEqual(plt.get_fignums(), baseline)
        with patch("matplotlib.figure.Figure.savefig", side_effect=RuntimeError("Render failure")):
            with self.assertRaises(RuntimeError):
                with chart_png(series, "1", "ru"):
                    pass
        self.assertEqual(plt.get_fignums(), baseline)
