from __future__ import annotations

import logging
import re
from html import unescape
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.utils.validators import is_valid_edrpou


BASE_YOUCONTROL_URL = "https://youcontrol.com.ua/catalog/company_details/{edrpou}/"
HTTP_TIMEOUT_SECONDS = 8.0
SOURCE = "youcontrol"
BLOCKED_OR_UNAVAILABLE = "blocked_or_unavailable"
COMPANY_NOT_FOUND = "company_not_found"


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = normalize_text(data)
        if text:
            self.parts.append(text)


def build_youcontrol_url(edrpou: str) -> str:
    return BASE_YOUCONTROL_URL.format(edrpou=edrpou)


def fetch_youcontrol_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_youcontrol_company(
    edrpou: str,
    fetcher: Callable[[str], str] = fetch_youcontrol_page,
) -> dict:
    url = build_youcontrol_url(edrpou)
    if not is_valid_edrpou(edrpou):
        return empty_result(edrpou, url=url, error="invalid_edrpou")

    try:
        html = fetcher(url)
    except HTTPError as exc:
        close_error_response(exc)
        if exc.code == 404:
            return empty_result(edrpou, url=url, error=COMPANY_NOT_FOUND, risk_flags=[COMPANY_NOT_FOUND])
        logging.info("YouControl unavailable for EDRPOU %s: HTTP %s", edrpou, exc.code)
        return empty_result(edrpou, url=url, error=BLOCKED_OR_UNAVAILABLE)
    except (URLError, TimeoutError, OSError) as exc:
        logging.info("YouControl unavailable for EDRPOU %s: %s", edrpou, exc)
        return empty_result(edrpou, url=url, error=BLOCKED_OR_UNAVAILABLE)

    return parse_youcontrol_page(html, edrpou, url)


def close_error_response(error: HTTPError) -> None:
    try:
        error.close()
    except OSError:
        pass


def parse_youcontrol_page(html: str, edrpou: str, url: str) -> dict:
    parts = extract_visible_text(html)
    text = join_text(parts)
    if is_blocked_page(text, html):
        return empty_result(edrpou, url=url, error=BLOCKED_OR_UNAVAILABLE)
    if is_not_found_page(text):
        return empty_result(edrpou, url=url, error=COMPANY_NOT_FOUND, risk_flags=[COMPANY_NOT_FOUND])

    page_edrpou = extract_page_edrpou(parts) or edrpou
    if page_edrpou != edrpou:
        return empty_result(edrpou, url=url, error="edrpou_mismatch", risk_flags=["data_mismatch_between_sources"])

    company = {
        "name": extract_company_name(parts),
        "edrpou": page_edrpou,
        "status": extract_field(parts, ("Статус", "Стан", "Статус компанії")),
        "registration_date": extract_field(parts, ("Дата реєстрації", "Дата заснування")),
        "address": extract_multiline_field(parts, ("Адреса", "Місцезнаходження")),
        "director": extract_field(parts, ("Керівник", "Директор")),
        "phone": extract_field(parts, ("Телефон", "Тел.", "Контактний телефон")),
        "email": extract_field(parts, ("Email", "E-mail", "Електронна пошта")),
        "website": extract_field(parts, ("Сайт", "Вебсайт", "Офіційний сайт")),
        "main_kved": extract_field(parts, ("Основний КВЕД", "Основний вид діяльності")),
        "additional_kveds": extract_additional_kveds(parts),
    }
    if not (company["name"] or company["status"] or company["address"] or company["director"]):
        return empty_result(edrpou, url=url, error="html_structure_not_recognized")

    signals = build_signals(parts, text)
    risk_flags = build_risk_flags(company, signals, text)

    return {
        "source": SOURCE,
        "found": True,
        "url": url,
        "company": company,
        "signals": signals,
        "risk_flags": risk_flags,
        "raw_text_excerpt": text[:700] or None,
        "error": None,
    }


def empty_result(
    edrpou: str,
    *,
    url: str,
    error: str,
    risk_flags: list[str] | None = None,
) -> dict:
    return {
        "source": SOURCE,
        "found": False,
        "url": url,
        "company": {
            "name": None,
            "edrpou": edrpou,
            "status": None,
            "registration_date": None,
            "address": None,
            "director": None,
            "phone": None,
            "email": None,
            "website": None,
            "main_kved": None,
            "additional_kveds": [],
        },
        "signals": [],
        "risk_flags": risk_flags or [],
        "raw_text_excerpt": None,
        "error": error,
    }


def extract_visible_text(html: str) -> list[str]:
    parser = VisibleTextParser()
    parser.feed(html)
    return parser.parts


def normalize_text(text: str) -> str:
    cleaned = (
        unescape(text)
        .replace("\xa0", " ")
        .replace("\u00ad", "")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def join_text(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def is_blocked_page(text: str, html: str) -> bool:
    lowered = f"{text} {html}".lower()
    return any(
        marker in lowered
        for marker in (
            "captcha",
            "cloudflare",
            "cf-chl",
            "just a moment",
            "access denied",
            "checking your browser",
            "перевірка браузера",
        )
    )


def is_not_found_page(text: str) -> bool:
    lowered = text.lower()
    return (
        "компанію не знайдено" in lowered
        or "компанія не знайдена" in lowered
        or "за вашим запитом нічого не знайдено" in lowered
        or "нічого не знайдено" in lowered
    )


def extract_page_edrpou(parts: list[str]) -> str | None:
    labelled = extract_field(parts[:80], ("Код ЄДРПОУ", "ЄДРПОУ", "ЕДРПОУ"))
    if labelled:
        match = re.search(r"\b\d{8}\b", labelled)
        if match:
            return match.group(0)
    match = re.search(r"(?:Код ЄДРПОУ|ЄДРПОУ|ЕДРПОУ)\D{0,30}(\d{8})", join_text(parts[:80]), re.IGNORECASE)
    return match.group(1) if match else None


def extract_company_name(parts: list[str]) -> str | None:
    labelled = extract_field(parts, ("Назва", "Повна назва", "Найменування"))
    if labelled:
        return labelled
    for part in parts[:20]:
        if is_likely_company_name(part):
            return part
    return None


def extract_field(parts: list[str], labels: tuple[str, ...]) -> str | None:
    for index, part in enumerate(parts):
        for label in labels:
            if part == label or part.rstrip(":") == label:
                return next_value(parts, index + 1)
            prefix = f"{label}:"
            if part.startswith(prefix):
                value = normalize_text(part[len(prefix) :])
                if value:
                    return value
    return None


def extract_multiline_field(parts: list[str], labels: tuple[str, ...]) -> str | None:
    for index, part in enumerate(parts):
        for label in labels:
            if part == label or part.rstrip(":") == label:
                values = values_until_next_label(parts, index + 1)
                if values:
                    return join_text(values)
            prefix = f"{label}:"
            if part.startswith(prefix):
                value = normalize_text(part[len(prefix) :])
                if value:
                    return value
    return None


def next_value(parts: list[str], start_index: int) -> str | None:
    for candidate in parts[start_index:]:
        if candidate and not is_label(candidate):
            return candidate
    return None


def values_until_next_label(parts: list[str], start_index: int) -> list[str]:
    values: list[str] = []
    for candidate in parts[start_index : start_index + 8]:
        if is_label(candidate):
            break
        if candidate:
            values.append(candidate)
    return values


def extract_additional_kveds(parts: list[str]) -> list[str]:
    value = extract_multiline_field(parts, ("Додаткові КВЕДи", "Додаткові види діяльності", "Інші види діяльності"))
    if not value:
        return []
    return [item.strip() for item in re.split(r";|,\s*(?=\d{2}\.\d{2})", value) if item.strip()]


def is_label(text: str) -> bool:
    return text.rstrip(":") in {
        "Назва",
        "Повна назва",
        "Найменування",
        "Код ЄДРПОУ",
        "ЄДРПОУ",
        "Статус",
        "Стан",
        "Статус компанії",
        "Дата реєстрації",
        "Дата заснування",
        "Адреса",
        "Місцезнаходження",
        "Керівник",
        "Директор",
        "Телефон",
        "Тел.",
        "Контактний телефон",
        "Email",
        "E-mail",
        "Електронна пошта",
        "Сайт",
        "Вебсайт",
        "Офіційний сайт",
        "Основний КВЕД",
        "Основний вид діяльності",
        "Додаткові КВЕДи",
        "Додаткові види діяльності",
        "Інші види діяльності",
        "Судові справи",
        "Судові згадки",
        "Виконавчі провадження",
        "Податковий борг",
        "Ризикові попередження",
    }


def is_likely_company_name(text: str) -> bool:
    upper = text.upper()
    return (
        re.search(r"(^|\s)(ТОВ|ПП|АТ|ПРАТ|ПАТ|ФОП)(\s|«|\"|$)", upper) is not None
        or "КОМПАН" in upper
        or "ПІДПРИЄМ" in upper
    )


def build_signals(parts: list[str], text: str) -> list[str]:
    signals: list[str] = []
    court_count = extract_count(parts, ("Судові справи", "Судові згадки"))
    enforcement_count = extract_count(parts, ("Виконавчі провадження",))
    tax_debt = detect_bool_signal(text, ("податковий борг",), positive=("наяв", "вияв"), negative=("відсут", "немає", "не має", "не вияв"))
    bankruptcy = detect_bool_signal(
        text,
        ("банкрутство", "банкрут"),
        positive=("наяв", "вияв", "поруш", "відкрит"),
        negative=("відсут", "немає", "не має", "не вияв", "не знайден"),
    )
    if court_count is not None:
        signals.append(f"Судові справи: {court_count}")
    if enforcement_count is not None:
        signals.append(f"Виконавчі провадження: {enforcement_count}")
    if tax_debt is not None:
        signals.append(f"Податковий борг: {'наявний' if tax_debt else 'відсутній'}")
    if bankruptcy is not None:
        signals.append(f"Банкрутство: {'виявлено' if bankruptcy else 'не виявлено'}")
    warnings = extract_multiline_field(parts, ("Ризикові попередження",))
    if warnings:
        signals.append(f"Ризикові попередження: {warnings}")
    return signals


def build_risk_flags(company: dict, signals: list[str], text: str) -> list[str]:
    flags: list[str] = []
    status = (company.get("status") or "").lower()
    lowered = text.lower()
    safe_status = safe_lifecycle_context(status)
    safe_text = safe_lifecycle_context(lowered)
    if status and "зареєстр" not in status and not safe_status:
        flags.append("suspicious_status")
    if is_positive_termination_status(status) or (not safe_text and has_positive_termination_context(lowered)):
        flags.append("company_in_termination")
    if is_positive_inactive_status(status) or (not safe_text and has_positive_inactive_context(lowered)):
        flags.append("company_inactive")
    if has_confirmed_bankruptcy_context(lowered):
        flags.append("bankruptcy_found")
    for signal in signals:
        lowered_signal = signal.lower()
        if lowered_signal.startswith("податковий борг: наяв"):
            flags.append("tax_debt_found")
        if lowered_signal.startswith("банкрутство: вияв"):
            flags.append("bankruptcy_found")
        if lowered_signal.startswith("судові справи:") and parse_first_int(signal):
            flags.append("court_cases_found")
        if lowered_signal.startswith("виконавчі провадження:") and parse_first_int(signal):
            flags.append("enforcement_found")
        if lowered_signal.startswith("ризикові попередження:"):
            flags.append("suspicious_status")
    return unique(flags)


def extract_count(parts: list[str], labels: tuple[str, ...]) -> int | None:
    for index, part in enumerate(parts):
        if any(part == label or part.rstrip(":") == label for label in labels):
            return next_numeric_value(parts, index + 1)
        for label in labels:
            if part.startswith(f"{label}:") or part.startswith(f"{label} ("):
                return parse_first_int(part)
    return None


def next_numeric_value(parts: list[str], start_index: int) -> int | None:
    for candidate in parts[start_index : start_index + 4]:
        if is_label(candidate):
            return None
        value = parse_first_int(candidate)
        if value is not None:
            return value
    return None


def parse_first_int(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"\d+", text.replace(" ", ""))
    return int(match.group(0)) if match else None


def detect_bool_signal(
    text: str,
    keywords: tuple[str, ...],
    *,
    positive: tuple[str, ...],
    negative: tuple[str, ...],
) -> bool | None:
    lowered = text.lower()
    for keyword in keywords:
        keyword_index = lowered.find(keyword)
        if keyword_index == -1:
            continue
        forward_window = lowered[keyword_index : keyword_index + 140]
        prefix_window = lowered[max(0, keyword_index - 40) : keyword_index]
        if any(marker in forward_window for marker in negative) or any(
            marker in prefix_window for marker in ("не має", "немає")
        ):
            return False
        if any(marker in forward_window for marker in positive):
            return True
    return None


def has_positive_signal(text: str, keyword: str) -> bool:
    index = text.find(keyword)
    if index == -1:
        return False
    window = text[index : index + 160]
    return not any(marker in window for marker in ("відсут", "немає", "не знайден", "не вияв", "не має"))


def has_confirmed_bankruptcy_context(text: str) -> bool:
    lowered = text or ""
    if has_bankruptcy_negative_context(lowered):
        return False
    return any(
        phrase in lowered
        for phrase in (
            "перебуває у процедурі банкрутства",
            "перебуває в процедурі банкрутства",
            "порушено справу про банкрутство",
            "відкрито провадження про банкрутство",
            "відкрите провадження про банкрутство",
            "визнано банкрутом",
            "боржника банкрутом",
            "неплатоспроможність",
        )
    )


def has_bankruptcy_negative_context(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        phrase in lowered
        for phrase in (
            "банкрутство не виявлено",
            "банкрутство відсут",
            "банкрутство не знайдено",
            "справи про банкрутство відсут",
            "відомості про банкрутство відсут",
        )
    )


def safe_negative_context(text: str) -> bool:
    lowered = (text or "").lower()
    return safe_lifecycle_context(lowered) or any(
        pattern in lowered
        for pattern in (
            "банкрутство не виявлено",
            "банкрутство відсут",
            "податковий борг відсут",
            "податковий борг не вияв",
            "виконавчі провадження відсут",
            "виконавчі провадження не вияв",
            "борг єсв відсут",
        )
    )


def safe_lifecycle_context(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        pattern in lowered
        for pattern in (
            "не перебуває в процесі припинення",
            "не перебуває у процесі припинення",
            "не перебуває в стані припинення",
            "не перебуває у стані припинення",
            "відомості про припинення відсутні",
            "припинення відсут",
            "статус: зареєстровано",
            "статус зареєстровано",
            "не анульовано",
            "не анульована",
            "анульовані записи відсут",
            "анульованих записів відсут",
        )
    )


def safe_termination_context(text: str) -> bool:
    return safe_lifecycle_context(text)


def is_positive_termination_status(status: str) -> bool:
    lowered = status or ""
    if safe_lifecycle_context(lowered) or "зареєстр" in lowered:
        return False
    return any(marker in lowered for marker in ("припинен", "припинення"))


def is_positive_inactive_status(status: str) -> bool:
    lowered = status or ""
    if safe_lifecycle_context(lowered) or "зареєстр" in lowered:
        return False
    return any(marker in lowered for marker in ("ліквід", "неактив", "анульован"))


def has_positive_termination_context(text: str) -> bool:
    lowered = text or ""
    return any(
        pattern in lowered
        for pattern in (
            "перебуває в процесі припинення",
            "перебуває у процесі припинення",
            "перебуває в стані припинення",
            "перебуває у стані припинення",
            "порушено процедуру припинення",
        )
    )


def has_positive_inactive_context(text: str) -> bool:
    lowered = text or ""
    return any(
        pattern in lowered
        for pattern in (
            "компанія ліквідована",
            "юридичну особу ліквідовано",
            "статус: ліквідовано",
            "статус ліквідовано",
            "статус: неактивна",
            "статус неактивна",
            "статус: анульовано",
            "статус анульовано",
        )
    )


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
