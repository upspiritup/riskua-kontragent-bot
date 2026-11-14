"""Команда «готово»: усі перевірки проєкту одним запуском.

    python scripts/check.py          # без бази даних
    python scripts/check.py --all    # плюс тести з PostgreSQL

Для --all потрібна адреса тестової бази RISKUA_TEST_DATABASE_URL (в оточенні або в .env):
тести працюють в окремій схемі й прибирають за собою. Цифри — у [tool.riskua] pyproject.toml.
"""

from __future__ import annotations

import argparse
import io
import itertools
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

import check_imports
import check_limits
import check_texts
from _common import ROOT, Problem, load_settings

TEST_DB_ENV = "RISKUA_TEST_DATABASE_URL"
# Скільки рядків виводу показати для кроку, що впав: далі зазвичай повтори.
MAX_OUTPUT_LINES = 150


@dataclass
class Step:
    """Результат одного кроку перевірки."""

    name: str
    ok: bool
    seconds: float
    output: str = ""


def run_tool(name: str, args: list[str], env: dict[str, str] | None = None) -> Step:
    """Запускає інструмент як `python -m ...` з кореня репозиторію."""
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1", **(env or {})},
        check=False,
    )
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return Step(name, result.returncode == 0, time.perf_counter() - started, output)


def run_check(name: str, check: Callable[[Path], list[Problem]]) -> Step:
    """Запускає перевірку зі scripts/ у цьому ж процесі."""
    started = time.perf_counter()
    problems = sorted(check(ROOT))
    output = "\n".join(str(problem) for problem in problems)
    return Step(name, not problems, time.perf_counter() - started, output)


def static_steps() -> Iterator[Step]:
    """Перевірки без запуску тестів."""
    yield run_tool("ruff format", ["ruff", "format", "--check", "."])
    yield run_tool("ruff check", ["ruff", "check", "."])
    yield run_tool("mypy", ["mypy"])
    yield run_check("межі розміру", check_limits.run)
    yield run_check("імпорти й шари", check_imports.run)
    yield run_check("тексти", check_texts.run)


def find_test_database_url(root: Path = ROOT) -> str:
    """Адреса тестової бази: з оточення, а якщо там немає — з .env."""
    url = os.environ.get(TEST_DB_ENV, "")
    env_file = root / ".env"
    if not url and env_file.is_file():
        url = dotenv_values(env_file, encoding="utf-8-sig").get(TEST_DB_ENV) or ""
    return url.strip()


def legacy_ignores(root: Path = ROOT) -> list[str]:
    """`--ignore` для папок старого бота всередині tests/."""
    return [
        f"--ignore={pattern.removesuffix('/**')}"
        for pattern in load_settings(root)["legacy"]
        if pattern.startswith("tests/") and pattern.endswith("/**")
    ]


def pytest_steps(full: bool, tests: dict[str, Any]) -> Iterator[Step]:
    """Тести і покриття: швидкий набір або, з --all, разом із базою."""
    env = {}
    if full:
        url = find_test_database_url()
        if not url:
            hint = f"Задайте {TEST_DB_ENV} в оточенні або в .env (див. .env.example)"
            yield Step("тести з базою", False, 0.0, hint)
            return
        env[TEST_DB_ENV] = url
    marker = "not net" if full else "not db and not net"
    args = [
        "pytest",
        "tests",
        *legacy_ignores(),
        "-m",
        marker,
        "-q",
        "--cov=riskua",
        "--cov-report=",
    ]
    step = run_tool("тести з базою" if full else "тести", args, env)
    if not full and step.ok and step.seconds > tests["fast_seconds"]:
        step.ok = False
        step.output = f"Швидкий набір триває {step.seconds:.0f} с, межа {tests['fast_seconds']} с"
    yield step
    if step.ok:
        yield from coverage_steps(full, tests)


def coverage_steps(full: bool, tests: dict[str, Any]) -> Iterator[Step]:
    """Покриття ядра (domain/, report/) завжди, усього riskua/ — з --all."""
    core = [name for name in tests["core_packages"] if (ROOT / "riskua" / name).is_dir()]
    if core:
        include = ",".join(f"riskua/{name}/*" for name in core)
        limit = f"--fail-under={tests['coverage_core']}"
        name = f"покриття {', '.join(core)}"
        yield run_tool(name, ["coverage", "report", f"--include={include}", limit])
    if full:
        limit = f"--fail-under={tests['coverage_total']}"
        yield run_tool("покриття riskua/", ["coverage", "report", limit])


def print_step(step: Step) -> None:
    """Рядок про крок; для кроку, що впав, — ще й його вивід."""
    mark = "OK     " if step.ok else "ПОМИЛКА"
    print(f"{mark} {step.name:<24} {step.seconds:5.1f} с", flush=True)
    if step.ok or not step.output:
        return
    lines = step.output.splitlines()
    for line in lines[:MAX_OUTPUT_LINES]:
        print(f"    {line}")
    if len(lines) > MAX_OUTPUT_LINES:
        print(f"    … ще {len(lines) - MAX_OUTPUT_LINES} рядків")


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        # Консоль Windows може не знати якогось символу: підміняємо його, а не падаємо.
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Усі перевірки проєкту RiskUA.")
    parser.add_argument("--all", action="store_true", help="разом із тестами, яким потрібна база")
    full = parser.parse_args(argv).all
    steps = []
    for step in itertools.chain(static_steps(), pytest_steps(full, load_settings()["tests"])):
        print_step(step)
        steps.append(step)
    for note in check_limits.target_notes():
        print(f"орієнтир: {note}")
    failed = [step.name for step in steps if not step.ok]
    if failed:
        print(f"\nНе готово. Впали: {', '.join(failed)}.")
        return 1
    print("\nГотово: усі перевірки зелені." + ("" if full else " З базою: check.py --all"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
