"""Тести riskua/bot: відповіді на повідомлення без справжнього Telegram."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

import riskua.bot.__main__ as entry
from riskua.bot import texts
from riskua.config import ConfigError

TOKEN = "123456:TEST-token_value"
CHAT_ID = 42


class RecordingSession(BaseSession):
    """Сесія, яка нікуди не ходить, а запам'ятовує запити бота до Telegram."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[Any] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: Any, *args: Any, **kwargs: Any) -> Any:
        self.requests.append(method)

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def send(text: str) -> list[Any]:
    """Передає диспетчеру повідомлення від користувача; повертає запити бота."""
    session = RecordingSession()
    bot = Bot(TOKEN, session=session)
    message = Message(
        message_id=1,
        date=datetime(2026, 1, 1, tzinfo=UTC),
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=CHAT_ID, is_bot=False, first_name="Тест"),
        text=text,
    )
    asyncio.run(entry.build_dispatcher().feed_update(bot, Update(update_id=1, message=message)))
    return session.requests


def test_start_greets_user():
    [request] = send("/start")
    assert isinstance(request, SendMessage)
    assert request.chat_id == CHAT_ID
    assert request.text == texts.START


def test_other_messages_say_check_is_not_ready():
    [request] = send("12345678")
    assert request.text == texts.NOT_READY


def test_main_needs_token(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RISKUA_BOT_TOKEN", raising=False)
    monkeypatch.setattr(entry, "setup_logging", lambda level: None)
    with pytest.raises(ConfigError, match="RISKUA_BOT_TOKEN"):
        entry.main()


def test_main_starts_polling(monkeypatch, tmp_path):
    polled: list[Bot] = []

    class FakeDispatcher:
        async def start_polling(self, bot: Bot) -> None:
            polled.append(bot)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RISKUA_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(entry, "setup_logging", lambda level: None)
    monkeypatch.setattr(entry, "build_dispatcher", FakeDispatcher)
    assert entry.main() == 0
    assert [bot.token for bot in polled] == [TOKEN]
