"""Журнал: один рядок JSON на подію.

У журнал пишемо назву події, ЄДРПОУ, id і технічні поля, але не токени й не тексти
повідомлень користувачів (правила, розділ 11). Про всяк випадок форматер вирізає все,
схоже на токен бота або пароль у рядку з'єднання: вони трапляються в текстах помилок.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

# Токен бота: id, двокрапка, 30+ символів. Буває в URL у помилках мережі.
TOKEN_PATTERN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
# Пароль у postgresql://користувач:пароль@сервер.
PASSWORD_PATTERN = re.compile(r"(://[^:/@\s]+):[^@\s]+@")
REDACTED = "<redacted>"
# Стандартні поля запису; усе інше в записі — поля, передані через extra.
STANDARD_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def redact(text: str) -> str:
    """Прибирає з тексту токени ботів і паролі з рядків з'єднання."""
    text = TOKEN_PATTERN.sub(REDACTED, text)
    return PASSWORD_PATTERN.sub(rf"\1:{REDACTED}@", text)


class JsonFormatter(logging.Formatter):
    """Запис журналу -> рядок JSON разом із полями з extra."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(
            (key, value) for key, value in vars(record).items() if key not in STANDARD_FIELDS
        )
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, ensure_ascii=False, default=str))


def setup_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Один обробник на весь процес; повторний виклик замінює попередній."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
