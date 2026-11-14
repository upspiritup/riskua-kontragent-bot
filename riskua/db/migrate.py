"""Міграції: файли migrations/NNNN_назва.sql застосовуються по порядку номерів.

Застосовану міграцію не редагують (правила, розділ 6): її контрольна сума записана в
schema_migrations, і змінений файл зупиняє запуск. Змінити схему — нова міграція.

Запуск: python -m riskua.db.migrate
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import TupleRow

from riskua.config import load_settings
from riskua.logs import setup_logging

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
NAME_PATTERN = re.compile(r"(?P<version>\d{4})_[a-z0-9_]+\.sql")
# Будь-яке стале число: два одночасні запуски чекають один на одного, а не застосовують двічі.
ADVISORY_LOCK_ID = 7_310_001

CREATE_JOURNAL = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version    integer     PRIMARY KEY,
        name       text        NOT NULL,
        checksum   text        NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
    )
"""
SELECT_APPLIED = "SELECT version, checksum FROM schema_migrations ORDER BY version"
INSERT_APPLIED = "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)"

# Стала назва: під python -m модуль називається __main__, а в журналі потрібна справжня.
log = logging.getLogger("riskua.db.migrate")


class MigrationError(RuntimeError):
    """Міграції не можна застосувати без рішення людини."""


@dataclass(frozen=True, slots=True)
class Migration:
    """Один файл міграції."""

    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Міграції з папки; номери мають іти підряд від 0001."""
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = NAME_PATTERN.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"{path.name}: ім'я має бути NNNN_назва.sql, латиницею")
        # Git у Windows може віддати файл із \r\n — контрольна сума від цього не залежить.
        sql = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        migrations.append(Migration(int(match["version"]), path.name, sql))
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise MigrationError(f"Номери міграцій мають іти підряд від 0001, а маємо {versions}")
    return migrations


def apply_pending(
    conn: psycopg.Connection[TupleRow], migrations: list[Migration]
) -> list[Migration]:
    """Застосовує нові міграції, кожну у своїй транзакції. З'єднання — з autocommit."""
    conn.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_ID,))
    try:
        conn.execute(CREATE_JOURNAL)
        applied: dict[int, str] = dict(conn.execute(SELECT_APPLIED).fetchall())
        _verify_applied(applied, migrations)
        pending = [migration for migration in migrations if migration.version not in applied]
        for migration in pending:
            with conn.transaction():
                conn.execute(migration.sql)
                conn.execute(
                    INSERT_APPLIED, (migration.version, migration.name, migration.checksum)
                )
            log.info("migration_applied", extra={"migration": migration.name})
        return pending
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))


def _verify_applied(applied: dict[int, str], migrations: list[Migration]) -> None:
    """Застосовані міграції мають лишитися такими, якими їх застосували."""
    known = {migration.version: migration for migration in migrations}
    for version, checksum in applied.items():
        migration = known.get(version)
        if migration is None:
            raise MigrationError(f"У базі є міграція {version:04d}, якої немає серед файлів")
        if migration.checksum != checksum:
            raise MigrationError(
                f"{migration.name} змінено після застосування: потрібна нова міграція"
            )


def main() -> int:
    """Застосовує всі нові міграції до бази з RISKUA_DATABASE_URL."""
    settings = load_settings()
    setup_logging(settings.log_level)
    with psycopg.connect(settings.require_database_url(), autocommit=True) as conn:
        applied = apply_pending(conn, discover())
    log.info("migrations_done", extra={"applied": len(applied)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
