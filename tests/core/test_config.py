"""Тести riskua/config.py: читання RISKUA_* з оточення і .env, перевірка значень."""

from __future__ import annotations

import pytest

from riskua.config import DEFAULT_CONTACT, ConfigError, Settings, load_settings

TOKEN = "123456:ABCdef_ghi-JKL"
DATABASE_URL = "postgresql://riskua:secret@localhost:5432/riskua"


def test_defaults_without_variables():
    settings = load_settings({}, dotenv_path=None)
    assert settings == Settings()
    assert settings.contact == DEFAULT_CONTACT


def test_reads_prefixed_variables_and_normalizes_case():
    environ = {
        "RISKUA_ENV": "Production",
        "RISKUA_LOG_LEVEL": "debug",
        "RISKUA_BOT_TOKEN": f" {TOKEN} ",
        "RISKUA_DATABASE_URL": DATABASE_URL,
        "RISKUA_CONTACT": "mailto:bot@example.com",
    }
    settings = load_settings(environ, dotenv_path=None)
    assert settings == Settings(
        env="production",
        log_level="DEBUG",
        contact="mailto:bot@example.com",
        bot_token=TOKEN,
        database_url=DATABASE_URL,
    )


def test_old_bot_variables_are_ignored():
    settings = load_settings({"BOT_TOKEN": TOKEN, "APP_ENV": "local"}, dotenv_path=None)
    assert settings.bot_token == ""


def test_blank_values_count_as_unset():
    settings = load_settings({"RISKUA_BOT_TOKEN": "   ", "RISKUA_ENV": ""}, dotenv_path=None)
    assert settings == Settings()


def test_reads_dotenv_saved_with_bom(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"RISKUA_LOG_LEVEL=WARNING\nRISKUA_BOT_TOKEN={TOKEN}\n", encoding="utf-8-sig"
    )
    settings = load_settings({}, dotenv_path=env_file)
    assert settings.log_level == "WARNING"
    assert settings.bot_token == TOKEN


def test_environment_overrides_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("RISKUA_LOG_LEVEL=WARNING\n", encoding="utf-8")
    settings = load_settings({"RISKUA_LOG_LEVEL": "ERROR"}, dotenv_path=env_file)
    assert settings.log_level == "ERROR"


def test_missing_dotenv_file_is_fine(tmp_path):
    assert load_settings({}, dotenv_path=tmp_path / "missing.env") == Settings()


def test_reads_process_environment_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RISKUA_LOG_LEVEL", "ERROR")
    assert load_settings().log_level == "ERROR"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("RISKUA_ENV", "staging"),
        ("RISKUA_LOG_LEVEL", "LOUD"),
        ("RISKUA_DATABASE_URL", "mysql://riskua@localhost/riskua"),
        ("RISKUA_BOT_TOKEN", "not a token"),
    ],
)
def test_invalid_values_name_the_variable(key, value):
    with pytest.raises(ConfigError, match=key):
        load_settings({key: value}, dotenv_path=None)


def test_require_fails_with_variable_name():
    with pytest.raises(ConfigError, match="RISKUA_BOT_TOKEN"):
        Settings().require_bot_token()
    with pytest.raises(ConfigError, match="RISKUA_DATABASE_URL"):
        Settings().require_database_url()


def test_require_returns_value():
    settings = Settings(bot_token=TOKEN, database_url=DATABASE_URL)
    assert settings.require_bot_token() == TOKEN
    assert settings.require_database_url() == DATABASE_URL


def test_repr_hides_secrets():
    text = repr(Settings(bot_token=TOKEN, database_url=DATABASE_URL))
    assert TOKEN not in text
    assert "secret" not in text
