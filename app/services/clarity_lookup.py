from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models.clarity import (
    ClarityCompany,
    ClarityData,
    ClarityRiskFlag,
    ClaritySignals,
    ClarityTax,
)
from app.utils.validators import is_valid_edrpou


BASE_CLARITY_URL = "https://clarity-project.info/edr/{edrpou}"
BASE_CLARITY_API_URL = "https://clarity-project.info/api/edr.info/{edrpou}"
CLARITY_API_KEY_ENV = "CLARITY_API_KEY"
HTTP_TIMEOUT_SECONDS = 8.0
FOUND = "found"
NOT_FOUND = "not_found"
SOURCE_ERROR = "source_error"
PARSE_ERROR = "parse_error"
PARTIAL = "partial"
LARGE_CLARITY_TAX_DEBT_THRESHOLD_UAH = 100_000.0
EDRPOU_MARKER_LABELS = {"ЄДРПОУ", "ЕДРПОУ", "КОД ЄДРПОУ"}
EDRPOU_HEADER_STOP_LABELS = {
    "Податки",
    "Сигнали",
    "Пов'язані компанії",
    "Пов’язані компанії",
    "Судові справи",
    "Виконавчі провадження",
    "Перевірки",
    "Ліцензії",
    "Prozorro",
}
COUNT_SIGNAL_LABELS = (
    "Банкрутство",
    "Банкрутства",
    "Виконавчі провадження",
    "Виконавче провадження",
    "Перевірки",
    "Інспекції",
    "Історія ЄДР",
    "Історія змін ЄДР",
    "Ліцензії",
    "Ліцензування",
    "Prozorro.Sale",
    "Prozorro",
    "Продажі Prozorro",
)


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


def build_clarity_url(edrpou: str) -> str:
    return BASE_CLARITY_URL.format(edrpou=edrpou)


def build_clarity_api_url(edrpou: str, api_key: str) -> str:
    query = urlencode({"key": api_key})
    return f"{BASE_CLARITY_API_URL.format(edrpou=edrpou)}?{query}"


def fetch_clarity_page(url: str) -> str:
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


def fetch_clarity_api_json(url: str) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        raw_body = response.read().decode(charset, errors="replace")
    payload = json.loads(raw_body)
    return payload if isinstance(payload, Mapping) else {}


def lookup_clarity_by_edrpou(
    edrpou: str,
    fetcher: Callable[[str], str] = fetch_clarity_page,
    api_fetcher: Callable[[str], Mapping[str, Any]] = fetch_clarity_api_json,
) -> ClarityData:
    source_url = build_clarity_url(edrpou)
    if not is_valid_edrpou(edrpou):
        return ClarityData(
            source_url=source_url,
            status=SOURCE_ERROR,
            edrpou=edrpou,
            error="invalid_edrpou",
        )

    api_key = os.environ.get(CLARITY_API_KEY_ENV, "").strip()
    if api_key:
        try:
            payload = api_fetcher(build_clarity_api_url(edrpou, api_key))
        except HTTPError as exc:
            close_error_response(exc)
            if exc.code == 404:
                return ClarityData(
                    source_url=source_url,
                    status=NOT_FOUND,
                    edrpou=edrpou,
                )
            return ClarityData(
                source_url=source_url,
                status=SOURCE_ERROR,
                edrpou=edrpou,
                error=f"clarity_api_http_{exc.code}",
            )
        except (json.JSONDecodeError, URLError, TimeoutError, OSError, ValueError):
            return ClarityData(
                source_url=source_url,
                status=SOURCE_ERROR,
                edrpou=edrpou,
                error="clarity_api_source_error",
            )
        return parse_clarity_api_payload(payload, edrpou, source_url)

    try:
        html = fetcher(source_url)
    except HTTPError as exc:
        close_error_response(exc)
        if exc.code == 404:
            return ClarityData(
                source_url=source_url,
                status=NOT_FOUND,
                edrpou=edrpou,
            )
        return ClarityData(
            source_url=source_url,
            status=SOURCE_ERROR,
            edrpou=edrpou,
            error=str(exc),
        )
    except (URLError, TimeoutError, OSError) as exc:
        return ClarityData(
            source_url=source_url,
            status=SOURCE_ERROR,
            edrpou=edrpou,
            error=str(exc),
        )

    return parse_clarity_page(html, edrpou, source_url)


def parse_clarity_api_payload(payload: Mapping[str, Any], edrpou: str, source_url: str) -> ClarityData:
    error = payload.get("error")
    if isinstance(error, Mapping):
        code = clean_api_error_code(error.get("code"))
        return ClarityData(
            source_url=source_url,
            status=SOURCE_ERROR,
            edrpou=edrpou,
            error=f"clarity_api_{code}",
        )

    payload_edrpou = normalize_api_edrpou(
        first_api_value(
            payload,
            "edr",
            "Edr",
            "edrpou",
            "EDRPOU",
        )
        or first_api_value(api_mapping(payload.get("edr_data")), "edr", "Edr", "edrpou")
    )
    if payload_edrpou and payload_edrpou != edrpou:
        return ClarityData(
            source_url=source_url,
            status=PARSE_ERROR,
            edrpou=edrpou,
            error="edrpou_mismatch",
        )

    company = parse_api_company(payload)
    if company is None:
        return ClarityData(
            source_url=source_url,
            status=PARSE_ERROR,
            edrpou=edrpou,
            error="company_name_missing",
            parse_warnings=["Не вдалося визначити назву компанії у Clarity API"],
        )

    tax = parse_api_tax(payload)
    signals = parse_api_signals(payload)
    return ClarityData(
        source_url=source_url,
        status=FOUND,
        edrpou=edrpou,
        company=company,
        tax=tax,
        signals=signals,
        risk_flags=build_risk_flags(company, tax, signals),
    )


def parse_clarity_page(html: str, edrpou: str, source_url: str) -> ClarityData:
    parts = extract_visible_text(html)
    text = " ".join(parts)
    parse_warnings: list[str] = []
    if is_not_found_page(text, edrpou):
        return ClarityData(
            source_url=source_url,
            status=NOT_FOUND,
            edrpou=edrpou,
        )

    page_edrpou = extract_page_edrpou(parts)
    if page_edrpou and page_edrpou != edrpou:
        return ClarityData(
            source_url=source_url,
            status=PARSE_ERROR,
            edrpou=edrpou,
            parse_warnings=[f"ЄДРПОУ у відповіді Clarity не збігається із запитом: {page_edrpou}"],
            error="edrpou_mismatch",
        )

    company = parse_company(parts, parse_warnings)
    tax = parse_tax(text, parse_warnings)
    signals = parse_signals(parts, parse_warnings)
    if company is None:
        return ClarityData(
            source_url=source_url,
            status=PARSE_ERROR,
            edrpou=edrpou,
            parse_warnings=parse_warnings or ["Не вдалося розпізнати блок компанії Clarity"],
            error="html_structure_not_recognized",
        )

    status = FOUND
    if parse_warnings:
        status = PARTIAL

    return ClarityData(
        source_url=source_url,
        status=status,
        edrpou=edrpou,
        company=company,
        tax=tax,
        signals=signals,
        risk_flags=build_risk_flags(company, tax, signals),
        parse_warnings=parse_warnings,
    )


def close_error_response(error: HTTPError) -> None:
    try:
        error.close()
    except OSError:
        pass


def parse_api_company(payload: Mapping[str, Any]) -> ClarityCompany | None:
    edr_data = api_mapping(payload.get("edr_data"))
    contact = api_mapping(payload.get("contact"))
    contacts = api_mapping(first_api_value(edr_data, "contacts", "contact"))
    name = first_string(
        first_api_value(edr_data, "name", "Name"),
        first_api_value(edr_data, "shortName", "short_name"),
        first_api_value(payload, "name", "Name"),
    )
    if not name:
        return None

    company = ClarityCompany(
        name=name,
        status=first_string(
            first_api_value(edr_data, "statusName", "status_name"),
            first_api_value(edr_data, "status", "Status"),
            first_api_value(payload, "status", "Status"),
        ),
        registration_date=parse_api_date(
            first_api_value(edr_data, "registration", "Registration", "registered_at", "registration_date")
        ),
        director=extract_api_director(edr_data),
        website=first_string(
            first_api_value(contacts, "web", "website", "url"),
            first_api_value(contact, "web", "website", "url"),
        ),
        statutory_capital_uah=parse_api_money(first_api_value(edr_data, "capital", "Capital")),
        main_activity=format_api_activity(first_api_value(edr_data, "activity", "activities", "Activity")),
    )
    return company


def parse_api_tax(payload: Mapping[str, Any]) -> ClarityTax:
    tax_debt_value = first_api_value(payload, "tax_debt", "taxDebt", "TaxDebt")
    tax_debt_mapping = api_mapping(tax_debt_value)
    tax_debt_amount = first_api_number(
        tax_debt_value,
        first_api_value(tax_debt_mapping, "amount", "sum", "total", "debt", "tax_debt_amount_uah"),
    )
    tax_debt = api_bool(tax_debt_value)
    if tax_debt_amount is not None:
        tax_debt = tax_debt_amount > 0

    esv_debt_value = first_api_value(payload, "esv_debt", "esvDebt", "unified_social_tax_debt")
    return ClarityTax(
        tax_debt=tax_debt,
        tax_debt_amount_uah=tax_debt_amount,
        tax_debt_as_of=first_string(
            first_api_value(tax_debt_mapping, "actual_date", "as_of", "date", "updated", "updated_at")
        ),
        esv_debt=api_bool(esv_debt_value),
        vat_active=api_bool(first_api_value(payload, "vat_active", "vatActive", "is_vat_payer")),
        single_tax_active=api_bool(first_api_value(payload, "single_tax_active", "singleTaxActive", "is_single_tax_payer")),
    )


def parse_api_signals(payload: Mapping[str, Any]) -> ClaritySignals:
    return ClaritySignals(
        bankruptcy_count=api_count(
            first_api_value(payload, "bankruptcy_count", "bankruptcies_count", "bankruptcy", "bankruptcies")
        ),
        enforcement_proceedings_count=api_count(
            first_api_value(
                payload,
                "enforcement_proceedings_count",
                "executive_proceedings_count",
                "enforcements_count",
                "enforcements",
            )
        ),
        inspections_count=api_count(first_api_value(payload, "inspections_count", "inspections")),
        edr_history_count=api_count(first_api_value(payload, "history", "history_count", "edr_history_count")),
        licenses_count=api_count(first_api_value(payload, "licenses_count", "licenses")),
        prozorro_sales_count=api_count(first_api_value(payload, "prozorro_sales_count", "prozorro_sales")),
    )


def extract_api_director(edr_data: Mapping[str, Any]) -> str | None:
    direct_value = first_string(
        first_api_value(edr_data, "director", "head", "manager", "chief"),
    )
    if direct_value:
        return direct_value

    signers = first_api_value(edr_data, "signers", "Signers")
    if isinstance(signers, list):
        for signer in signers:
            signer_mapping = api_mapping(signer)
            name = first_string(first_api_value(signer_mapping, "name", "Name", "person", "Person"))
            if name:
                return name
    return None


def format_api_activity(value: Any) -> str | None:
    if isinstance(value, list):
        candidates = [api_mapping(item) for item in value]
        selected = next(
            (
                item
                for item in candidates
                if api_bool(first_api_value(item, "is_primary", "primary", "main", "isMain")) is True
            ),
            candidates[0] if candidates else {},
        )
        return format_api_activity(selected)
    if isinstance(value, Mapping):
        code = first_string(first_api_value(value, "code", "Code", "KVED", "kved"))
        name = first_string(first_api_value(value, "name", "Name", "text", "Text"))
        if code and name:
            return f"{code} {name}"
        return code or name
    return first_string(value)


def parse_api_date(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return parse_api_date(first_api_value(value, "date", "Date", "timestamp", "registered_at"))
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC).strftime("%d.%m.%Y")
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() and len(stripped) >= 9:
            return datetime.fromtimestamp(int(stripped), UTC).strftime("%d.%m.%Y")
        return stripped or None
    return None


def parse_api_money(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Mapping):
        return parse_api_money(first_api_value(value, "amount", "value", "sum"))
    if isinstance(value, str):
        return parse_money(value)
    return None


def first_api_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            parsed = parse_money(value)
            if parsed is not None:
                return parsed
        if isinstance(value, Mapping):
            parsed = first_api_number(
                first_api_value(value, "amount", "value", "sum", "total", "debt", "tax_debt_amount_uah")
            )
            if parsed is not None:
                return parsed
    return None


def api_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        return parse_first_int(value)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, Mapping):
        direct = first_api_value(value, "count", "total", "total_found", "value")
        if direct is not None and direct is not value:
            return api_count(direct)
        return len(value) if value else None
    return None


def api_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, Mapping):
        direct = first_api_value(value, "has_debt", "exists", "active", "value", "amount", "sum", "total", "debt")
        if direct is not None and direct is not value:
            return api_bool(direct)
        return True if value else None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if not lowered:
            return None
        if lowered in {"0", "false", "no", "ні", "none", "null"}:
            return False
        if any(marker in lowered for marker in ("відсут", "немає", "не має", "не вияв")):
            return False
        if lowered in {"1", "true", "yes", "так"} or any(marker in lowered for marker in ("наяв", "актив", "вияв")):
            return True
    return None


def api_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def first_api_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    if not mapping:
        return None
    for key in keys:
        if key in mapping:
            return mapping[key]
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            stripped = normalize_text(value)
            if stripped:
                return stripped
        elif isinstance(value, (int, float)):
            return str(value)
    return None


def normalize_api_edrpou(value: Any) -> str | None:
    if value is None:
        return None
    match = re.search(r"\b\d{8}\b", str(value))
    return match.group(0) if match else None


def clean_api_error_code(value: Any) -> str:
    if value is None:
        return "error"
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value).strip())
    return normalized or "error"


def is_not_found_page(text: str, edrpou: str) -> bool:
    lowered = text.lower()
    return (
        "за запитом нічого не знайдено" in lowered
        or "нічого не знайдено" in lowered
        or "інформацію не знайдено" in lowered
        or "компанію не знайдено" in lowered
        or "компанія не знайдена" in lowered
        or f"єдрпоу {edrpou} не знайдено" in lowered
        or f"код {edrpou} не знайдено" in lowered
    )


def parse_company(parts: list[str], parse_warnings: list[str]) -> ClarityCompany | None:
    name = extract_name(parts)
    company = ClarityCompany(
        name=name,
        status=extract_field(parts, ("Стан", "Статус")),
        registration_date=extract_field(parts, ("Дата реєстрації", "Дата заснування")),
        director=extract_director(parts),
        statutory_capital_uah=parse_money(extract_field(parts, ("Статутний капітал",))),
        main_activity=extract_field(parts, ("Основний КВЕД", "Основний вид діяльності", "Види діяльності")),
    )

    if not company.name:
        return None
    missing = {
        "статус компанії": company.status,
        "дату реєстрації": company.registration_date,
        "керівника": company.director,
        "статутний капітал": company.statutory_capital_uah,
        "основний КВЕД": company.main_activity,
    }
    for label, value in missing.items():
        if value is None:
            parse_warnings.append(f"Не вдалося визначити {label} у Clarity")
    return company


def parse_tax(text: str, parse_warnings: list[str]) -> ClarityTax:
    tax_debt_amount = extract_tax_debt_amount(text)
    tax_debt = detect_bool_signal(
        text,
        ("податковий борг",),
        positive=("наяв", "вияв"),
        negative=("відсут", "немає", "не має", "не вияв"),
    )
    if tax_debt_amount is not None:
        tax_debt = tax_debt_amount > 0

    tax = ClarityTax(
        tax_debt=tax_debt,
        tax_debt_amount_uah=tax_debt_amount,
        tax_debt_as_of=extract_tax_debt_as_of(text),
        esv_debt=detect_bool_signal(text, ("борг єсв", "єсв борг", "борг по єсв"), positive=("наяв", "вияв"), negative=("відсут", "немає", "не має", "не вияв")),
        vat_active=detect_bool_signal(text, ("пдв",), positive=("актив", "зареєстр"), negative=("ануль", "неактив", "відсут")),
        single_tax_active=detect_bool_signal(text, ("єдиний податок",), positive=("актив", "зареєстр"), negative=("ануль", "неактив", "відсут")),
    )
    if tax.tax_debt is None:
        parse_warnings.append("Не вдалося визначити податковий борг у Clarity")
    if tax.esv_debt is None:
        parse_warnings.append("Не вдалося визначити борг ЄСВ у Clarity")
    return tax


def parse_signals(parts: list[str], parse_warnings: list[str]) -> ClaritySignals:
    signals = ClaritySignals(
        bankruptcy_count=extract_count(parts, ("Банкрутство", "Банкрутства")),
        enforcement_proceedings_count=extract_count(parts, ("Виконавчі провадження", "Виконавче провадження")),
        inspections_count=extract_count(parts, ("Перевірки", "Інспекції")),
        edr_history_count=extract_count(parts, ("Історія ЄДР", "Історія змін ЄДР")),
        licenses_count=extract_count(parts, ("Ліцензії", "Ліцензування")),
        prozorro_sales_count=extract_count(parts, ("Prozorro.Sale", "Prozorro", "Продажі Prozorro")),
    )
    if signals.bankruptcy_count is None:
        parse_warnings.append("Не вдалося визначити кількість записів банкрутства у Clarity")
    return signals


def build_risk_flags(
    company: ClarityCompany,
    tax: ClarityTax,
    signals: ClaritySignals,
) -> list[ClarityRiskFlag]:
    flags: list[ClarityRiskFlag] = []
    status = company.status.strip().lower() if company.status else ""
    if status and status != "зареєстровано" and not safe_negative_context(status):
        flags.append(
            ClarityRiskFlag(
                level="medium",
                code="company_not_registered_or_inactive",
                text="Статус компанії у Clarity відрізняється від 'Зареєстровано'. Потребує додаткової перевірки.",
            )
        )
    if signals.bankruptcy_count and signals.bankruptcy_count > 0:
        flags.append(
            ClarityRiskFlag(
                level="high",
                code="bankruptcy_found",
                text="Знайдено записи, пов'язані з банкрутством. Потребує уважної додаткової перевірки.",
            )
        )
    if tax.tax_debt is True:
        flags.append(
            ClarityRiskFlag(
                level="medium",
                code="tax_debt_found",
                text=format_clarity_tax_debt_text(tax),
            )
        )
        if (tax.tax_debt_amount_uah or 0) >= LARGE_CLARITY_TAX_DEBT_THRESHOLD_UAH:
            flags.append(
                ClarityRiskFlag(
                    level="medium",
                    code="large_tax_debt_found",
                    text=format_clarity_large_tax_debt_text(tax),
                )
            )
    if tax.esv_debt is True:
        flags.append(
            ClarityRiskFlag(
                level="medium",
                code="esv_debt_found",
                text="У Clarity є ознака боргу ЄСВ.",
            )
        )
    if signals.enforcement_proceedings_count and signals.enforcement_proceedings_count > 0:
        flags.append(
            ClarityRiskFlag(
                level="info",
                code="enforcement_proceeding_found",
                text="Знайдено виконавчі провадження. Варто перевірити їх зміст.",
            )
        )
    if signals.enforcement_proceedings_count and signals.enforcement_proceedings_count > 5:
        flags.append(
            ClarityRiskFlag(
                level="medium",
                code="multiple_enforcement_proceedings",
                text="Знайдено кілька виконавчих проваджень. Потребує додаткової перевірки.",
            )
        )
    if signals.edr_history_count and signals.edr_history_count > 10:
        flags.append(
            ClarityRiskFlag(
                level="info",
                code="edr_history_found",
                text="Знайдено записи історії ЄДР. Варто перевірити, які саме зміни відбувались.",
            )
        )
    if signals.inspections_count and signals.inspections_count > 0:
        flags.append(
            ClarityRiskFlag(
                level="info",
                code="inspections_found",
                text="Знайдено записи перевірок. Варто переглянути їх контекст.",
            )
        )
    return flags


def extract_visible_text(html: str) -> list[str]:
    parser = VisibleTextParser()
    parser.feed(html)
    return parser.parts


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text).replace("\xa0", " ")).strip()


def extract_page_edrpou(parts: list[str]) -> str | None:
    header_parts = collect_header_parts(parts)
    for index, part in enumerate(header_parts[:-1]):
        if part.rstrip(":").upper() in EDRPOU_MARKER_LABELS:
            match = re.search(r"\b\d{8}\b", header_parts[index + 1])
            if match:
                return match.group(0)

    joined = " ".join(header_parts)
    match = re.search(r"(?:ЄДРПОУ|ЕДРПОУ|КОД ЄДРПОУ)\D{0,20}(\d{8})", joined, re.IGNORECASE)
    return match.group(1) if match else None


def collect_header_parts(parts: list[str]) -> list[str]:
    header_parts: list[str] = []
    for part in parts[:80]:
        if part.rstrip(":") in EDRPOU_HEADER_STOP_LABELS:
            break
        header_parts.append(part)
    return header_parts


def extract_name(parts: list[str]) -> str | None:
    labelled = extract_field(parts, ("Назва", "Повна назва"))
    if labelled:
        return labelled
    for part in parts:
        if is_likely_company_name(part):
            return part
    return None


def extract_director(parts: list[str]) -> str | None:
    labelled = extract_field(parts, ("Керівник", "Директор"))
    if labelled and is_person_name(labelled):
        return labelled

    for index, part in enumerate(parts):
        if part.rstrip(":") not in {"Уповноважені особи", "Уповноважена особа", "Підписанти"}:
            continue

        block = parts[index + 1 : index + 8]
        has_director_role = any("керівник" in item.lower() or "директор" in item.lower() for item in block)
        if not has_director_role:
            continue
        for candidate in block:
            if is_person_name(candidate):
                return candidate
    return None


def is_person_name(text: str) -> bool:
    if text in {"-", "—"}:
        return False
    return re.fullmatch(r"[А-ЯІЇЄҐ][а-яіїєґ'’.-]+(?:\s+[А-ЯІЇЄҐ][а-яіїєґ'’.-]+){1,3}", text) is not None


def is_likely_company_name(text: str) -> bool:
    upper_text = text.upper()
    return (
        re.search(r"(^|\s)(ТОВ|ПП|АТ|ПРАТ|ПАТ|ФОП)(\s|«|\"|$)", upper_text) is not None
        or "КОМПАН" in upper_text
        or "ПІДПРИЄМ" in upper_text
    )


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


def next_value(parts: list[str], start_index: int) -> str | None:
    for candidate in parts[start_index:]:
        if candidate and not is_label(candidate):
            return candidate
    return None


def is_label(text: str) -> bool:
    return text.rstrip(":") in {
        "Назва",
        "Повна назва",
        "Стан",
        "Статус",
        "Дата реєстрації",
        "Дата заснування",
        "Керівник",
        "Директор",
        "Статутний капітал",
        "Основний КВЕД",
        "Основний вид діяльності",
        "Види діяльності",
        "Уповноважені особи",
        "Уповноважена особа",
        "Підписанти",
    }


def parse_money(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"-?\d[\d\s]*(?:[,.]\d{1,2})?", text)
    if not match:
        return None
    return float(match.group(0).replace(" ", "").replace(",", "."))


def extract_tax_debt_amount(text: str) -> float | None:
    context = extract_tax_debt_context(text)
    if not context:
        return None
    match = re.search(r"(-?\d[\d\s]*(?:[,.]\d{1,2})?)\s*(?:грн|uah|₴)", context, re.IGNORECASE)
    if not match:
        return None
    return parse_money(match.group(1))


def extract_tax_debt_as_of(text: str) -> str | None:
    context = extract_tax_debt_context(text)
    if not context:
        return None
    match = re.search(r"(?:станом\s+на|на|від)\s*(\d{2}\.\d{2}\.\d{4})", context, re.IGNORECASE)
    return match.group(1) if match else None


def extract_tax_debt_context(text: str, max_length: int = 220) -> str | None:
    lowered = text.lower()
    index = lowered.find("податковий борг")
    if index == -1:
        return None
    return text[index : index + max_length]


def format_clarity_tax_debt_text(tax: ClarityTax) -> str:
    details = format_clarity_tax_debt_details(tax)
    suffix = (
        "Через обмеження оновлення відкритих податкових даних із 2022 року це може бути "
        "історичний запис, але його потрібно звірити вручну."
    )
    if details:
        return f"Clarity показує податковий борг: {details}. {suffix}"
    return f"Clarity показує ознаку податкового боргу. {suffix}"


def format_clarity_large_tax_debt_text(tax: ClarityTax) -> str:
    details = format_clarity_tax_debt_details(tax)
    if details:
        return f"Сума податкового боргу за Clarity дуже суттєва: {details}. Потрібна актуальна ручна звірка."
    return "Сума податкового боргу за Clarity виглядає суттєвою. Потрібна актуальна ручна звірка."


def format_clarity_tax_debt_details(tax: ClarityTax) -> str | None:
    if tax.tax_debt_amount_uah is None:
        return None
    details = format_decimal_uah(tax.tax_debt_amount_uah)
    if tax.tax_debt_as_of:
        details = f"{details} станом на {tax.tax_debt_as_of}"
    return details


def format_decimal_uah(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ") + " грн"
    whole, fraction = f"{value:.2f}".split(".")
    return f"{int(whole):,}".replace(",", " ") + f".{fraction} грн"


def extract_count(parts: list[str], labels: tuple[str, ...]) -> int | None:
    for index, part in enumerate(parts):
        if any(part == label or part.rstrip(":") == label for label in labels):
            value = next_numeric_value(parts, index + 1)
            if value is not None:
                return value
        for label in labels:
            if part.startswith(f"{label}:"):
                value = parse_first_int(part)
                if value is not None:
                    return value
            if part.startswith(label):
                value = parse_first_int(part)
                if value is not None:
                    return value
    return None


def next_numeric_value(parts: list[str], start_index: int) -> int | None:
    for candidate in parts[start_index : start_index + 4]:
        if is_label(candidate) or is_count_signal_label(candidate):
            return None
        value = parse_first_int(candidate)
        if value is not None:
            return value
    return None


def is_count_signal_label(text: str) -> bool:
    normalized = text.rstrip(":")
    return any(
        normalized == label
        or normalized.startswith(f"{label}:")
        or normalized.startswith(f"{label} (")
        for label in COUNT_SIGNAL_LABELS
    )


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
        index = lowered.find(keyword)
        if index == -1:
            continue
        forward_window = lowered[index : index + 140]
        prefix_window = lowered[max(0, index - 40) : index]
        if any(marker in forward_window for marker in negative) or any(
            marker in prefix_window for marker in ("не має", "немає")
        ):
            return False
        if any(marker in forward_window for marker in positive):
            return True
    return None


def safe_negative_context(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        pattern in lowered
        for pattern in (
            "не перебуває в процесі припинення",
            "не перебуває у процесі припинення",
            "не перебуває в стані припинення",
            "не перебуває у стані припинення",
            "банкрутство не виявлено",
            "банкрутство відсут",
            "податковий борг відсут",
            "податковий борг не вияв",
            "виконавчі провадження відсут",
            "виконавчі провадження не вияв",
            "борг єсв відсут",
        )
    )
