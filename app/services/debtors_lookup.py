from __future__ import annotations

from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
import logging
import re
from typing import Any, Callable

from app.utils.validators import is_valid_edrpou


SOURCE = "debtors_registry"
SOURCE_UNAVAILABLE = "source_unavailable"
BASE_DEBTORS_URL = "https://erb.minjust.gov.ua/#/search-debtors"
BROWSER_TIMEOUT_MS = 15_000


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


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._skip_depth = 0
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(join_text(self._current_cell))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._current_cell is None:
            return
        text = normalize_text(data)
        if text:
            self._current_cell.append(text)


def build_debtors_result_url() -> str:
    return BASE_DEBTORS_URL


def fetch_debtors_registry(
    edrpou: str,
    fetcher: Callable[[str], str | dict[str, Any]] | None = None,
) -> dict:
    if not is_valid_edrpou(edrpou):
        return unavailable_result(edrpou, error="invalid_edrpou")

    if fetcher is None:
        return fetch_debtors_registry_with_browser(edrpou)

    try:
        page_data = fetcher(edrpou)
    except (TimeoutError, OSError) as exc:
        logging.info("Debtors registry unavailable for EDRPOU %s: %s", edrpou, exc)
        return unavailable_result(edrpou)

    return parse_debtors_results(page_data, edrpou)


def fetch_debtors_registry_with_browser(edrpou: str) -> dict:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return unavailable_result(edrpou)

    if not is_valid_edrpou(edrpou):
        return unavailable_result(edrpou, error="invalid_edrpou")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(BASE_DEBTORS_URL, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
                page.wait_for_load_state("networkidle", timeout=BROWSER_TIMEOUT_MS)

                if captcha_detected(page.content()):
                    return unavailable_result(edrpou)

                if not select_legal_entity(page):
                    return unavailable_result(edrpou)
                if not fill_edrpou_field(page, edrpou):
                    return unavailable_result(edrpou)
                if not click_search(page):
                    return unavailable_result(edrpou)

                page.wait_for_load_state("networkidle", timeout=BROWSER_TIMEOUT_MS)
                wait_for_results_or_empty_state(page)
                return parse_debtors_results(page.content(), edrpou)
            finally:
                browser.close()
    except (PlaywrightError, PlaywrightTimeoutError, TimeoutError, OSError) as exc:
        logging.info("Debtors registry browser lookup failed for EDRPOU %s: %s", edrpou, exc)
        return unavailable_result(edrpou)


def select_legal_entity(page: Any) -> bool:
    for label in ("Юридична особа", "Юридична особа - боржник"):
        try:
            option = page.get_by_text(label, exact=True)
            if option.count():
                option.first.click(timeout=3_000)
                return True
        except Exception:
            continue
    return False


def fill_edrpou_field(page: Any, edrpou: str) -> bool:
    labels = (
        "Ідентифікаційний код юридичної особи",
        "Код ЄДРПОУ",
        "ЄДРПОУ",
    )
    for label in labels:
        try:
            field = page.get_by_label(label)
            if field.count():
                field.first.fill(edrpou, timeout=3_000)
                return True
        except Exception:
            continue

    for selector in ("input[name*='code']", "input[id*='code']", "input[type='text']", "input"):
        try:
            field = page.locator(selector)
            if field.count():
                field.first.fill(edrpou, timeout=3_000)
                return True
        except Exception:
            continue
    return False


def click_search(page: Any) -> bool:
    try:
        button = page.get_by_role("button", name=re.compile("Шукати", re.IGNORECASE))
        if button.count():
            button.first.click(timeout=3_000)
            return True
    except Exception:
        pass

    try:
        button = page.get_by_text("Шукати", exact=True)
        if button.count():
            button.first.click(timeout=3_000)
            return True
    except Exception:
        pass
    return False


def wait_for_results_or_empty_state(page: Any) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const text = document.body ? document.body.innerText.toLowerCase() : "";
              return text.includes("нічого не знайдено")
                || text.includes("найменування")
                || text.includes("номер виконавчого провадження")
                || text.includes("captcha");
            }
            """,
            timeout=BROWSER_TIMEOUT_MS,
        )
    except Exception:
        return


def parse_debtors_results(html_or_page_data: str | dict[str, Any], edrpou: str) -> dict:
    if isinstance(html_or_page_data, dict):
        if html_or_page_data.get("source") == SOURCE and "checked" in html_or_page_data:
            return with_result_defaults(html_or_page_data, edrpou)
        if "html" in html_or_page_data:
            return parse_debtors_results(str(html_or_page_data.get("html") or ""), edrpou)
        if "items" in html_or_page_data:
            return build_result(edrpou, list(html_or_page_data.get("items") or []))

    html = str(html_or_page_data or "")
    text_parts = extract_visible_text(html)
    text = join_text(text_parts)
    if captcha_detected(text) or unavailable_detected(text):
        return unavailable_result(edrpou)

    rows = extract_table_rows(html)
    items = parse_table_items(rows, edrpou)
    if not items:
        if no_results_detected(text):
            return empty_result(edrpou)
        return unavailable_result(edrpou)

    return build_result(edrpou, items)


def parse_table_items(rows: list[list[str]], edrpou: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for cells in rows:
        if is_header_row(cells) or len(cells) < 4:
            continue

        debtor_name = cells[0]
        document_issuer = cells[1]
        proceeding_number = extract_proceeding_number(cells[2])
        collection_category = cells[3]
        raw_text = join_text(cells)
        if not (debtor_name or document_issuer or proceeding_number or collection_category):
            continue

        items.append(
            {
                "edrpou": edrpou,
                "debtor_name": debtor_name or None,
                "document_issuer": document_issuer or None,
                "enforcement_proceeding_number": proceeding_number,
                "collection_category": collection_category or None,
                "executor_details_available": executor_details_available(cells),
                "raw_text": None if all((debtor_name, document_issuer, proceeding_number, collection_category)) else raw_text,
            }
        )
    return items


def is_header_row(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return "найменування" in joined and "номер виконавчого провадження" in joined


def executor_details_available(cells: list[str]) -> bool:
    tail = " ".join(cells[4:]).lower() if len(cells) > 4 else ""
    return any(marker in tail for marker in ("виконавець", "переглянути", "деталі", "докладніше"))


def build_debtors_risk_flags(items: list[dict]) -> list[str]:
    flags: list[str] = []
    if items:
        flags.append("debtor_registry_found")
    if len(items) >= 3:
        flags.append("multiple_debtor_records")

    for item in items:
        classification = classify_debt_item(item)
        flags.extend(classification["risk_flags"])
    return unique(flags)


def classify_debt_item(item: dict) -> dict:
    category = str(item.get("collection_category") or "")
    issuer = str(item.get("document_issuer") or "")
    raw_text = str(item.get("raw_text") or "")
    classification = classify_debt_category(category)
    lowered_context = " ".join((category, issuer, raw_text)).lower()
    flags = list(classification["risk_flags"])
    level = classification["risk_level"]

    if contains_any(lowered_context, ("дпс", "гу дпс", "державна податкова служба")):
        flags.append("tax_debt_enforcement_found")
        level = "high"
    if contains_any(lowered_context, ("державний бюджет", "місцевий бюджет", "бюджет", "стягнення коштів")):
        flags.append("debt_collection_found")
        if level == "low":
            level = "high"

    return {
        "category": category,
        "risk_level": level,
        "risk_flags": unique(flags),
    }


def classify_debt_category(category: str) -> dict:
    lowered = category.lower()
    flags: list[str] = []
    level = "medium"

    if contains_any(lowered, ("судовий збір", "стягнення судового збору")):
        flags.append("court_fee_enforcement_found")
        level = "medium"
    if contains_any(lowered, ("заборгованості із заробітної плати", "заробітної плати", "зарплати")):
        flags.append("salary_debt_enforcement_found")
        level = "high"
    elif contains_any(lowered, ("податковий борг", "податкової заборгованості")):
        flags.append("tax_debt_enforcement_found")
        level = "high"
    elif contains_any(lowered, ("штраф", "пеня", "санкція")):
        flags.append("fine_or_penalty_enforcement_found")
        level = "medium"
    elif contains_any(lowered, ("стягнення коштів", "стягнення заборгованості", "борг", "заборгованість")):
        flags.append("debt_collection_found")
        level = "high"

    return {
        "category": category,
        "risk_level": level if flags else "low",
        "risk_flags": flags,
    }


def build_result(edrpou: str, items: list[dict[str, Any]]) -> dict:
    normalized_items = [normalize_item(item, edrpou) for item in items]
    risk_flags = build_debtors_risk_flags(normalized_items)
    return {
        "source": SOURCE,
        "checked": True,
        "found": bool(normalized_items),
        "url": BASE_DEBTORS_URL,
        "searched_edrpou": edrpou,
        "checked_at": checked_at(),
        "items_count": len(normalized_items),
        "unique_categories": unique(
            [
                item["collection_category"]
                for item in normalized_items
                if item.get("collection_category")
            ]
        ),
        "proceeding_numbers": unique(
            [
                item["enforcement_proceeding_number"]
                for item in normalized_items
                if item.get("enforcement_proceeding_number")
            ]
        ),
        "items": normalized_items,
        "signals": build_signals(normalized_items, risk_flags),
        "risk_flags": risk_flags,
        "error": None,
    }


def normalize_item(item: dict[str, Any], edrpou: str) -> dict[str, Any]:
    return {
        "edrpou": str(item.get("edrpou") or edrpou),
        "debtor_name": none_if_blank(item.get("debtor_name")),
        "document_issuer": none_if_blank(item.get("document_issuer")),
        "enforcement_proceeding_number": none_if_blank(item.get("enforcement_proceeding_number")),
        "collection_category": none_if_blank(item.get("collection_category")),
        "executor_details_available": bool(item.get("executor_details_available")),
        "raw_text": none_if_blank(item.get("raw_text")),
    }


def build_signals(items: list[dict[str, Any]], risk_flags: list[str]) -> list[str]:
    if not items:
        return []

    signals = [
        "Компанія знайдена в Єдиному реєстрі боржників",
        f"Знайдено {len(items)} записів у реєстрі боржників",
    ]
    if "salary_debt_enforcement_found" in risk_flags:
        signals.append("Є стягнення заборгованості із заробітної плати")
    if "court_fee_enforcement_found" in risk_flags:
        signals.append("Є стягнення судового збору")
    if "tax_debt_enforcement_found" in risk_flags:
        signals.append("Є податковий борг у виконавчому провадженні")
    return signals


def empty_result(edrpou: str) -> dict:
    return {
        "source": SOURCE,
        "checked": True,
        "found": False,
        "url": BASE_DEBTORS_URL,
        "searched_edrpou": edrpou,
        "checked_at": checked_at(),
        "items_count": 0,
        "unique_categories": [],
        "proceeding_numbers": [],
        "items": [],
        "signals": [],
        "risk_flags": [],
        "error": None,
    }


def unavailable_result(edrpou: str, *, error: str = SOURCE_UNAVAILABLE) -> dict:
    return {
        "source": SOURCE,
        "checked": False,
        "found": False,
        "url": BASE_DEBTORS_URL,
        "searched_edrpou": edrpou,
        "checked_at": checked_at(),
        "items_count": 0,
        "unique_categories": [],
        "proceeding_numbers": [],
        "items": [],
        "signals": [],
        "risk_flags": [SOURCE_UNAVAILABLE],
        "error": error,
    }


def with_result_defaults(result: dict[str, Any], edrpou: str) -> dict:
    if result.get("checked") is False or result.get("error") == SOURCE_UNAVAILABLE:
        return {**unavailable_result(edrpou, error=str(result.get("error") or SOURCE_UNAVAILABLE)), **result}
    if result.get("found"):
        return {**build_result(edrpou, list(result.get("items") or [])), **result}
    return {**empty_result(edrpou), **result}


def extract_visible_text(html: str) -> list[str]:
    parser = VisibleTextParser()
    parser.feed(html)
    return parser.parts


def extract_table_rows(html: str) -> list[list[str]]:
    parser = TableParser()
    parser.feed(html)
    return parser.rows


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


def join_text(values: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(value for value in values if value)).strip()


def extract_proceeding_number(text: str) -> str | None:
    match = re.search(r"\b\d{5,}\b", text or "")
    return match.group(0) if match else none_if_blank(text)


def none_if_blank(value: Any) -> str | None:
    text = normalize_text(str(value or ""))
    return text or None


def no_results_detected(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "нічого не знайдено",
            "записів не знайдено",
            "результатів не знайдено",
            "відсутні записи",
        )
    )


def captcha_detected(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("captcha", "капча", "перевірка безпеки"))


def unavailable_detected(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "service unavailable",
            "тимчасово недоступ",
            "доступ заборонено",
            "access denied",
        )
    )


def contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def checked_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
