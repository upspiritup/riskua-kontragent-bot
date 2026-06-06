from __future__ import annotations

import os
from dataclasses import dataclass
from os import PathLike
from typing import Mapping

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in runtime envs
    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False


@dataclass(frozen=True)
class Settings:
    bot_token: str
    app_env: str = "local"


def load_settings(
    environ: Mapping[str, str] | None = None,
    dotenv_path: str | PathLike[str] | None = None,
) -> Settings:
    if environ is None:
        load_dotenv(dotenv_path=dotenv_path, encoding="utf-8-sig")
        environ = os.environ

    bot_token = environ.get("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required. Create .env and set BOT_TOKEN.")

    app_env = environ.get("APP_ENV", "local").strip() or "local"
    return Settings(bot_token=bot_token, app_env=app_env)
