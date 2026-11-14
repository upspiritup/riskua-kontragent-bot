"""Тести допоміжних функцій scripts/check.py. Самі інструменти тут не запускаються."""

from __future__ import annotations

import check
from _common import ROOT


def test_legacy_tests_are_ignored():
    assert check.legacy_ignores(ROOT) == ["--ignore=tests/legacy"]


def test_database_url_from_environment_wins(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{check.TEST_DB_ENV}=postgresql://file\n", encoding="utf-8")
    monkeypatch.setenv(check.TEST_DB_ENV, "postgresql://env")
    assert check.find_test_database_url(tmp_path) == "postgresql://env"


def test_database_url_from_dotenv_with_bom(tmp_path, monkeypatch):
    monkeypatch.delenv(check.TEST_DB_ENV, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"{check.TEST_DB_ENV}=postgresql://file\n", encoding="utf-8-sig")
    assert check.find_test_database_url(tmp_path) == "postgresql://file"


def test_database_url_missing(tmp_path, monkeypatch):
    monkeypatch.delenv(check.TEST_DB_ENV, raising=False)
    assert check.find_test_database_url(tmp_path) == ""


def test_all_without_database_fails_with_hint(monkeypatch):
    monkeypatch.setattr(check, "find_test_database_url", lambda: "")
    [step] = check.pytest_steps(full=True, tests={"fast_seconds": 30})
    assert not step.ok
    assert check.TEST_DB_ENV in step.output


def test_failed_step_prints_trimmed_output(capsys):
    extra = 5
    output = "\n".join(f"line {index}" for index in range(check.MAX_OUTPUT_LINES + extra))
    check.print_step(check.Step("mypy", ok=False, seconds=1.0, output=output))
    printed = capsys.readouterr().out
    assert "ПОМИЛКА" in printed
    assert f"line {check.MAX_OUTPUT_LINES - 1}\n" in printed
    assert f"line {check.MAX_OUTPUT_LINES}\n" not in printed
    assert f"ще {extra} рядків" in printed


def test_passed_step_prints_one_line(capsys):
    check.print_step(check.Step("ruff check", ok=True, seconds=0.2, output="All checks passed!"))
    assert capsys.readouterr().out.count("\n") == 1
