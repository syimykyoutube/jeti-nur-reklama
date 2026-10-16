"""Persistent SQLite schema, user preferences, catalog, and order operations."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite

from bot.i18n import SUPPORTED_LANGUAGES
from bot.services.catalog import validate_name, validate_price_amount
from bot.services.orders import validate_description
from bot.services.stats import ChartBucket, Period, Summary, TopProduct, bucket_date


def order_scope(start: datetime | None = None, end: datetime | None = None) -> tuple[str, list[str]]:
    """Bound UTC ISO timestamps; midnight includes both seconds and fractional ISO forms."""
    conditions = [ACTIVE_ORDER_FILTER]
    values = []
    if start is not None:
        if start.tzinfo is None:
            raise ValueError("Start time must include a timezone")
        conditions.append("created_at >= ?")
        values.append(start.astimezone(timezone.utc).isoformat(timespec="seconds"))
    if end is not None:
        if end.tzinfo is None:
            raise ValueError("End time must include a timezone")
        conditions.append("created_at <= ?")
        values.append(end.astimezone(timezone.utc).isoformat(timespec="microseconds"))
    return " AND ".join(conditions), values


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    name: str
    price: float
    is_active: bool
    created_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Product":
        return cls(row["id"], row["name"], row["price"], bool(row["is_active"]), row["created_at"])


@dataclass(frozen=True, slots=True)
class Order:
    id: int
    product_id: int | None
    product_name: str
    price: float
    created_by: int
    created_by_name: str | None
    created_at: str
    receipt_file_id: str
    receipt_file_unique_id: str | None
    receipt_type: str
    receipt_file_name: str | None
    deleted_at: str | None
    deleted_by: int | None
    description: str | None = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Order":
        return cls(**dict(row))


@dataclass(frozen=True, slots=True)
class OrderPage:
    orders: list[Order]
    page: int
    pages: int
    total: int


ORDER_PAGE_SIZE = 10
# Every normal order lookup excludes deleted rows. Audit reads must be explicit.
ACTIVE_ORDER_FILTER = "deleted_at IS NULL"


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    name TEXT,
    lang TEXT NOT NULL DEFAULT 'ky',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    product_name TEXT NOT NULL,
    price REAL NOT NULL,
    created_by INTEGER NOT NULL,
    created_by_name TEXT,
    created_at TEXT NOT NULL,
    receipt_file_id TEXT NOT NULL,
    receipt_file_unique_id TEXT,
    receipt_type TEXT NOT NULL,
    receipt_file_name TEXT,
    deleted_at TEXT,
    deleted_by INTEGER,
    description TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_deleted_at ON orders(deleted_at);
"""


async def init_db(db_path: Path) -> None:
    """Create the database and tables without adding demonstration data."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path, timeout=10) as connection:
        await connection.executescript(SCHEMA)
        # Serialize inspection and ALTER so concurrent initializations are safe too.
        await connection.execute("BEGIN IMMEDIATE")
        async with connection.execute("PRAGMA table_info(orders)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        if "description" not in columns:
            await connection.execute("ALTER TABLE orders ADD COLUMN description TEXT")
        await connection.commit()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def backup_to(self, destination: Path) -> None:
        """Create a consistent standalone copy using SQLite's online backup API."""
        if self.path.resolve() == destination.resolve():
            raise ValueError("Backup destination must differ from the working database")
        if not self.path.is_file():
            raise FileNotFoundError("Working database does not exist")
        if destination.exists():
            raise FileExistsError("Backup destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_uri = self.path.resolve().as_uri() + "?mode=ro"
        async with aiosqlite.connect(source_uri, uri=True, timeout=10) as source:
            async with aiosqlite.connect(destination, timeout=10) as target:
                await source.backup(target, pages=256, sleep=0.05)

    async def get_user_language(self, tg_id: int) -> str | None:
        """No row means the user has not chosen a language yet."""
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            async with connection.execute("SELECT lang FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
                row = await cursor.fetchone()
        return row[0] if row is not None else None

    async def set_user_language(self, tg_id: int, name: str, lang: str) -> None:
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError("Unsupported language")
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            await connection.execute(
                """
                INSERT INTO users (tg_id, name, lang, created_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET name = excluded.name, lang = excluded.lang
                """,
                (tg_id, name, lang, created_at),
            )
            await connection.commit()

    async def list_active_products(self) -> list[Product]:
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute("SELECT * FROM products WHERE is_active = 1 ORDER BY id ASC") as cursor:
                return [Product.from_row(row) for row in await cursor.fetchall()]

    async def get_active_product(self, product_id: int) -> Product | None:
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                "SELECT * FROM products WHERE id = ? AND is_active = 1", (product_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return Product.from_row(row) if row is not None else None

    async def add_product(self, name: str, price: float) -> int:
        name = validate_name(name)
        price = validate_price_amount(price)
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            async with connection.execute(
                "INSERT INTO products (name, price, created_at) VALUES (?, ?, ?)", (name, price, created_at)
            ) as cursor:
                product_id = cursor.lastrowid
            await connection.commit()
        assert product_id is not None
        return product_id

    async def update_product_name(self, product_id: int, name: str) -> bool:
        return await self._update_active_product(product_id, "name", validate_name(name))

    async def update_product_price(self, product_id: int, price: float) -> bool:
        return await self._update_active_product(product_id, "price", validate_price_amount(price))

    async def soft_delete_product(self, product_id: int) -> bool:
        return await self._update_active_product(product_id, "is_active", 0)

    async def _update_active_product(self, product_id: int, column: str, value: str | float | int) -> bool:
        if column not in {"name", "price", "is_active"}:
            raise ValueError("Unsupported product field")
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            async with connection.execute(
                f"UPDATE products SET {column} = ? WHERE id = ? AND is_active = 1", (value, product_id)
            ) as cursor:
                changed = cursor.rowcount > 0
            await connection.commit()
        return changed

    async def add_order(
        self, *, product_id: int, product_name: str, price: float,
        created_by: int, created_by_name: str, receipt_file_id: str,
        receipt_file_unique_id: str | None, receipt_type: str,
        receipt_file_name: str | None = None,
        description: str | None = None,
    ) -> int:
        """Save a quoted snapshot only with both a receipt and a description."""
        if receipt_type not in {"photo", "document"} or not receipt_file_id:
            raise ValueError("A photo or document receipt is required")
        product_name = validate_name(product_name)
        price = validate_price_amount(price)
        description = validate_description(description)
        created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            async with connection.execute(
                """
                INSERT INTO orders (
                    product_id, product_name, price, created_by, created_by_name, created_at,
                    receipt_file_id, receipt_file_unique_id, receipt_type, receipt_file_name, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, product_name, price, created_by, created_by_name, created_at,
                 receipt_file_id, receipt_file_unique_id, receipt_type,
                 receipt_file_name if receipt_type == "document" else None, description),
            ) as cursor:
                order_id = cursor.lastrowid
            await connection.commit()
        assert order_id is not None
        return order_id

    async def get_active_order(self, order_id: int) -> Order | None:
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                f"SELECT * FROM orders WHERE id = ? AND {ACTIVE_ORDER_FILTER}", (order_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return Order.from_row(row) if row is not None else None

    async def get_order_for_receipt_link(self, order_id: int) -> Order | None:
        """Only for deep links: distinguish a deleted order without delivering its receipt."""
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cursor:
                row = await cursor.fetchone()
                return Order.from_row(row) if row is not None else None

    async def get_orders_page(
        self, page: int = 0, *, start: datetime | None = None, end: datetime | None = None,
    ) -> OrderPage:
        """Fetch ten active orders from all users, newest first, in one read snapshot."""
        scope, values = order_scope(start, end)
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN")
            async with connection.execute(f"SELECT COUNT(*) FROM orders WHERE {scope}", values) as cursor:
                total = (await cursor.fetchone())[0]
            pages = max(1, (total + ORDER_PAGE_SIZE - 1) // ORDER_PAGE_SIZE)
            page = max(0, min(page, pages - 1))
            async with connection.execute(
                f"SELECT * FROM orders WHERE {scope} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (*values, ORDER_PAGE_SIZE, page * ORDER_PAGE_SIZE),
            ) as cursor:
                orders = [Order.from_row(row) for row in await cursor.fetchall()]
            await connection.commit()
        return OrderPage(orders=orders, page=page, pages=pages, total=total)

    async def get_order_summary(self, period: Period) -> Summary:
        scope, values = order_scope(period.start, period.end)
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            async with connection.execute(
                f"SELECT COUNT(*), COALESCE(SUM(price), 0), MIN(created_at) FROM orders WHERE {scope}", values,
            ) as cursor:
                count, total, first = await cursor.fetchone()
        return Summary(count, total, first)

    async def get_top_products(self, period: Period) -> list[TopProduct]:
        scope, values = order_scope(period.start, period.end)
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            async with connection.execute(
                "SELECT product_name, COUNT(*) AS quantity, SUM(price) AS total "
                f"FROM orders WHERE {scope} GROUP BY product_name "
                "ORDER BY quantity DESC, total DESC, product_name ASC", values,
            ) as cursor:
                return [TopProduct(*row) for row in await cursor.fetchall()]

    async def get_chart_buckets(self, period: Period, tz: ZoneInfo, weekly: bool) -> list[ChartBucket]:
        scope, values = order_scope(period.start, period.end)
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            await connection.create_function(
                "chart_bucket", 1, lambda value: bucket_date(value, tz, weekly).isoformat(), deterministic=True,
            )
            async with connection.execute(
                f"SELECT chart_bucket(created_at) AS bucket, SUM(price) FROM orders WHERE {scope} "
                "GROUP BY bucket ORDER BY bucket ASC", values,
            ) as cursor:
                return [ChartBucket(date.fromisoformat(day), total) for day, total in await cursor.fetchall()]

    async def soft_delete_order(self, order_id: int, deleted_by: int) -> bool:
        """Preserve the order and receipt; never overwrite an earlier deletion."""
        deleted_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        async with aiosqlite.connect(self.path, timeout=10) as connection:
            async with connection.execute(
                f"UPDATE orders SET deleted_at = ?, deleted_by = ? WHERE id = ? AND {ACTIVE_ORDER_FILTER}",
                (deleted_at, deleted_by, order_id),
            ) as cursor:
                changed = cursor.rowcount > 0
            await connection.commit()
        return changed
