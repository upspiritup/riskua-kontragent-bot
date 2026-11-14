"""Тести scripts/check_limits.py: кожна межа ловить порушення і пропускає код у межах.

Цифри беруться з pyproject.toml, тож тести не ламаються, коли межі змінюють.
"""

from __future__ import annotations

import check_limits
from _common import Problem, load_settings

LIMITS = load_settings()["limits"]


def assignments(count: int) -> str:
    """Файл рівно на count рядків коду."""
    return "".join(f"x{index} = {index}\n" for index in range(count))


def function(lines: int) -> str:
    """Функція рівно на lines рядків разом із def."""
    body = "".join(f"    x{index} = {index}\n" for index in range(lines - 1))
    return f"def f():\n{body}"


def nested(depth: int, inner: str = "return x") -> str:
    """Функція з depth вкладених if; inner — код на найглибшому рівні."""
    lines = ["def f(x):"]
    lines += ["    " * (level + 1) + f"if x > {level}:" for level in range(depth)]
    indent = "    " * (depth + 1)
    lines += [indent + line for line in inner.splitlines()]
    return "\n".join(lines) + "\n"


def problems(project) -> list[Problem]:
    return check_limits.run(project.root)


def test_file_at_limit_passes(project):
    project.write("riskua/ok.py", assignments(LIMITS["file_lines"]))
    assert problems(project) == []


def test_file_over_limit_fails(project):
    project.write("riskua/big.py", assignments(LIMITS["file_lines"] + 1))
    [problem] = problems(project)
    assert problem.path == "riskua/big.py"
    assert "поділіть за змістом" in problem.message


def test_sql_files_and_scripts_count_too(project):
    project.write("riskua/db/migrations/0001_big.sql", "SELECT 1;\n" * (LIMITS["file_lines"] + 1))
    project.write("scripts/big.py", assignments(LIMITS["file_lines"] + 1))
    paths = {problem.path for problem in problems(project)}
    assert paths == {"riskua/db/migrations/0001_big.sql", "scripts/big.py"}


def test_legacy_code_is_ignored(project):
    project.write("app/bot.py", assignments(LIMITS["file_lines"] * 3))
    project.write("tests/legacy/test_old.py", assignments(LIMITS["test_file_lines"] + 1))
    assert problems(project) == []


def test_file_exception_allows_bigger_file(project):
    project.write("riskua/big.py", assignments(LIMITS["file_lines"] + 5))
    project.add_file_exception("riskua/big.py", LIMITS["file_lines"] + 10, "один формат файла")
    assert problems(project) == []


def test_file_exception_needs_reason(project):
    project.write("riskua/big.py", assignments(LIMITS["file_lines"] + 5))
    project.add_file_exception("riskua/big.py", LIMITS["file_lines"] + 10, " ")
    [problem] = problems(project)
    assert "без причини" in problem.message


def test_needless_exceptions_fail(project):
    project.write("riskua/small.py", assignments(3))
    project.add_file_exception("riskua/small.py", LIMITS["file_lines"] + 10, "причина")
    project.add_file_exception("riskua/gone.py", LIMITS["file_lines"] + 10, "причина")
    messages = [problem.message for problem in problems(project)]
    assert any("не потрібен" in message for message in messages)
    assert any("файла немає" in message for message in messages)


def test_exception_budget(project):
    for index in range(LIMITS["file_exceptions"] + 1):
        relative = f"riskua/big{index}.py"
        project.write(relative, assignments(LIMITS["file_lines"] + 1))
        project.add_file_exception(relative, LIMITS["file_lines"] + 10, "причина")
    [problem] = problems(project)
    assert "бюджет" in problem.message


def test_function_length(project):
    project.write("riskua/ok.py", function(LIMITS["function_lines"]))
    project.write("riskua/long.py", function(LIMITS["function_lines"] + 1))
    [problem] = problems(project)
    assert problem.path == "riskua/long.py"
    assert "функція f" in problem.message


def test_nesting_at_limit_passes(project):
    project.write("riskua/ok.py", nested(LIMITS["nesting_depth"]))
    assert problems(project) == []


def test_nesting_over_limit_is_reported_once(project):
    project.write("riskua/deep.py", nested(LIMITS["nesting_depth"] + 2))
    [problem] = problems(project)
    # Рядок 1 — def, далі по одному if на рядок: перший зайвий рівень — на рядку межа + 2.
    assert problem.line == LIMITS["nesting_depth"] + 2


def test_elif_does_not_add_depth(project):
    chain = "if x == 1:\n    return 1\nelif x == 2:\n    return 2\nelif x == 3:\n    return 3"
    project.write("riskua/chain.py", nested(LIMITS["nesting_depth"] - 1, chain))
    assert problems(project) == []


def test_if_inside_else_adds_depth(project):
    inner = "if x == 1:\n    return 1\nelse:\n    if x == 2:\n        return 2"
    project.write("riskua/else_if.py", nested(LIMITS["nesting_depth"] - 1, inner))
    [problem] = problems(project)
    assert "вкладеність" in problem.message


def test_try_and_loops_count_as_blocks(project):
    inner = "try:\n    for item in x:\n        pass\nexcept ValueError:\n    pass"
    project.write("riskua/loops.py", nested(LIMITS["nesting_depth"] - 1, inner))
    [problem] = problems(project)
    assert problem.line == LIMITS["nesting_depth"] + 2


def test_nested_function_starts_new_count(project):
    inner = "def g(y):\n    if y:\n        return y\nreturn g"
    project.write("riskua/closure.py", nested(LIMITS["nesting_depth"], inner))
    assert problems(project) == []


def test_suppression_needs_reason_above(project):
    project.write("riskua/bare.py", "import os  # noqa: F401\n")
    explained = "# Причина: модуль потрібен заради побічного ефекту.\nimport os  # noqa: F401\n"
    project.write("riskua/explained.py", explained)
    [problem] = problems(project)
    assert problem.path == "riskua/bare.py"
    assert "причиною" in problem.message


def test_type_ignore_is_a_suppression(project):
    project.write("riskua/typed.py", "x = 1\ny: str = x  # type: ignore[assignment]\n")
    [problem] = problems(project)
    assert problem.line == 2


def test_noqa_inside_string_is_not_a_suppression(project):
    project.write("riskua/text.py", 'HINT = "add # noqa: E501 to silence"\n')
    assert problems(project) == []


def test_suppression_budget(project):
    count = LIMITS["suppressions"] + 1
    source = "".join(f"# Причина {index}.\nx{index} = 1  # noqa: E501\n" for index in range(count))
    project.write("riskua/many.py", source)
    [problem] = problems(project)
    assert "бюджет" in problem.message


def test_test_file_limit(project):
    project.write("tests/core/test_ok.py", assignments(LIMITS["test_file_lines"]))
    project.write("tests/core/test_big.py", assignments(LIMITS["test_file_lines"] + 1))
    [problem] = problems(project)
    assert problem.path == "tests/core/test_big.py"


def test_fixture_size_limit(project):
    project.write("tests/fixtures/edr/sample.xml", "x" * (LIMITS["fixture_kb"] * 1024 + 1))
    project.write("tests/fixtures/edr/small.xml", "x" * 100)
    [problem] = problems(project)
    assert problem.path == "tests/fixtures/edr/sample.xml"


def test_target_notes_do_not_fail(project):
    target = LIMITS["file_lines_target"]
    project.write("riskua/mid.py", assignments(target + 1))
    project.write("riskua/small.py", assignments(target))
    notes = check_limits.target_notes(project.root)
    assert notes == [f"riskua/mid.py: {target + 1} рядків, орієнтир {target}"]
    assert problems(project) == []
