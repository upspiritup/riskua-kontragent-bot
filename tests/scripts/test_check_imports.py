"""Тести scripts/check_imports.py: шари, заборони, власники бібліотек і «єдине місце»."""

from __future__ import annotations

import pytest

import check_imports

DOMAIN_FILE = "riskua/domain/rules/debts.py"
INGEST_FILE = "riskua/ingest/edr.py"


def problems(project, relative: str, source: str) -> list[str]:
    project.write(relative, source)
    return [p.message for p in check_imports.run(project.root) if p.path == relative]


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("riskua/http/client.py", "from riskua.db import pool\n"),
        (
            "riskua/usecases/check.py",
            "from riskua.report import text\nfrom riskua.facts import x\n",
        ),
        ("riskua/bot/handlers.py", "from riskua.usecases import check_company\n"),
        ("riskua/bot/handlers.py", "from riskua.bot import texts\n"),
        ("riskua/http/client.py", "from riskua import __version__\n"),
        ("riskua/db/pool.py", "from riskua.config import Settings\nfrom riskua import logs\n"),
        ("riskua/db/pool.py", "from . import migrate\n"),
    ],
)
def test_allowed_imports(project, relative, source):
    assert problems(project, relative, source) == []


@pytest.mark.parametrize(
    ("relative", "source", "expected"),
    [
        ("riskua/db/pool.py", "from riskua.http import client\n", "вищий шар"),
        ("riskua/report/text.py", "from riskua.facts import debts\n", "той самий шар"),
        ("riskua/logs.py", "import riskua.config\n", "той самий шар"),
        ("riskua/db/pool.py", "from ..http import client\n", "вищий шар"),
        ("riskua/db/pool.py", "import riskua.utils\n", "пакета utils немає"),
        ("riskua/__init__.py", "from riskua import config\n", "не імпортує пакетів"),
    ],
)
def test_layer_violations(project, relative, source, expected):
    [message] = problems(project, relative, source)
    assert expected in message


def test_new_package_must_be_declared(project):
    [message] = problems(project, "riskua/utils/helpers.py", "X = 1\n")
    assert "пакета utils немає" in message


@pytest.mark.parametrize(
    "source",
    [
        "import os\n",
        "from pathlib import Path\n",
        "import asyncio\n",
        "import urllib.parse\n",
        "import socket\n",
        "import subprocess\n",
        "from riskua import clock\n",
        "import riskua.config\n",
    ],
)
def test_domain_stays_pure(project, source):
    assert problems(project, DOMAIN_FILE, source)


def test_domain_may_import_itself_and_plain_stdlib(project):
    source = "from datetime import date\nfrom riskua.domain.models import Fact\n"
    assert problems(project, DOMAIN_FILE, source) == []


def test_bot_goes_through_usecases(project):
    [message] = problems(project, "riskua/bot/handlers.py", "from riskua.db import pool\n")
    assert "bot не імпортує riskua.db" in message


@pytest.mark.parametrize(
    ("relative", "source", "allowed"),
    [
        ("riskua/http/client.py", "import httpx\n", True),
        ("riskua/db/pool.py", "from psycopg_pool import AsyncConnectionPool\n", True),
        ("riskua/db/pool.py", "import psycopg.rows\n", True),
        ("riskua/bot/__main__.py", "from aiogram import Bot\n", True),
        ("riskua/sources/prozorro.py", "import httpx\n", False),
        ("riskua/ingest/edr.py", "from psycopg import sql\n", False),
        ("riskua/usecases/check.py", "from aiogram import Bot\n", False),
    ],
)
def test_library_owners(project, relative, source, allowed):
    assert (problems(project, relative, source) == []) is allowed


@pytest.mark.parametrize(
    "source",
    [
        "import os\nTOKEN = os.environ['RISKUA_BOT_TOKEN']\n",
        "import os\nTOKEN = os.getenv('RISKUA_BOT_TOKEN')\n",
        "from os import environ\n",
        "import os as system\nTOKEN = system.environ.get('X')\n",
        "from dotenv import load_dotenv\n",
        "from datetime import datetime\nNOW = datetime.now()\n",
        "import datetime\nNOW = datetime.datetime.now()\n",
        "import datetime as dt\nTODAY = dt.date.today()\n",
        "from datetime import date\nTODAY = date.today()\n",
        "import time\nNOW = time.time()\n",
    ],
)
def test_environment_and_time_only_in_their_modules(project, source):
    [message] = problems(project, INGEST_FILE, source)
    assert "лише в riskua/" in message


@pytest.mark.parametrize(
    "source",
    [
        "import os\nPATH = os.path.join('a', 'b')\n",
        "import time\nSTARTED = time.monotonic()\n",
        "from datetime import UTC, datetime\nEPOCH = datetime(2020, 1, 1, tzinfo=UTC)\n",
    ],
)
def test_harmless_os_and_time_usage(project, source):
    assert problems(project, INGEST_FILE, source) == []


def test_config_and_clock_are_the_single_places(project):
    assert problems(project, "riskua/config.py", "import os\nENV = os.environ\n") == []
    clock = "from datetime import UTC, datetime\nNOW = datetime.now(UTC)\n"
    assert problems(project, "riskua/clock.py", clock) == []
