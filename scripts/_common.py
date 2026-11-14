"""Спільне для скриптів перевірки: корінь репозиторію, цифри з pyproject.toml, обхід файлів."""

from __future__ import annotations

import fnmatch
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, order=True)
class Problem:
    """Одне порушення правила: файл, рядок і що не так."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def load_settings(root: Path = ROOT) -> dict[str, Any]:
    """Розділ [tool.riskua] з pyproject.toml."""
    with (root / "pyproject.toml").open("rb") as file:
        data = tomllib.load(file)
    settings: dict[str, Any] = data["tool"]["riskua"]
    return settings


def is_legacy(relative: str, patterns: list[str]) -> bool:
    """Чи належить файл старому боту. `/**` у кінці — уся папка; `*` не перетинає `/`."""
    for pattern in patterns:
        if pattern.endswith("/**"):
            if relative.startswith(pattern[:-2]):
                return True
        elif relative.count("/") == pattern.count("/") and fnmatch.fnmatchcase(relative, pattern):
            return True
    return False


def project_files(root: Path, folder: str, pattern: str = "*.py") -> Iterator[tuple[Path, str]]:
    """Файли нового коду в папці: (шлях, шлях від кореня через `/`). Старий бот пропускається."""
    base = root / folder
    if not base.exists():
        return
    legacy = load_settings(root)["legacy"]
    for path in sorted(base.rglob(pattern)):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and "__pycache__" not in path.parts and not is_legacy(relative, legacy):
            yield path, relative


def read_text(path: Path) -> str:
    """Текст файла в UTF-8: однаково в Windows і Linux."""
    return path.read_text(encoding="utf-8")


def report(title: str, problems: list[Problem]) -> int:
    """Друкує порушення і повертає код виходу: 0 — порушень немає."""
    for problem in sorted(problems):
        print(problem)
    if problems:
        print(f"{title}: порушень — {len(problems)}")
        return 1
    print(f"{title}: порушень немає")
    return 0
