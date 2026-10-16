"""Environment configuration and validation."""

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import load_dotenv

from bot.i18n import SUPPORTED_LANGUAGES


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(ValueError):
    """Configuration cannot be used to start the bot."""


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str = field(repr=False)
    allowed_user_ids: frozenset[int]
    db_path: Path
    timezone: ZoneInfo
    default_lang: str = "ky"
    access_denied_reply: bool = False
    bot_username: str | None = None


def load_config(env_file: Path | None = None) -> Config:
    """Load .env from the project root; environment variables take priority."""
    load_dotenv(env_file if env_file is not None else PROJECT_ROOT / ".env", override=False)

    token = os.getenv("BOT_TOKEN", "").strip()
    try:
        validate_token(token)
    except TokenValidationError:
        raise ConfigError("BOT_TOKEN is missing or malformed. Set it in .env.") from None

    raw_ids = os.getenv("ALLOWED_USER_IDS", "").strip()
    try:
        parts = [part.strip() for part in raw_ids.split(",")] if raw_ids else []
        if any(not part.isascii() or not part.isdecimal() for part in parts):
            raise ValueError
        allowed_ids = frozenset(int(part) for part in parts)
        if any(user_id <= 0 for user_id in allowed_ids):
            raise ValueError
    except ValueError:
        raise ConfigError("ALLOWED_USER_IDS must contain positive Telegram IDs separated by commas.") from None

    default_lang = os.getenv("DEFAULT_LANG", "ky").strip().lower()
    if default_lang not in SUPPORTED_LANGUAGES:
        raise ConfigError("DEFAULT_LANG must be ru or ky.")

    timezone_name = (os.getenv("BOT_TZ", "").strip()
                     or os.getenv("TZ", "").strip()
                     or "Asia/Bishkek")
    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError("BOT_TZ (or fallback TZ) must be a valid IANA timezone, for example Asia/Bishkek.") from None

    raw_path = os.getenv("DB_PATH", "data/bot.db").strip()
    if not raw_path or raw_path == ":memory:":
        raise ConfigError("DB_PATH must point to a persistent SQLite file.")
    db_path = Path(raw_path).expanduser()
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    if db_path.is_dir():
        raise ConfigError("DB_PATH must point to a file, not a directory.")

    raw_reply = os.getenv("ACCESS_DENIED_REPLY", "false").strip().lower()
    if raw_reply not in {"true", "false"}:
        raise ConfigError("ACCESS_DENIED_REPLY must be true or false.")

    username = os.getenv("BOT_USERNAME", "").strip().removeprefix("@") or None
    if username is not None and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) is None:
        raise ConfigError("BOT_USERNAME must be a Telegram username (5–32 letters, digits or underscores).")

    return Config(
        bot_token=token,
        allowed_user_ids=allowed_ids,
        db_path=db_path,
        timezone=timezone,
        default_lang=default_lang,
        access_denied_reply=raw_reply == "true",
        bot_username=username,
    )
