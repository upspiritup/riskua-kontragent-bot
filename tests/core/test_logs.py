"""Тести riskua/logs.py: рядок JSON на подію, без токенів і паролів."""

from __future__ import annotations

import io
import json
import logging

import pytest

from riskua.logs import REDACTED, redact, setup_logging

TOKEN = "123456789:AAH-abcdefghijklmnopqrstuvwxyz012345"


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers = handlers
    root.setLevel(level)


def capture(level: str = "INFO") -> io.StringIO:
    stream = io.StringIO()
    setup_logging(level, stream)
    return stream


def records(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_one_json_line_with_extra_fields():
    stream = capture()
    logging.getLogger("riskua.test").info("check_done", extra={"edrpou": "12345678", "user": 42})
    [record] = records(stream)
    assert record["event"] == "check_done"
    assert record["level"] == "INFO"
    assert record["logger"] == "riskua.test"
    assert record["edrpou"] == "12345678"
    assert record["user"] == 42
    assert record["time"].endswith("+00:00")


def test_bot_token_is_redacted_everywhere():
    stream = capture()
    log = logging.getLogger("riskua.test")
    log.warning("request failed: %s", f"https://api.telegram.org/bot{TOKEN}/getMe")
    log.warning("retry", extra={"url": f"https://api.telegram.org/bot{TOKEN}/getUpdates"})
    try:
        raise RuntimeError(f"bad token {TOKEN}")
    except RuntimeError:
        log.exception("crash")
    output = stream.getvalue()
    assert TOKEN not in output
    assert output.count(REDACTED) >= 3
    assert "RuntimeError" in records(stream)[-1]["error"]


def test_database_password_is_redacted():
    url = "postgresql://riskua:s3cret@db:5432/riskua"
    assert redact(url) == f"postgresql://riskua:{REDACTED}@db:5432/riskua"


def test_level_filters_records():
    stream = capture("WARNING")
    log = logging.getLogger("riskua.test")
    log.info("skipped")
    log.warning("kept")
    assert [record["event"] for record in records(stream)] == ["kept"]


def test_setup_replaces_previous_handler():
    first = capture()
    second = capture()
    logging.getLogger("riskua.test").info("once")
    assert first.getvalue() == ""
    assert len(records(second)) == 1
