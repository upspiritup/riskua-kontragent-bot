"""Налаштування з оточення. Єдине місце, де читаються змінні оточення і файл .env."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

# Префікс відділяє змінні нової версії від змінних старого бота в тому самому .env.
PREFIX = "RISKUA_"
DOTENV_PATH = Path(".env")
ENVIRONMENTS = frozenset({"local", "test", "production"})
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})
# Контакт у User-Agent: власник сайту має знати, хто до нього звертається.
DEFAULT_CONTACT = "https://github.com/upspiritup/riskua-kontragent-bot"
DATABASE_SCHEMES = ("postgresql://", "postgres://")
# Токен від BotFather: числовий id бота, двокрапка, латинські літери, цифри, _ і -.
TOKEN_PATTERN = re.compile(r"\d+:[A-Za-z0-9_-]+")


class ConfigError(RuntimeError):
    """Змінну оточення не задано або задано неправильно."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Налаштування процесу. Секретів немає в repr, тож вони не потраплять у журнал."""

    env: str = "local"
    log_level: str = "INFO"
    contact: str = DEFAULT_CONTACT
    bot_token: str = field(default="", repr=False)
    database_url: str = field(default="", repr=False)

    def require_bot_token(self) -> str:
        """Токен бота; без нього бот не стартує."""
        return _required(self.bot_token, "BOT_TOKEN")

    def require_database_url(self) -> str:
        """Рядок з'єднання з базою; без нього не працюють міграції й перевірки."""
        return _required(self.database_url, "DATABASE_URL")


def load_settings(
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = DOTENV_PATH,
) -> Settings:
    """Читає RISKUA_* з .env і оточення; оточення важливіше за .env."""
    values = _collect(os.environ if environ is None else environ, dotenv_path)
    settings = Settings(
        env=values.get("ENV", "local").lower(),
        log_level=values.get("LOG_LEVEL", "INFO").upper(),
        contact=values.get("CONTACT", DEFAULT_CONTACT),
        bot_token=values.get("BOT_TOKEN", ""),
        database_url=values.get("DATABASE_URL", ""),
    )
    _validate(settings)
    return settings


def _collect(environ: Mapping[str, str], dotenv_path: Path | None) -> dict[str, str]:
    """Непорожні значення RISKUA_* без префікса: спершу з .env, поверх — з оточення."""
    file_values: dict[str, str | None] = {}
    if dotenv_path is not None and dotenv_path.is_file():
        # utf-8-sig: Блокнот у Windows дописує на початок файла невидимий BOM.
        file_values = dotenv_values(dotenv_path, encoding="utf-8-sig")
    merged = {**file_values, **environ}
    return {
        key.removeprefix(PREFIX): value.strip()
        for key, value in merged.items()
        if key.startswith(PREFIX) and value and value.strip()
    }


def _validate(settings: Settings) -> None:
    if settings.env not in ENVIRONMENTS:
        raise ConfigError(f"{PREFIX}ENV: очікується одне з {', '.join(sorted(ENVIRONMENTS))}")
    if settings.log_level not in LOG_LEVELS:
        raise ConfigError(f"{PREFIX}LOG_LEVEL: очікується одне з {', '.join(sorted(LOG_LEVELS))}")
    if settings.database_url and not settings.database_url.startswith(DATABASE_SCHEMES):
        raise ConfigError(f"{PREFIX}DATABASE_URL має починатися з postgresql://")
    if settings.bot_token and TOKEN_PATTERN.fullmatch(settings.bot_token) is None:
        raise ConfigError(f"{PREFIX}BOT_TOKEN не схожий на токен від @BotFather")


def _required(value: str, name: str) -> str:
    if not value:
        raise ConfigError(f"Не задано {PREFIX}{name}: додайте його в .env або в оточення")
    return value
