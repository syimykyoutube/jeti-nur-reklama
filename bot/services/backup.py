"""Temporary, consistent SQLite snapshots shared by backup and report export."""

from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from bot.db import Database


@asynccontextmanager
async def database_snapshot(database: Database):
    with TemporaryDirectory(prefix="jeti-nur-db-") as directory:
        snapshot_path = Path(directory) / "snapshot.db"
        await database.backup_to(snapshot_path)
        yield Database(snapshot_path)
