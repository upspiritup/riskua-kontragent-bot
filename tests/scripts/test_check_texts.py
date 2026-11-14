"""Тести scripts/check_texts.py: кирилиця в domain/ і оцінні слова в текстах для користувача."""

from __future__ import annotations

import pytest

import check_texts

DOMAIN_FILE = "riskua/domain/rules/debts.py"


def problems(project, relative: str, source: str) -> list[str]:
    project.write(relative, source)
    return [p.message for p in check_texts.run(project.root) if p.path == relative]


def test_domain_string_with_cyrillic_fails(project):
    [message] = problems(project, DOMAIN_FILE, 'TITLE = "Борг"\n')
    assert "кирилицею" in message


def test_domain_fstring_with_cyrillic_fails(project):
    assert problems(project, DOMAIN_FILE, 'def f(x):\n    return f"борг {x}"\n')


def test_domain_docstrings_and_comments_may_be_ukrainian(project):
    source = (
        '"""Правила про борги."""\n\n'
        "# Поріг узято з правил.\n"
        "LIMIT = 1000\n\n\n"
        "def rule(case):\n"
        '    """Борг від порогу."""\n'
        '    return "tax_debt"\n'
    )
    assert problems(project, DOMAIN_FILE, source) == []


@pytest.mark.parametrize("relative", ["riskua/report/sections/debts.py", "riskua/bot/texts.py"])
def test_banned_words_in_user_texts(project, relative):
    [message] = problems(project, relative, 'TEXT = "Ознаки ШАХРАЙСТВА"\n')
    assert "шахра" in message


def test_banned_words_outside_user_texts_and_in_docstrings_are_fine(project):
    assert problems(project, "riskua/facts/courts.py", 'CATEGORY = "шахрайство"\n') == []
    docstring = '"""Тут не пишемо «шахрай»."""\n'
    assert problems(project, "riskua/report/sections/courts.py", docstring) == []
