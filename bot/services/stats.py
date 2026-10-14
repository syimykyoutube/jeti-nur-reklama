"""Timezone-aware analytics periods and chart bucket preparation."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from bot.i18n import t


PERIOD_KEYS = ("1", "3", "7", "10", "20", "30", "60", "90", "all")
ANALYTICS_MODES = ("summary", "top", "chart", "orders", "word")


@dataclass(frozen=True, slots=True)
class Period:
    key: str
    start: datetime | None
    end: datetime

    @property
    def anchor(self) -> int:
        return int(self.end.timestamp() * 1_000_000)


@dataclass(frozen=True, slots=True)
class Summary:
    count: int
    total: float
    first_created_at: str | None


@dataclass(frozen=True, slots=True)
class TopProduct:
    name: str
    count: int
    total: float


@dataclass(frozen=True, slots=True)
class ChartBucket:
    day: date
    total: float


@dataclass(frozen=True, slots=True)
class ChartSeries:
    buckets: list[ChartBucket]
    weekly: bool


def make_period(key: str, tz: ZoneInfo, now: datetime | None = None) -> Period:
    if key != "all" and (not key.isascii() or not key.isdigit() or not 1 <= int(key) <= 99 or str(int(key)) != key):
        raise ValueError("Unsupported analytics period")
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Analytics time must include a timezone")
    end = now.astimezone(timezone.utc)
    if key == "all":
        return Period(key, None, end)
    first_day = now.astimezone(tz).date() - timedelta(days=int(key) - 1)
    start = datetime.combine(first_day, time.min, tzinfo=tz).astimezone(timezone.utc)
    return Period(key, start, end)


def period_from_anchor(key: str, anchor: int, tz: ZoneInfo) -> Period:
    seconds, micros = divmod(anchor, 1_000_000)
    end = datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=micros)
    return make_period(key, tz, end)


def period_label(key: str, lang: str) -> str:
    if key == "all":
        return t("period_all", lang)
    if key == "1":
        return t("period_today", lang)
    return t("period_days", lang, days=int(key))


def chart_weekly(period: Period, first_created_at: str, tz: ZoneInfo) -> bool:
    if period.key != "all":
        return int(period.key) > 31
    first_day = datetime.fromisoformat(first_created_at).astimezone(tz).date()
    return (period.end.astimezone(tz).date() - first_day).days + 1 > 31


def bucket_date(timestamp: str, tz: ZoneInfo, weekly: bool) -> date:
    day = datetime.fromisoformat(timestamp).astimezone(tz).date()
    return day - timedelta(days=day.weekday()) if weekly else day


def fill_chart_buckets(rows: list[ChartBucket], period: Period, tz: ZoneInfo, weekly: bool) -> ChartSeries:
    if not rows:
        return ChartSeries([], weekly)
    first = period.start.astimezone(tz).date() if period.start else min(row.day for row in rows)
    last = period.end.astimezone(tz).date()
    if weekly:
        first -= timedelta(days=first.weekday())
        last -= timedelta(days=last.weekday())
    totals = {row.day: row.total for row in rows}
    buckets = []
    step = timedelta(days=7 if weekly else 1)
    while first <= last:
        buckets.append(ChartBucket(first, totals.get(first, 0.0)))
        first += step
    return ChartSeries(buckets, weekly)


def period_token(key: str) -> str:
    return "all" if key == "all" else ("t" if key == "1" else f"d{key}")


def period_key(token: str) -> str:
    return "all" if token == "all" else ("1" if token == "t" else token.removeprefix("d"))


def validate_days(text: str | None) -> str:
    if text is None or not text.strip().isascii() or not text.strip().isdigit():
        raise ValueError("Expected an integer number of days")
    days = int(text.strip())
    if not 1 <= days <= 99:
        raise ValueError("Days must be between 1 and 99")
    return str(days)
