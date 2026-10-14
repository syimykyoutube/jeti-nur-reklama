"""All user-facing text and localized display formats."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


SUPPORTED_LANGUAGES = ("ru", "ky")

TEXTS: dict[str, dict[str, str]] = {
    "choose_lang": {
        "ru": "Выберите язык",
        "ky": "Тилди тандаңыз"
    },
    "language_ru": {
        "ru": "Русский",
        "ky": "Русский"
    },
    "language_ky": {
        "ru": "Кыргызча",
        "ky": "Кыргызча"
    },
    "language_saved": {
        "ru": "Язык сохранён ✅",
        "ky": "Тил сакталды ✅"
    },
    "main_menu": {
        "ru": "Главное меню\n/edit — Редактировать каталог",
        "ky": "Башкы меню\n/edit — Каталогду өзгөртүү"
    },
    "menu_catalog": {
        "ru": "📋 Каталог",
        "ky": "📋 Каталог"
    },
    "menu_analytics": {
        "ru": "📊 Аналитика",
        "ky": "📊 Аналитика"
    },
    "menu_delete_order": {
        "ru": "🗑 Удалить заказ",
        "ky": "🗑 Заказды өчүрүү"
    },
    "menu_language": {
        "ru": "🌐 Язык / Тил",
        "ky": "🌐 Тил / Язык"
    },
    "btn_menu": {
        "ru": "Меню",
        "ky": "Меню"
    },
    "my_id": {
        "ru": "Ваш Telegram ID: {user_id}",
        "ky": "Сиздин Telegram ID: {user_id}"
    },
    "access_denied": {
        "ru": "Нет доступа",
        "ky": "Кирүүгө уруксат жок"
    },
    "catalog_empty": {
        "ru": "Каталог пуст",
        "ky": "Каталог бош"
    },
    "catalog_edit_hint": {
        "ru": "Чтобы добавить карточки, отправьте /edit",
        "ky": "Карточка кошуу үчүн /edit командасын жөнөт"
    },
    "catalog_edit_mode": {
        "ru": "✏️ Режим редактирования",
        "ky": "✏️ Өзгөртүү режими"
    },
    "command_edit": {
        "ru": "Редактировать каталог",
        "ky": "Каталогду өзгөртүү"
    },
    "catalog_actions": {
        "ru": "Чтобы добавить карточку, нажмите кнопку ниже",
        "ky": "Жаңы карточка кошуу үчүн ылдыйдагы баскычты бас"
    },
    "product_card": {
        "ru": "<b>{name} — {price}</b>",
        "ky": "<b>{name} — {price}</b>"
    },
    "btn_select": {
        "ru": "✅ Выбрать",
        "ky": "✅ Тандоо"
    },
    "btn_edit": {
        "ru": "✏️",
        "ky": "✏️"
    },
    "btn_delete": {
        "ru": "🗑",
        "ky": "🗑"
    },
    "btn_add": {
        "ru": "➕ Добавить карточку",
        "ky": "➕ Карточка кошуу"
    },
    "btn_cancel": {
        "ru": "❌ Отмена",
        "ky": "❌ Жокко чыгаруу"
    },
    "btn_back": {
        "ru": "❌ Назад",
        "ky": "❌ Артка"
    },
    "ask_receipt": {
        "ru": "{name} — {price}. Отправьте чек.",
        "ky": "{name} — {price}. Чекти жөнөт."
    },
    "receipt_wrong": {
        "ru": "Отправьте чек как фото или документ",
        "ky": "Чекти сүрөт же документ катары жөнөт"
    },
    "order_saved": {
        "ru": "Заказ сохранён ✅",
        "ky": "Заказ сакталды ✅"
    },
    "order_deleted": {
        "ru": "Заказ удалён",
        "ky": "Заказ өчүрүлдү"
    },
    "no_orders_to_delete": {
        "ru": "Заказов нет",
        "ky": "Заказ жок"
    },
    "order_unavailable": {
        "ru": "Заказ уже удалён или не найден. Откройте список снова.",
        "ky": "Заказ өчүрүлгөн же табылган жок. Тизмени кайра ачыңыз."
    },
    "order_dialog_expired": {
        "ru": "Подтверждение устарело. Выберите заказ в списке снова.",
        "ky": "Ырастоо эскирди. Тизмеден заказды кайра тандаңыз."
    },
    "page_previous": {
        "ru": "◀",
        "ky": "◀"
    },
    "page_next": {
        "ru": "▶",
        "ky": "▶"
    },
    "analytics_top": {
        "ru": "🏆 Топ",
        "ky": "🏆 Топ"
    },
    "analytics_chart": {
        "ru": "📈 График",
        "ky": "📈 График"
    },
    "analytics_orders": {
        "ru": "🧾 Список с чеками",
        "ky": "🧾 Тизме чек менен"
    },
    "analytics_word": {
        "ru": "📄 Word",
        "ky": "📄 Word"
    },
    "report_title": {
        "ru": "Отчёт по заказам",
        "ky": "Заказдар боюнча отчёт"
    },
    "report_datetime": {
        "ru": "{day} {month} {year}, {time}",
        "ky": "{day} {month} {year}, {time}"
    },
    "report_top": {
        "ru": "Топ 5 по количеству заказов",
        "ky": "Заказдардын саны боюнча топ 5"
    },
    "report_chart": {
        "ru": "График суммы заказов",
        "ky": "Заказдардын суммасынын графиги"
    },
    "report_orders": {
        "ru": "Список заказов",
        "ky": "Заказдардын тизмеси"
    },
    "report_product": {
        "ru": "Название",
        "ky": "Аты"
    },
    "report_quantity": {
        "ru": "Количество",
        "ky": "Саны"
    },
    "report_amount": {
        "ru": "Сумма",
        "ky": "Сумма"
    },
    "report_number": {
        "ru": "№",
        "ky": "№"
    },
    "report_date_column": {
        "ru": "Дата и время",
        "ky": "Убакыт"
    },
    "report_order_product": {
        "ru": "Продукт",
        "ky": "Продукт"
    },
    "report_author": {
        "ru": "Кто внёс",
        "ky": "Ким киргизди"
    },
    "report_building": {
        "ru": "Готовлю Word-отчёт…",
        "ky": "Word отчёт даярдалууда…"
    },
    "report_failed": {
        "ru": "Не удалось создать отчёт. Попробуйте ещё раз.",
        "ky": "Отчёт түзүү мүмкүн болгон жок. Кайра аракет кылыңыз."
    },
    "backup_building": {
        "ru": "Создаю резервную копию базы…",
        "ky": "Базанын камдык көчүрмөсү түзүлүүдө…"
    },
    "backup_ready": {
        "ru": "Резервная копия базы данных",
        "ky": "Базанын камдык көчүрмөсү"
    },
    "backup_failed": {
        "ru": "Не удалось создать резервную копию. Попробуйте ещё раз.",
        "ky": "Камдык көчүрмө түзүү мүмкүн болгон жок. Кайра аракет кылыңыз."
    },
    "command_backup": {
        "ru": "Скачать резервную копию базы",
        "ky": "Базанын камдык көчүрмөсүн алуу"
    },
    "choose_period": {
        "ru": "Выберите период",
        "ky": "Убакытты тандаңыз"
    },
    "period_1": {
        "ru": "1 день (сегодня)",
        "ky": "1 күн (бүгүн)"
    },
    "period_3": {
        "ru": "3 дня",
        "ky": "3 күн"
    },
    "period_7": {
        "ru": "7 дней",
        "ky": "7 күн"
    },
    "period_10": {
        "ru": "10 дней",
        "ky": "10 күн"
    },
    "period_20": {
        "ru": "20 дней",
        "ky": "20 күн"
    },
    "period_30": {
        "ru": "30 дней",
        "ky": "30 күн"
    },
    "period_60": {
        "ru": "2 мес. (60 дней)",
        "ky": "2 ай (60 күн)"
    },
    "period_90": {
        "ru": "3 мес. (90 дней)",
        "ky": "3 ай (90 күн)"
    },
    "period_all": {
        "ru": "всё время",
        "ky": "бардык убакыт"
    },
    "period_heading": {
        "ru": "Период: {period}",
        "ky": "Убакыт: {period}"
    },
    "summary_result": {
        "ru": "Период: {period}\nЗаказов: {count}\nСумма: {total}",
        "ky": "Убакыт: {period}\nЗаказ: {count}\nСумма: {total}"
    },
    "top_line": {
        "ru": "{rank}. {name}: {count} раз, {total}",
        "ky": "{rank}. {name}: {count} жолу, {total}"
    },
    "no_orders": {
        "ru": "За этот период заказов нет",
        "ky": "Бул убакытта заказ жок"
    },
    "btn_receipt": {
        "ru": "🧾 Чек",
        "ky": "🧾 Чек"
    },
    "receipt_unavailable": {
        "ru": "Не удалось отправить чек. Попробуйте ещё раз позже.",
        "ky": "Чекти жөнөтүү мүмкүн болгон жок. Кийин кайра аракет кылыңыз."
    },
    "chart_title": {
        "ru": "Сумма заказов — {period}",
        "ky": "Заказдардын суммасы — {period}"
    },
    "chart_days": {
        "ru": "Дни",
        "ky": "Күндөр"
    },
    "chart_weeks": {
        "ru": "Недели (понедельник — воскресенье)",
        "ky": "Апталар (дүйшөмбү — жекшемби)"
    },
    "chart_amount": {
        "ru": "Сумма (сом)",
        "ky": "Сумма (сом)"
    },
    "chart_caption": {
        "ru": "Период: {period}. {grouping}.",
        "ky": "Убакыт: {period}. {grouping}."
    },
    "ask_name": {
        "ru": "Введите название",
        "ky": "Атын жаз"
    },
    "ask_price": {
        "ru": "Введите цену (сом)",
        "ky": "Баасын жаз (сом)"
    },
    "invalid_name": {
        "ru": "Введите название текстом: от 1 до 60 символов.",
        "ky": "Атын текст менен жазыңыз: 1ден 60ка чейин символ."
    },
    "invalid_price": {
        "ru": "Введите число больше 0 и меньше 1 000 000. Для дробной цены используйте точку или запятую.",
        "ky": "0дөн чоң жана 1 000 000дон кичине сан жазыңыз. Ондук баа үчүн чекит же үтүр колдонуңуз."
    },
    "added": {
        "ru": "Добавлено ✅",
        "ky": "Кошулду ✅"
    },
    "updated": {
        "ru": "Изменено ✅",
        "ky": "Өзгөртүлдү ✅"
    },
    "cancelled": {
        "ru": "Отменено",
        "ky": "Жокко чыгарылды"
    },
    "delete_cancelled": {
        "ru": "Удаление отменено",
        "ky": "Жокко чыгарылды"
    },
    "edit_field": {
        "ru": "Что изменить?",
        "ky": "Эмнени өзгөртүү керек?"
    },
    "field_name": {
        "ru": "Название",
        "ky": "Аты"
    },
    "field_price": {
        "ru": "Цена",
        "ky": "Баасы"
    },
    "confirm_delete": {
        "ru": "Точно удалить?",
        "ky": "Чын эле өчүрөсүңбү?"
    },
    "confirm_product_delete": {
        "ru": "{card}\n\n{question}",
        "ky": "{card}\n\n{question}"
    },
    "yes": {
        "ru": "Да",
        "ky": "Ооба"
    },
    "no": {
        "ru": "Нет",
        "ky": "Жок"
    },
    "product_deleted": {
        "ru": "Продукт удалён",
        "ky": "Продукт өчүрүлдү"
    },
    "product_unavailable": {
        "ru": "Продукт уже удалён или не найден. Откройте каталог снова.",
        "ky": "Продукт өчүрүлгөн же табылган жок. Каталогду кайра ачыңыз."
    },
    "form_expired": {
        "ru": "Этот диалог уже завершён. Откройте каталог снова.",
        "ky": "Бул диалог аяктаган. Каталогду кайра ачыңыз."
    },
    "choose_edit_field": {
        "ru": "Выберите «Название» или «Цена» кнопкой ниже.",
        "ky": "Төмөнкү баскыч менен «Аты» же «Баасы» тандаңыз."
    },
    "choose_confirmation": {
        "ru": "Подтвердите удаление кнопкой «Да» или отмените.",
        "ky": "«Ооба» баскычы менен өчүрүүнү ырастаңыз же жокко чыгарыңыз."
    },
    "command_cancel": {
        "ru": "Отменить действие",
        "ky": "Аракетти жокко чыгаруу"
    },
    "invalid_button": {
        "ru": "Кнопка устарела. Отправьте /start.",
        "ky": "Баскыч эскирди. /start командасын жөнөтүңүз."
    },
    "unexpected_error": {
        "ru": "Произошла ошибка. Попробуйте ещё раз или отправьте /start.",
        "ky": "Ката чыкты. Кайра аракет кылыңыз же /start командасын жөнөтүңүз."
    },
    "command_start": {
        "ru": "Начать / главное меню",
        "ky": "Баштоо / башкы меню"
    },
    "command_menu": {
        "ru": "Главное меню",
        "ky": "Башкы меню"
    },
    "command_language": {
        "ru": "Выбрать язык",
        "ky": "Тилди тандоо"
    },
    "command_myid": {
        "ru": "Узнать свой Telegram ID",
        "ky": "Telegram ID билүү"
    },
    "currency": {
        "ru": "сом",
        "ky": "сом"
    },
    "delete_order_button": {
        "ru": "🗑 Удалить",
        "ky": "🗑 Өчүрүү"
    },
    "order_card": {
        "ru": "<b>{number}. {name} — {price}</b>\n<i>{date} · {author}</i>",
        "ky": "<b>{number}. {name} — {price}</b>\n<i>{date} · {author}</i>"
    },
    "pagination": {
        "ru": "◀ ▶",
        "ky": "◀ ▶"
    },
    "period_today_button": {
        "ru": "Сегодня",
        "ky": "Бүгүн"
    },
    "period_all_button": {
        "ru": "За всё время",
        "ky": "Жалпы"
    },
    "period_custom_button": {
        "ru": "✏️ Ввести число",
        "ky": "✏️ Сан киргиз"
    },
    "ask_days": {
        "ru": "Введите число дней (1-99)",
        "ky": "Күндү жаз (1-99)"
    },
    "period_today": {
        "ru": "сегодня",
        "ky": "бүгүн"
    },
    "period_days": {
        "ru": "последние {days} дней",
        "ky": "акыркы {days} күн"
    },
    "change_period": {
        "ru": "🔄 Сменить период",
        "ky": "🔄 Убакытты өзгөртүү"
    },
    "command_deleteorder": {
        "ru": "Удалить заказ",
        "ky": "Заказды өчүрүү"
    },
    "report_subtitle": {
        "ru": "Период: {period} · Сформирован: {date}",
        "ky": "Убакыт: {period} · Түзүлгөн: {date}"
    },
    "report_count_label": {
        "ru": "Количество заказов",
        "ky": "Заказдын саны"
    },
    "report_total_label": {
        "ru": "Общая сумма",
        "ky": "Жалпы сумма"
    },
    "report_grand_total": {
        "ru": "Итого: {total}",
        "ky": "Жалпы: {total}"
    }
}

MONTHS = {
    "ru": (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ),
    "ky": (
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ),
}


def normalize_language(lang: str | None, default: str = "ky") -> str:
    return lang if lang in SUPPORTED_LANGUAGES else default


def t(key: str, lang: str, **values: object) -> str:
    return TEXTS[key][normalize_language(lang)].format(**values)


def variants(key: str) -> tuple[str, ...]:
    """Accept old menu labels after a user changes language."""
    return tuple(dict.fromkeys(TEXTS[key].values()))


def format_datetime(value: datetime, lang: str, tz: ZoneInfo) -> str:
    """Convert aware UTC timestamps to the configured display timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must include timezone information")
    local = value.astimezone(tz)
    return f"{local:%H:%M} · {local:%d.%m.%Y}"


def format_money(value: Decimal | float | int, lang: str) -> str:
    number = Decimal(format(value, ".15g") if isinstance(value, float) else str(value))
    formatted = f"{number:,f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    formatted = formatted.replace(",", " ")
    return f"{formatted} {t('currency', lang)}"
