"""Запуск бота: python -m riskua.bot.

Поки що бот лише вітається: перевірка контрагента з'явиться в завданні 1.9.
"""

from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from riskua.bot import texts
from riskua.config import load_settings
from riskua.logs import setup_logging


async def on_start(message: Message) -> None:
    """Відповідь на /start."""
    await message.answer(texts.START)


async def on_other(message: Message) -> None:
    """Відповідь на будь-яке інше повідомлення, поки перевірки ще немає."""
    await message.answer(texts.NOT_READY)


def build_dispatcher() -> Dispatcher:
    """Диспетчер з усіма обробниками: той самий для запуску і для тестів."""
    router = Router(name="start")
    router.message.register(on_start, CommandStart())
    router.message.register(on_other)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


def main() -> int:
    """Читає налаштування і слухає Telegram через long polling."""
    settings = load_settings()
    setup_logging(settings.log_level)
    bot = Bot(settings.require_bot_token())
    asyncio.run(build_dispatcher().start_polling(bot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
