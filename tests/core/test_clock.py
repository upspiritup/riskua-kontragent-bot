"""Тести riskua/clock.py: час в UTC, дата за Києвом."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from riskua import clock


def test_now_is_aware_utc():
    now = clock.now()
    assert now.tzinfo is UTC
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)


def test_today_follows_kyiv_calendar():
    before = datetime.now(clock.KYIV).date()
    today = clock.today()
    after = datetime.now(clock.KYIV).date()
    assert before <= today <= after


def test_kyiv_offset_is_two_or_three_hours():
    offsets = {
        datetime(2026, 1, 15, 12, tzinfo=clock.KYIV).utcoffset(),
        datetime(2026, 7, 15, 12, tzinfo=clock.KYIV).utcoffset(),
    }
    assert offsets == {timedelta(hours=2), timedelta(hours=3)}
