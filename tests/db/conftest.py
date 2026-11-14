"""Тестова база: окрема схема на кожен тест, тож тести не бачать даних один одного.

Адреса — у RISKUA_TEST_DATABASE_URL; check.py --all бере її з оточення або з .env.
Без неї тести з позначкою db пропускаються.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from urllib.parse import quote

import psycopg
import pytest
from psycopg import sql

TEST_DB_ENV = "RISKUA_TEST_DATABASE_URL"


@pytest.fixture
def database_url() -> Iterator[str]:
    """Адреса бази, де search_path веде в нову порожню схему; після тесту схема зникає."""
    base = os.environ.get(TEST_DB_ENV, "").strip()
    if not base:
        pytest.skip(f"{TEST_DB_ENV} не задано")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    separator = "&" if "?" in base else "?"
    try:
        yield f"{base}{separator}options={quote(f'-c search_path={schema}')}"
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
