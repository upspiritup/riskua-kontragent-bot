"""Тексти: у domain/ немає кириличних рядків, у текстах для користувача — оцінних слів.

Правила, розділи 4.8 і 7.5. Docstring і коментарі не перевіряються: їх пишемо українською.
Налаштування — у [tool.riskua.texts] pyproject.toml.

Запуск: python scripts/check_texts.py
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from _common import ROOT, Problem, load_settings, project_files, read_text, report

CYRILLIC = re.compile("[Ѐ-ӿ]")
DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def docstring_ids(tree: ast.AST) -> set[int]:
    """id вузлів-docstring: перший рядок у тілі модуля, класу чи функції."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, DOCSTRING_OWNERS) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def strings(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Рядкові константи, крім docstring, зокрема частини f-рядків: (рядок, текст)."""
    skip = docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value


def files_under(root: Path, target: str) -> Iterator[tuple[Path, str]]:
    """Файли .py за шляхом із налаштувань: окремий файл або вся папка."""
    path = root / target
    if path.is_file():
        yield path, target
    else:
        yield from project_files(root, target)


def code_only_problems(root: Path, packages: list[str]) -> list[Problem]:
    """У пакетах лише з кодом рядки не містять кирилиці: текст для людей дає report/."""
    problems = []
    for package in packages:
        for path, relative in files_under(root, f"riskua/{package}"):
            for line, text in strings(ast.parse(read_text(path))):
                if CYRILLIC.search(text):
                    message = f"рядок із кирилицею в {package}/: тут код, текст дає report/"
                    problems.append(Problem(relative, line, message))
    return problems


def banned_word_problems(root: Path, targets: list[str], stems: list[str]) -> list[Problem]:
    """Тексти для користувача описують ознаки ризику, а не роблять висновків про людей."""
    problems = []
    for target in targets:
        for path, relative in files_under(root, target):
            for line, text in strings(ast.parse(read_text(path))):
                lowered = text.lower()
                problems += [
                    Problem(relative, line, f"«{stem}…» у тексті для користувача")
                    for stem in stems
                    if stem in lowered
                ]
    return problems


def run(root: Path = ROOT) -> list[Problem]:
    """Усі порушення правил про тексти."""
    settings = load_settings(root)["texts"]
    return [
        *code_only_problems(root, settings["code_only_packages"]),
        *banned_word_problems(root, settings["user_text_paths"], settings["banned_stems"]),
    ]


def main() -> int:
    return report("Тексти", run())


if __name__ == "__main__":
    sys.exit(main())
