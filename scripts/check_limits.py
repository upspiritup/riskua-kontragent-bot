"""Межі розміру: файли, функції, вкладеність, придушення й винятки (правила, розділи 3 і 10).

Цифри — у [tool.riskua.limits] pyproject.toml. Складність, аргументи, гілки й return
перевіряє ruff; тут — те, чого ruff не вміє.

Запуск: python scripts/check_limits.py
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _common import ROOT, Problem, load_settings, project_files, read_text, report

# Блоки, які додають рівень вкладеності. elif і case окремого рівня не додають.
BLOCKS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.TryStar,
    ast.Match,
)
# Нова функція чи клас — новий відлік вкладеності.
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
# Придушення в коментарі: noqa (зокрема у формі ruff: noqa) і type: ignore.
SUPPRESSION = re.compile(r"#\s*(?:ruff\s*:\s*)?(?:noqa\b|type\s*:\s*ignore\b)", re.IGNORECASE)
# Папки, де діють межі для коду; у tests/ — лише межа розміру файла.
CODE_FOLDERS = ("riskua", "scripts")


@dataclass(frozen=True)
class Limits:
    """Цифри з [tool.riskua.limits]."""

    file_lines: int
    file_lines_target: int
    test_file_lines: int
    function_lines: int
    nesting_depth: int
    suppressions: int
    file_exceptions: int
    fixture_kb: int
    exceptions: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, root: Path) -> Limits:
        raw = dict(load_settings(root)["limits"])
        return cls(exceptions=raw.pop("exceptions", {}), **raw)


def line_count(text: str) -> int:
    return len(text.splitlines())


def function_problems(relative: str, tree: ast.AST, limit: int) -> list[Problem]:
    """Функції довші за межу: від рядка з def до останнього рядка тіла."""
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > limit:
                message = f"функція {node.name}: {length} рядків, межа {limit}"
                problems.append(Problem(relative, node.lineno, message))
    return problems


def is_elif(parent: ast.AST, child: ast.AST) -> bool:
    """`elif` у дереві — це if у гілці else з тим самим відступом, що й батьківський if."""
    return (
        isinstance(parent, ast.If)
        and isinstance(child, ast.If)
        and parent.orelse == [child]
        and child.col_offset == parent.col_offset
    )


def nesting_problems(relative: str, tree: ast.AST, limit: int) -> list[Problem]:
    """Блоки глибше за межу. Для кожного ланцюжка — лише перший зайвий рівень."""
    problems: list[Problem] = []

    def visit(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            child_depth = depth
            if isinstance(child, SCOPES):
                child_depth = 0
            elif isinstance(child, BLOCKS) and not is_elif(node, child):
                child_depth = depth + 1
                if child_depth == limit + 1:
                    message = f"вкладеність блоків: рівень {child_depth}, межа {limit}"
                    problems.append(Problem(relative, child.lineno, message))
            visit(child, child_depth)

    visit(tree, 0)
    return problems


def file_problems(root: Path, limits: Limits) -> list[Problem]:
    """Розмір файлів коду, довжина функцій і вкладеність блоків."""
    problems = []
    for folder in CODE_FOLDERS:
        for pattern in ("*.py", "*.sql"):
            for path, relative in project_files(root, folder, pattern):
                text = read_text(path)
                limit = limits.exceptions.get(relative, {}).get("lines", limits.file_lines)
                count = line_count(text)
                if count > limit:
                    message = f"файл: {count} рядків, межа {limit} — поділіть за змістом"
                    problems.append(Problem(relative, count, message))
                if path.suffix == ".py":
                    tree = ast.parse(text, filename=relative)
                    problems += function_problems(relative, tree, limits.function_lines)
                    problems += nesting_problems(relative, tree, limits.nesting_depth)
    return problems


def exception_problems(root: Path, limits: Limits) -> list[Problem]:
    """Винятки з межі розміру: бюджет, причина і чи вони ще потрібні."""
    problems = []
    if len(limits.exceptions) > limits.file_exceptions:
        message = (
            f"винятків із межі розміру {len(limits.exceptions)}, бюджет {limits.file_exceptions}"
        )
        problems.append(Problem("pyproject.toml", 1, message))
    for relative, entry in limits.exceptions.items():
        path = root / relative
        if not str(entry.get("reason", "")).strip():
            problems.append(Problem("pyproject.toml", 1, f"виняток для {relative} без причини"))
        if not path.is_file():
            problems.append(Problem("pyproject.toml", 1, f"виняток для {relative}: файла немає"))
        elif line_count(read_text(path)) <= limits.file_lines:
            message = f"виняток для {relative} не потрібен: файл уже вкладається в межу"
            problems.append(Problem("pyproject.toml", 1, message))
    return problems


def suppression_lines(text: str) -> list[int]:
    """Рядок кожного придушення. Шукаємо лише в коментарях, а не в рядкових константах."""
    lines = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            lines += [token.start[0]] * len(SUPPRESSION.findall(token.string))
    return lines


def suppression_problems(root: Path, limits: Limits) -> list[Problem]:
    """Придушення в riskua/: бюджет на проєкт і коментар із причиною рядком вище."""
    problems = []
    total = 0
    for path, relative in project_files(root, "riskua"):
        text = read_text(path)
        source = text.splitlines()
        lines = suppression_lines(text)
        total += len(lines)
        for line in sorted(set(lines)):
            above = source[line - 2].strip() if line > 1 else ""
            if not above.startswith("#") or SUPPRESSION.search(above):
                message = "придушення без причини: потрібен коментар із причиною рядком вище"
                problems.append(Problem(relative, line, message))
    if total > limits.suppressions:
        message = f"придушень {total}, бюджет {limits.suppressions} на весь riskua/"
        problems.append(Problem("riskua", 0, message))
    return problems


def tests_folder_problems(root: Path, limits: Limits) -> list[Problem]:
    """Розмір файлів тестів і зразків файлів джерел."""
    problems = []
    for path, relative in project_files(root, "tests"):
        count = line_count(read_text(path))
        if count > limits.test_file_lines:
            message = f"файл тестів: {count} рядків, межа {limits.test_file_lines}"
            problems.append(Problem(relative, count, message))
    for path, relative in project_files(root, "tests/fixtures", "*"):
        size_kb = path.stat().st_size / 1024
        if size_kb > limits.fixture_kb:
            message = f"зразок {size_kb:.0f} КБ, межа {limits.fixture_kb} КБ: потрібен уривок"
            problems.append(Problem(relative, 1, message))
    return problems


def target_notes(root: Path = ROOT) -> list[str]:
    """Файли понад орієнтир, але в межах: ще не помилка, але час думати, як ділити."""
    limits = Limits.load(root)
    notes = []
    for folder in CODE_FOLDERS:
        for path, relative in project_files(root, folder):
            count = line_count(read_text(path))
            if limits.file_lines_target < count <= limits.file_lines:
                notes.append(f"{relative}: {count} рядків, орієнтир {limits.file_lines_target}")
    return notes


def run(root: Path = ROOT) -> list[Problem]:
    """Усі порушення меж розміру в проєкті."""
    limits = Limits.load(root)
    return [
        *file_problems(root, limits),
        *exception_problems(root, limits),
        *suppression_problems(root, limits),
        *tests_folder_problems(root, limits),
    ]


def main() -> int:
    for note in target_notes():
        print(f"орієнтир: {note}")
    return report("Межі розміру", run())


if __name__ == "__main__":
    sys.exit(main())
