"""Тимчасовий проєкт із копією справжнього pyproject.toml: перевірки бачать ті самі цифри."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from _common import ROOT


class Project:
    """Папка з pyproject.toml, куди тест кладе файли."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def add_file_exception(self, relative: str, lines: int, reason: str) -> None:
        """Дописує виняток у [tool.riskua.limits.exceptions]."""
        pyproject = self.root / "pyproject.toml"
        header = "[tool.riskua.limits.exceptions]\n"
        entry = f'"{relative}" = {{ lines = {lines}, reason = "{reason}" }}\n'
        text = pyproject.read_text(encoding="utf-8")
        assert header in text
        pyproject.write_text(text.replace(header, header + entry), encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Project:
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    return Project(tmp_path)
