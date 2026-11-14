"""Тести riskua/db/migrate.py: порядок файлів, контрольні суми, застосування в базі."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from riskua.db import migrate
from riskua.db.migrate import Migration, MigrationError, apply_pending, discover

TABLE_A = Migration(1, "0001_a.sql", "CREATE TABLE a (id integer);")


def write(directory: Path, name: str, sql: str = "SELECT 1;\n") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(sql.encode("utf-8"))


def names(conn: psycopg.Connection, query: str) -> list:
    return [row[0] for row in conn.execute(query)]


def test_project_migrations_are_numbered_in_order():
    migrations = discover()
    assert migrations[0].name == "0001_dataset_runs.sql"
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))


def test_bad_file_name_is_rejected(tmp_path):
    write(tmp_path, "1_init.sql")
    with pytest.raises(MigrationError, match=r"1_init\.sql"):
        discover(tmp_path)


def test_gap_in_numbers_is_rejected(tmp_path):
    write(tmp_path, "0001_a.sql")
    write(tmp_path, "0003_c.sql")
    with pytest.raises(MigrationError, match="підряд"):
        discover(tmp_path)


def test_checksum_ignores_windows_line_endings(tmp_path):
    write(tmp_path / "unix", "0001_a.sql", "SELECT 1;\nSELECT 2;\n")
    write(tmp_path / "windows", "0001_a.sql", "SELECT 1;\r\nSELECT 2;\r\n")
    unix = discover(tmp_path / "unix")[0]
    windows = discover(tmp_path / "windows")[0]
    assert unix.checksum == windows.checksum


@pytest.mark.db
def test_applies_each_migration_once(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        first = apply_pending(conn, discover())
        second = apply_pending(conn, discover())
        columns = names(
            conn,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'dataset_runs'",
        )
    assert first == discover()
    assert second == []
    assert {"dataset", "status", "row_count", "source_modified_at", "source_hash"} <= set(columns)


@pytest.mark.db
def test_dataset_runs_rejects_unknown_status(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_pending(conn, discover())
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO dataset_runs (dataset, status) VALUES ('edr', 'done')")


@pytest.mark.db
def test_edited_migration_stops_the_run(database_url):
    edited = Migration(1, "0001_a.sql", "CREATE TABLE a (id bigint);")
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_pending(conn, [TABLE_A])
        with pytest.raises(MigrationError, match="змінено"):
            apply_pending(conn, [edited])


@pytest.mark.db
def test_unknown_applied_migration_stops_the_run(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        apply_pending(conn, [TABLE_A])
        with pytest.raises(MigrationError, match="0001"):
            apply_pending(conn, [])


@pytest.mark.db
def test_failed_migration_leaves_no_trace(database_url):
    broken = Migration(2, "0002_b.sql", "CREATE TABLE b (id integer); SELECT * FROM missing;")
    with psycopg.connect(database_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.UndefinedTable):
            apply_pending(conn, [TABLE_A, broken])
        applied = names(conn, "SELECT version FROM schema_migrations")
        tables = names(
            conn,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema()",
        )
    assert applied == [1]
    assert "a" in tables
    assert "b" not in tables


@pytest.mark.db
def test_main_reads_database_url_from_environment(database_url, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RISKUA_DATABASE_URL", database_url)
    monkeypatch.setattr(migrate, "setup_logging", lambda level: None)
    assert migrate.main() == 0
    with psycopg.connect(database_url) as conn:
        applied = names(conn, "SELECT name FROM schema_migrations ORDER BY version")
    assert applied == [m.name for m in discover()]
