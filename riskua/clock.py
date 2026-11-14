"""Єдине місце, де читається поточний час. Решта коду отримує час параметром."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


def now() -> datetime:
    """Поточний момент в UTC: для журналу, бази і строків кешу."""
    return datetime.now(UTC)


def today() -> date:
    """Сьогоднішня дата за київським часом: від неї рахуються вік компанії і «станом на»."""
    return datetime.now(KYIV).date()
