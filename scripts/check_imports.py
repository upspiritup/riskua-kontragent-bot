"""Імпорти в riskua/: шари, власники бібліотек, заборони і «єдине місце» (правила, розділ 2).

Усе налаштування — у [tool.riskua.imports] pyproject.toml. Новий пакет верхнього рівня
спершу додається в layers, інакше перевірка не пройде.

Запуск: python scripts/check_imports.py
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from _common import ROOT, Problem, load_settings, project_files, read_text, report


@dataclass(frozen=True)
class Rules:
    """Налаштування з [tool.riskua.imports]."""

    layers: list[list[str]]
    forbidden: dict[str, list[str]]
    owners: dict[str, str]
    single_place: dict[str, str]

    @classmethod
    def load(cls, root: Path) -> Rules:
        raw = load_settings(root)["imports"]
        return cls(raw["layers"], raw["forbidden"], raw["owners"], raw["single_place"])

    def layer(self, package: str) -> int | None:
        """Номер шару як у правилах: нижній шар — 1, верхній (bot) — найбільший."""
        for index, row in enumerate(self.layers):
            if package in row:
                return len(self.layers) - index
        return None


def package_of(relative: str) -> str:
    """riskua/db/migrate.py -> db; riskua/config.py -> config; riskua/__init__.py -> ''."""
    parts = relative.split("/")[1:]
    if len(parts) > 1:
        return parts[0]
    name = parts[0].removesuffix(".py")
    return "" if name == "__init__" else name


def target_package(module: str) -> str | None:
    """Пакет riskua, до якого веде імпорт: '' — сам riskua; None — модуль не з проєкту."""
    parts = module.split(".")
    if parts[0] != "riskua":
        return None
    if len(parts) == 1 or parts[1].startswith("_"):
        return ""
    return parts[1]


def resolve_from(node: ast.ImportFrom, relative: str) -> str:
    """Повна назва модуля в `from X import ...`, зокрема для відносних імпортів."""
    if node.level == 0:
        return node.module or ""
    package = relative.removesuffix(".py").split("/")[:-1]
    base = package[: len(package) - node.level + 1]
    return ".".join([*base, *([node.module] if node.module else [])])


def imports_of(tree: ast.AST, relative: str) -> Iterator[tuple[int, str]]:
    """(рядок, модуль) для кожного імпорту; `from riskua import db` дає riskua.db."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            base = resolve_from(node, relative)
            if base == "riskua":
                for alias in node.names:
                    yield node.lineno, f"riskua.{alias.name}"
            else:
                yield node.lineno, base


def layer_problem(own: str, module: str, rules: Rules) -> str | None:
    """Залежності йдуть лише згори вниз; пакети одного шару одне одного не імпортують."""
    target = target_package(module)
    if target is None or target in {"", own}:
        return None
    target_layer = rules.layer(target)
    own_layer = rules.layer(own)
    if target_layer is None:
        return f"{module}: пакета {target} немає в [tool.riskua.imports] layers"
    if own == "":
        return f"riskua/__init__.py не імпортує пакетів проєкту ({module})"
    if own_layer is not None and target_layer >= own_layer:
        where = "той самий шар" if target_layer == own_layer else "вищий шар"
        return (
            f"{own} (шар {own_layer}) не імпортує {target} (шар {target_layer}, {where}): "
            "залежності йдуть лише згори вниз"
        )
    return None


def forbidden_problem(own: str, module: str, rules: Rules) -> str | None:
    """Заборони понад шари; `riskua` у переліку — будь-який інший пакет проєкту."""
    for entry in rules.forbidden.get(own, []):
        if entry == "riskua":
            hit = target_package(module) not in {None, own}
        else:
            hit = module == entry or module.startswith(f"{entry}.")
        if hit:
            return f"{own} не імпортує {module} ([tool.riskua.imports.forbidden])"
    return None


def owner_problem(own: str, module: str, rules: Rules) -> str | None:
    """Бібліотеку з переліку власників імпортує лише її пакет."""
    library = module.partition(".")[0]
    owner = rules.owners.get(library)
    if owner is None or owner == own:
        return None
    return f"{library} імпортує лише riskua/{owner}/"


def dotted(node: ast.expr) -> str | None:
    """`a.b.c` для ланцюжка атрибутів від імені; None для всього іншого."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def used_names(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Повні назви імпортованого й ужитого: os.environ, datetime.datetime.now тощо."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.partition(".")[0]
                aliases[alias.asname or top] = alias.name if alias.asname else top
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
                yield node.lineno, f"{node.module}.{alias.name}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            head, _, rest = (dotted(node) or "").partition(".")
            if head in aliases:
                yield node.lineno, f"{aliases[head]}.{rest}"


def single_place_problems(relative: str, tree: ast.AST, rules: Rules) -> list[Problem]:
    """Оточення читає лише config.py, поточний час — лише clock.py."""
    own = package_of(relative)
    found: dict[tuple[int, str], str] = {}
    for line, name in used_names(tree):
        for banned, place in rules.single_place.items():
            if place != own and (name == banned or name.startswith(f"{banned}.")):
                found[(line, banned)] = place
    return [
        Problem(relative, line, f"{banned} — лише в riskua/{place}.py")
        for (line, banned), place in found.items()
    ]


CHECKS: tuple[Callable[[str, str, Rules], str | None], ...] = (
    layer_problem,
    forbidden_problem,
    owner_problem,
)


def file_problems(relative: str, tree: ast.AST, rules: Rules) -> list[Problem]:
    """Усі порушення імпортів в одному файлі."""
    own = package_of(relative)
    problems = []
    if own and rules.layer(own) is None:
        message = f"пакета {own} немає в [tool.riskua.imports] layers у pyproject.toml"
        problems.append(Problem(relative, 1, message))
    for line, module in imports_of(tree, relative):
        for check in CHECKS:
            found = check(own, module, rules)
            if found:
                problems.append(Problem(relative, line, found))
    return problems + single_place_problems(relative, tree, rules)


def run(root: Path = ROOT) -> list[Problem]:
    """Усі порушення імпортів у riskua/."""
    rules = Rules.load(root)
    problems = []
    for path, relative in project_files(root, "riskua"):
        problems += file_problems(relative, ast.parse(read_text(path), filename=relative), rules)
    return problems


def main() -> int:
    return report("Імпорти й шари", run())


if __name__ == "__main__":
    sys.exit(main())
