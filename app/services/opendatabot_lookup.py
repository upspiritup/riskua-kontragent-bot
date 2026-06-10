from __future__ import annotations

from dataclasses import asdict
import re
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from app.models.company_lookup import (
    CompanyData,
    CompanyLookupResult,
    CourtData,
    FinancialData,
    FinancialYearData,
    OwnerData,
    RegistrationChange,
    RiskInput,
)
from app.services.court_analyzer import analyze_court_decision
from app.utils.validators import is_valid_edrpou


BASE_OPENDATABOT_URL = "https://opendatabot.ua/c/{edrpou}?from=search"
HTTP_TIMEOUT_SECONDS = 8.0
FOUND = "found"
NOT_FOUND = "not_found"
SOURCE_ERROR = "source_error"
PARSE_ERROR = "parse_error"
PARTIAL = "partial"
EDRPOU_MARKER_LABELS = ("Код ЄДРПОУ", "ЄДРПОУ", "ЕДРПОУ")

FINANCIAL_ROW_LABELS = (
    "Дохід",
    "Чистий прибуток",
    "Рентабельність",
    "Активи",
    "Зобов'язання",
    "Власний капітал",
    "Капітал",
    "Кількість працівників",
    "Дохід на працівника",
)
SECTION_END_LABELS = {
    "Керівники",
    "Керівники з обмеженнями",
    "Новинка",
    "Документи компанії",
    "Корпоративна структура",
    "Фінансові показники",
    "Фінансова звітність",
    "Історія змін реєстраційної інформації",
    "Участь у тендерах",
    "Судовий реєстр",
    "Судові справи",
    "Опендатабот",
}


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


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth or tag != "a":
            return

        href = dict(attrs).get("href")
        if href:
            self._current_href = href
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "a" and self._current_href:
            label = join_text_fragments(self._current_text)
            self.links.append((self._current_href, label))
            self._current_href = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not self._current_href:
            return

        text = normalize_text(data)
        if text:
            self._current_text.append(text)


def validate_edrpou(edrpou: str) -> bool:
    return is_valid_edrpou(edrpou)


def build_opendatabot_url(edrpou: str) -> str:
    return BASE_OPENDATABOT_URL.format(edrpou=edrpou)


def fetch_company_page(edrpou: str) -> str:
    request = Request(
        build_opendatabot_url(edrpou),
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_court_decision_page(url: str) -> str:
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


def lookup_company(
    edrpou: str,
    fetcher: Callable[[str], str] = fetch_company_page,
    court_decision_fetcher: Callable[[str], str] | None = fetch_court_decision_page,
    max_court_decisions: int = 3,
) -> CompanyLookupResult:
    source_url = build_opendatabot_url(edrpou)
    if not validate_edrpou(edrpou):
        return CompanyLookupResult(
            status=SOURCE_ERROR,
            edrpou=edrpou,
            source_url=source_url,
            error="invalid_edrpou",
        )

    try:
        html = fetcher(edrpou)
    except HTTPError as exc:
        close_error_response(exc)
        if exc.code == 404:
            return CompanyLookupResult(status=NOT_FOUND, edrpou=edrpou, source_url=source_url)
        return CompanyLookupResult(
            status=SOURCE_ERROR,
            edrpou=edrpou,
            source_url=source_url,
            error=str(exc),
        )
    except (URLError, TimeoutError, OSError) as exc:
        return CompanyLookupResult(
            status=SOURCE_ERROR,
            edrpou=edrpou,
            source_url=source_url,
            error=str(exc),
        )

    result = parse_company_page(html, edrpou)
    if result.status in {FOUND, PARTIAL} and court_decision_fetcher and max_court_decisions > 0:
        enrich_court_decisions(result, court_decision_fetcher, max_court_decisions)
    return result


def close_error_response(error: HTTPError) -> None:
    try:
        error.close()
    except OSError:
        pass


def parse_company_page(html: str, edrpou: str) -> CompanyLookupResult:
    source_url = build_opendatabot_url(edrpou)
    parts = extract_visible_text(html)
    joined_text = " ".join(parts)

    if is_not_found_page(joined_text, edrpou):
        return CompanyLookupResult(status=NOT_FOUND, edrpou=edrpou, source_url=source_url)

    page_edrpou = extract_page_edrpou(parts)
    if page_edrpou and page_edrpou != edrpou:
        return CompanyLookupResult(
            status=PARSE_ERROR,
            edrpou=edrpou,
            source_url=source_url,
            parse_warnings=[
                f"ЄДРПОУ у відповіді Opendatabot не збігається із запитом: {page_edrpou}"
            ],
            error="edrpou_mismatch",
        )

    parse_warnings: list[str] = []
    company_data = parse_company_data(parts, edrpou, parse_warnings)
    if company_data is None:
        return CompanyLookupResult(
            status=PARSE_ERROR,
            edrpou=edrpou,
            source_url=source_url,
            parse_warnings=["Не вдалося розпізнати базові реєстраційні дані"],
            error="html_structure_not_recognized",
        )

    financial_data = parse_financial_data(parts, parse_warnings)
    registration_changes = parse_registration_changes(parts, parse_warnings)
    court_data = parse_court_data(parts)
    court_data.risk_flags = unique_strings(
        [*court_data.risk_flags, *detect_opendatabot_page_risk_flags(parts, company_data.status)]
    )
    court_data.source_urls = extract_court_decision_links(html)
    if court_data.source_urls and not court_data.has_court_mentions:
        court_data.has_court_mentions = True
        court_data.risk_flags = unique_strings([*court_data.risk_flags, "court_mentions_found"])
    risk_input = build_risk_input(company_data, financial_data, registration_changes, court_data, parts)

    return CompanyLookupResult(
        status=FOUND,
        edrpou=edrpou,
        source_url=source_url,
        company_data=company_data,
        financial_data=financial_data,
        registration_changes=registration_changes,
        court_data=court_data,
        risk_input=risk_input,
        parse_warnings=parse_warnings,
    )


def enrich_court_decisions(
    lookup_result: CompanyLookupResult,
    court_decision_fetcher: Callable[[str], str],
    max_court_decisions: int,
) -> None:
    for url in lookup_result.court_data.source_urls[:max_court_decisions]:
        try:
            html = court_decision_fetcher(url)
        except HTTPError as exc:
            close_error_response(exc)
            add_court_warning(lookup_result, f"Не вдалося отримати судове рішення {url}: HTTP {exc.code}")
            continue
        except (URLError, TimeoutError, OSError) as exc:
            add_court_warning(lookup_result, f"Не вдалося отримати судове рішення {url}: {exc}")
            continue

        decision = parse_court_decision_page(html, url)
        lookup_result.court_data.decisions.append(decision)


def add_court_warning(lookup_result: CompanyLookupResult, warning: str) -> None:
    lookup_result.court_data.parse_warnings.append(warning)
    lookup_result.parse_warnings.append(warning)


def extract_court_decision_links(html: str) -> list[str]:
    parser = LinkParser()
    parser.feed(html)

    links: list[str] = []
    seen: set[str] = set()
    for href, _label in parser.links:
        normalized_url = normalize_court_decision_url(href)
        if not normalized_url or normalized_url in seen:
            continue
        seen.add(normalized_url)
        links.append(normalized_url)
    return links


def normalize_court_decision_url(href: str) -> str | None:
    absolute_url = urljoin(BASE_OPENDATABOT_URL, href)
    parsed = urlparse(absolute_url)
    if parsed.netloc != "opendatabot.ua":
        return None
    if re.fullmatch(r"/court/\d+-[a-z0-9]+", parsed.path, re.IGNORECASE) is None:
        return None
    return f"{parsed.scheme or 'https'}://{parsed.netloc}{parsed.path}"


def parse_court_decision_page(html: str, url: str) -> dict[str, Any]:
    parts = extract_visible_text(html)
    text = " ".join(parts)
    meta = extract_court_decision_meta(text)
    analysis = asdict(analyze_court_decision(text))
    return {
        "source_url": url,
        **meta,
        **analysis,
    }


def extract_court_decision_meta(text: str) -> dict[str, str | None]:
    meta = {
        "document_type": None,
        "decision_number": None,
        "decision_date": None,
        "case_number": None,
    }
    header_match = re.search(
        r"\b(Ухвала|Постанова|Рішення)\s*№\s*(\d+)\s*від\s*(\d{2}\.\d{2}\.\d{4})"
        r"(?:\s*року)?\s*(?:по|у)\s+справ[іи]\s*№?\s*([^\s,;]+)",
        text,
        re.IGNORECASE,
    )
    if header_match:
        return {
            "document_type": header_match.group(1).capitalize(),
            "decision_number": header_match.group(2),
            "decision_date": header_match.group(3),
            "case_number": header_match.group(4),
        }

    document_type_match = re.search(r"\b(Ухвала|Постанова|Рішення)\b", text, re.IGNORECASE)
    decision_number_match = re.search(r"№\s*(\d{5,})", text)
    decision_date_match = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", text)
    case_number_match = re.search(r"справ[іи]\s*№?\s*([0-9A-Za-zА-Яа-яІіЇїЄєҐґ/_-]+)", text, re.IGNORECASE)
    if document_type_match:
        meta["document_type"] = document_type_match.group(1).capitalize()
    if decision_number_match:
        meta["decision_number"] = decision_number_match.group(1)
    if decision_date_match:
        meta["decision_date"] = decision_date_match.group(0)
    if case_number_match:
        meta["case_number"] = case_number_match.group(1)
    return meta


def parse_company_data(
    parts: list[str],
    edrpou: str,
    parse_warnings: list[str],
) -> CompanyData | None:
    full_name = extract_field(parts, ("Повна назва", "Назва"))
    short_name = extract_company_name(parts, edrpou)
    found_edrpou = extract_page_edrpou(parts) or edrpou
    if found_edrpou != edrpou or not (full_name or short_name):
        return None

    address = extract_multiline_field(parts, ("Адреса", "Місцезнаходження"))
    main_activity = extract_field(parts, ("Основний вид діяльності", "Основний КВЕД"))
    main_activity_code, main_activity_name = split_activity(main_activity)
    tenders_text = extract_field(parts, ("Тендери", "Участь у тендерах", "Публічні закупівлі"))
    owners, beneficial_owners = parse_owners(parts)
    additional_activities = parse_additional_activities(
        extract_field(parts, ("Інші види діяльності", "Додаткові види діяльності"))
    )

    company_data = CompanyData(
        full_name=full_name,
        short_name=short_name,
        edrpou=found_edrpou,
        status=extract_company_status(parts),
        address=address,
        city=extract_city(address),
        region=extract_region(address),
        registration_date=extract_field(parts, ("Дата заснування", "Дата реєстрації")),
        registry_extract_time=extract_field(parts, ("Час витягу з ЄДР",)),
        director=extract_field(parts, ("Директор", "Керівник")),
        statutory_capital_uah=parse_uah_amount(extract_field(parts, ("Статутний капітал",))),
        vat_status=extract_field(parts, ("ПДВ-статус", "Статус платника ПДВ", "ПДВ")),
        main_activity_code=main_activity_code,
        main_activity_name=main_activity_name,
        additional_activities=additional_activities,
        tenders_count=parse_first_int(tenders_text),
        tenders_text=tenders_text,
        owners_count=len([owner for owner in owners if not owner.is_beneficial_owner]),
        owners=[owner for owner in owners if not owner.is_beneficial_owner],
        beneficial_owners=beneficial_owners,
    )

    required_fields = {
        "повну назву": company_data.full_name,
        "адресу": company_data.address,
        "дату реєстрації": company_data.registration_date,
        "керівника": company_data.director,
        "основний КВЕД": company_data.main_activity_code,
    }
    for label, value in required_fields.items():
        if not value:
            parse_warnings.append(f"Не вдалося визначити {label}")

    return company_data


def parse_financial_data(parts: list[str], parse_warnings: list[str]) -> FinancialData:
    start = find_first_index(parts, "Фінансові показники")
    reports = [part for part in parts if part.lower().endswith(".xlsx")]
    if start is None:
        parse_warnings.append("Не знайдено фінансову таблицю")
        return FinancialData(financial_reports=reports, parse_warnings=["Не знайдено фінансову таблицю"])

    cursor = start + 1
    while cursor < len(parts) and parts[cursor] == "Фінансові показники":
        cursor += 1

    forecast: dict[str, int | float] = {}
    has_forecast = cursor < len(parts) and parts[cursor].startswith("Прогноз на")
    if has_forecast:
        forecast["year"] = parse_first_int(parts[cursor]) or 2026
        cursor += 1

    years: list[str] = []
    while cursor < len(parts) and re.fullmatch(r"20\d{2}", parts[cursor]):
        years.append(parts[cursor])
        cursor += 1

    rows = collect_financial_rows(parts, cursor)
    year_data = {year: FinancialYearData() for year in years}

    revenue_money, revenue_percents = money_values(rows.get("Дохід", [])), percent_values(rows.get("Дохід", []))
    if has_forecast and revenue_money:
        forecast["revenue_uah"] = revenue_money.pop(0)
        if revenue_percents:
            forecast["revenue_change_percent"] = revenue_percents.pop(0)
    assign_values(year_data, years, "revenue_uah", revenue_money)
    assign_values(year_data, years, "revenue_change_percent", revenue_percents)
    assign_values(year_data, years, "net_profit_uah", money_values(rows.get("Чистий прибуток", [])))
    assign_values(year_data, years, "profitability_percent", percent_values(rows.get("Рентабельність", [])))
    assign_values(year_data, years, "assets_uah", money_values(rows.get("Активи", [])))
    assign_values(year_data, years, "liabilities_uah", money_values(rows.get("Зобов'язання", [])))
    equity_values = money_values(rows.get("Власний капітал", [])) or money_values(rows.get("Капітал", []))
    assign_values(year_data, years, "equity_uah", equity_values)
    assign_values(year_data, years, "employees_count", integer_values(rows.get("Кількість працівників", [])))
    assign_values(year_data, years, "revenue_per_employee_uah", money_values(rows.get("Дохід на працівника", [])))

    return FinancialData(years=year_data, forecast=forecast, financial_reports=reports)


def collect_financial_rows(parts: list[str], start_index: int) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    index = start_index
    while index < len(parts):
        label = parts[index]
        if label == "Фінансова звітність":
            break
        if label in FINANCIAL_ROW_LABELS:
            next_index = index + 1
            values: list[str] = []
            while next_index < len(parts) and parts[next_index] not in FINANCIAL_ROW_LABELS and parts[next_index] != "Фінансова звітність":
                values.append(parts[next_index])
                next_index += 1
            rows[label] = values
            index = next_index
            continue
        index += 1
    return rows


def assign_values(
    year_data: dict[str, FinancialYearData],
    years: list[str],
    field_name: str,
    values: list[int | float],
) -> None:
    for year, value in zip(years, values):
        current = year_data[year]
        year_data[year] = current.model_copy(update={field_name: value})


def parse_registration_changes(parts: list[str], parse_warnings: list[str]) -> list[RegistrationChange]:
    start = find_first_index(parts, "Історія змін реєстраційної інформації")
    if start is None:
        parse_warnings.append("Не знайдено дату останньої зміни реєстраційної інформації")
        return []

    block = collect_until_section(parts, start + 1, {"Участь у тендерах", "Судовий реєстр", "Опендатабот"})
    tokens = [
        token
        for token in block
        if token
        not in {
            "Історія змін реєстраційної інформації",
            "Дата",
            "Зміна",
            "Було",
            "Стало",
        }
    ]
    date_requires_login = "Увійдіть" in tokens
    if date_requires_login:
        parse_warnings.append("Дата останньої зміни реєстраційної інформації закрита авторизацією")
        tokens = [
            token
            for token in tokens
            if token not in {"Увійдіть", "для отримання дати останніх змін"}
        ]

    if len(tokens) < 3:
        return []

    return [
        RegistrationChange(
            date=None,
            date_requires_login=date_requires_login,
            change_type=tokens[0],
            before=tokens[1],
            after=tokens[2],
        )
    ]


def parse_court_data(parts: list[str]) -> CourtData:
    start = find_first_index(parts, "Судовий реєстр")
    if start is None:
        start = find_first_index(parts, "Судові справи")
    if start is None:
        return CourtData()

    block = collect_until_section(parts, start + 1, {"Опендатабот", "Перевірити компанію"})
    total_cases = parse_first_int(block[0]) if block else 0
    court_categories: dict[str, int] = {}
    for index, token in enumerate(block[:-1]):
        if token and not token[0].isdigit() and re.fullmatch(r"\d+", block[index + 1]):
            court_categories[token] = int(block[index + 1])

    latest_date = next((token for token in block if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", token)), None)
    return CourtData(
        has_court_mentions=bool(total_cases),
        court_mentions_count=total_cases or 0,
        court_unique_cases_count=None,
        court_risky_cases_count=None,
        total_cases_found=total_cases or 0,
        court_categories=court_categories,
        latest_court_date=latest_date,
        risk_flags=["court_mentions_found"] if total_cases else [],
    )


def build_risk_input(
    company_data: CompanyData,
    financial_data: FinancialData,
    registration_changes: list[RegistrationChange],
    court_data: CourtData,
    parts: list[str] | None = None,
) -> RiskInput:
    latest_year = max(financial_data.years.keys(), default=None)
    latest_financial = financial_data.years[latest_year] if latest_year else FinancialYearData()
    profits = [year.net_profit_uah for year in financial_data.years.values() if year.net_profit_uah is not None]
    revenue_changes = [
        year.revenue_change_percent
        for year in financial_data.years.values()
        if year.revenue_change_percent is not None
    ]
    return RiskInput(
        company_age_years=calculate_company_age_years(company_data.registration_date),
        has_full_registration_data=bool(
            company_data.full_name and company_data.edrpou and company_data.address and company_data.registration_date
        ),
        has_director=bool(company_data.director),
        has_beneficial_owner=bool(company_data.beneficial_owners),
        owners_count=company_data.owners_count,
        statutory_capital_uah=company_data.statutory_capital_uah,
        has_financial_history=bool(financial_data.years),
        latest_revenue_uah=latest_financial.revenue_uah,
        latest_net_profit_uah=latest_financial.net_profit_uah,
        latest_profitability_percent=latest_financial.profitability_percent,
        latest_employees_count=latest_financial.employees_count,
        had_losses_in_previous_years=any(profit < 0 for profit in profits),
        revenue_drop_detected=any(change < -20 for change in revenue_changes),
        registration_address_changed=any(
            change.change_type and "адрес" in change.change_type.lower()
            for change in registration_changes
        ),
        main_activity_code=company_data.main_activity_code,
        main_activity_name=company_data.main_activity_name,
        has_court_mentions=court_data.has_court_mentions,
        court_mentions_count=court_data.court_mentions_count or court_data.total_cases_found,
        court_unique_cases_count=court_data.court_unique_cases_count,
        court_risky_cases_count=court_data.court_risky_cases_count,
        total_court_cases_found=court_data.total_cases_found,
        **parse_tax_debt_risk_input(parts or [], company_data),
    )


def parse_tax_debt_risk_input(parts: list[str], company_data: CompanyData | None = None) -> dict[str, object]:
    context = extract_tax_debt_collection_context(parts, company_data)
    if not context:
        return {
            "tax_debt_found": False,
            "tax_debt_count": 0,
            "tax_debt_text": None,
        }
    return {
        "tax_debt_found": True,
        "tax_debt_count": extract_tax_debt_count(context),
        "tax_debt_text": context,
    }


def extract_tax_debt_collection_context(parts: list[str], company_data: CompanyData | None = None) -> str | None:
    for part in parts:
        if is_tax_debt_for_queried_company(part, company_data):
            return normalize_tax_debt_context(part)

    joined_text = join_text_fragments(parts)
    lowered = joined_text.lower()
    for marker in ("державна податкова служба", "гу дпс", "дпс", "податковий борг", "податкового боргу"):
        index = lowered.find(marker)
        if index == -1:
            continue
        context = joined_text[max(0, index - 80) : index + 220]
        if is_tax_debt_for_queried_company(context, company_data):
            return normalize_tax_debt_context(context)
    return None


def is_tax_debt_for_queried_company(text: str, company_data: CompanyData | None = None) -> bool:
    if not is_tax_debt_collection_context(text):
        return False
    if not is_tax_authority_company(company_data):
        return True
    return is_tax_debt_against_tax_authority(text)


def is_tax_authority_company(company_data: CompanyData | None) -> bool:
    if company_data is None:
        return False
    identity = " ".join(
        value
        for value in (
            company_data.short_name,
            company_data.full_name,
            company_data.main_activity_name,
        )
        if value
    ).lower()
    return contains_any(
        identity,
        (
            "гу дпс",
            "головне управління дпс",
            "державна податкова служба",
            "податкова служба",
        ),
    )


def is_tax_debt_against_tax_authority(text: str) -> bool:
    lowered = (text or "").lower()
    tax_authority = r"(?:гу\s+дпс|головн\w*\s+управлін\w*\s+дпс|державн\w*\s+податков\w*\s+служб\w*|дпс)"
    debtor_patterns = (
        rf"\bборжник\b[^.:\n]{{0,80}}[:\-\s]+[^.:\n]{{0,80}}{tax_authority}",
        rf"\bборжник\b[^.:\n]{{0,120}}{tax_authority}",
        rf"\bз\s+{tax_authority}\b",
    )
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in debtor_patterns)


def is_tax_debt_collection_context(text: str) -> bool:
    lowered = (text or "").lower()
    if not contains_any(lowered, ("податковий борг", "податкового боргу", "податкової заборгованості")):
        return False
    if contains_any(lowered, ("податковий борг відсут", "податковий борг не вияв", "відсутній податковий борг")):
        return False
    return contains_any(
        lowered,
        (
            "державна податкова служба",
            "гу дпс",
            "дпс",
            "стягує",
            "стягнення",
            "стягнути",
        ),
    )


def normalize_tax_debt_context(text: str) -> str:
    context = normalize_text(text)
    return context.rstrip(".") + "."


def extract_tax_debt_count(text: str) -> int:
    match = re.search(r"\b(\d+)\s+податков\w*\s+борг", text.lower())
    if match:
        return int(match.group(1))
    return 1


def contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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


def is_not_found_page(text: str, edrpou: str) -> bool:
    lowered = text.lower()
    return (
        f"невірний код компанії {edrpou}".lower() in lowered
        or "компанію не знайдено" in lowered
        or "компанія не знайдена" in lowered
    )


def extract_page_edrpou(parts: list[str]) -> str | None:
    scan_parts = parts[:80]
    labelled_value = extract_field(scan_parts, EDRPOU_MARKER_LABELS)
    if labelled_value:
        match = re.search(r"\b\d{8}\b", labelled_value)
        if match:
            return match.group(0)

    marker_pattern = "|".join(re.escape(label) for label in EDRPOU_MARKER_LABELS)
    joined_text = " ".join(scan_parts)
    marker_match = re.search(rf"(?:{marker_pattern})\D{{0,30}}(\d{{8}})", joined_text, re.IGNORECASE)
    if marker_match:
        return marker_match.group(1)

    for part in scan_parts[:10]:
        title_match = re.match(r"^\s*(\d{8})\s*(?:[—-]|\b)", part)
        if title_match and is_likely_company_name(part):
            return title_match.group(1)

    return None


def extract_company_name(parts: list[str], edrpou: str) -> str | None:
    for index, part in enumerate(parts):
        if part == "Код ЄДРПОУ" or part.rstrip(":") == "Код ЄДРПОУ":
            code_index = find_next_index(parts, index + 1, edrpou)
            if code_index is None:
                continue
            for candidate in parts[code_index + 1 : code_index + 4]:
                if is_likely_company_name(candidate):
                    return candidate
    return None


def extract_company_status(parts: list[str]) -> str | None:
    labelled = extract_field(parts, ("Статус компанії", "Статус", "Стан"))
    if labelled:
        return labelled

    joined_text = " ".join(parts).lower()
    if has_safe_negative_status(joined_text):
        return "Зареєстровано"
    if "компанія зареєстрована" in joined_text or "підприємство" in joined_text and "зареєстровано" in joined_text:
        return "Зареєстровано"
    if has_positive_termination_context(joined_text):
        if "в стані припинення" in joined_text or "у стані припинення" in joined_text:
            return "В стані припинення"
        return "Припинено"
    if has_positive_bankruptcy_context(joined_text):
        return "Виконується процедура банкрутства"
    return None


def has_safe_negative_status(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        pattern in lowered
        for pattern in (
            "не перебуває в процесі припинення",
            "не перебуває у процесі припинення",
            "не перебуває в стані припинення",
            "не перебуває у стані припинення",
        )
    )


def detect_opendatabot_page_risk_flags(parts: list[str], company_status: str | None = None) -> list[str]:
    text = join_text_fragments(parts).lower()
    flags: list[str] = []
    if has_positive_bankruptcy_context(text):
        flags.append("bankruptcy_found")
    if is_positive_company_termination_status(company_status):
        flags.append("company_in_termination")
    return unique_strings(flags)


def has_positive_bankruptcy_context(text: str) -> bool:
    lowered = (text or "").lower()
    if has_bankruptcy_negative_context(lowered):
        return False
    return contains_any(
        lowered,
        (
            "виконується процедура банкрутства",
            "перебуває у процедурі банкрутства",
            "перебуває в процедурі банкрутства",
            "процедура банкрутства",
            "справа про банкрутство",
            "справі про банкрутство",
            "відкрито провадження про банкрутство",
            "порушено справу про банкрутство",
            "визнано банкрутом",
            "боржника банкрутом",
            "ліквідаційна маса банкрута",
            "ліквідаційної маси банкрута",
        ),
    )


def has_bankruptcy_negative_context(text: str) -> bool:
    lowered = (text or "").lower()
    return contains_any(
        lowered,
        (
            "банкрутство не виявлено",
            "банкрутство відсут",
            "банкрутство не знайдено",
            "справи про банкрутство відсут",
            "відомості про банкрутство відсут",
            "не перебуває у процедурі банкрутства",
            "не перебуває в процедурі банкрутства",
        ),
    )


def has_positive_termination_context(text: str) -> bool:
    lowered = (text or "").lower()
    if has_safe_negative_status(lowered):
        return False
    return contains_any(
        lowered,
        (
            "статус компанії припинено",
            "статус компанії: припинено",
            "статус компанії в стані припинення",
            "статус компанії: в стані припинення",
            "статус компанії у стані припинення",
            "статус компанії: у стані припинення",
            "компанія припинена",
            "підприємство припинено",
        ),
    )


def is_positive_company_termination_status(status: str | None) -> bool:
    normalized = " ".join((status or "").casefold().split()).strip(" .:;")
    return normalized in {
        "в стані припинення",
        "у стані припинення",
        "припиняється",
        "припинено",
    }


def is_likely_company_name(text: str) -> bool:
    if is_label(text) or text.isdigit():
        return False
    return (
        re.search(r"(^|\s)(ТОВ|ПП|АТ|ПРАТ|ПАТ|ФОП)(\s|«|\"|$)", text.upper()) is not None
        or "КОМПАН" in text.upper()
        or "ПІДПРИЄМ" in text.upper()
    )


def find_first_index(parts: list[str], value: str) -> int | None:
    for index, part in enumerate(parts):
        if part == value:
            return index
    return None


def find_next_index(parts: list[str], start_index: int, value: str) -> int | None:
    for index in range(start_index, len(parts)):
        if parts[index] == value:
            return index
        if is_label(parts[index]):
            return None
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
                    return join_text_fragments(values)
            prefix = f"{label}:"
            if part.startswith(prefix):
                value = normalize_text(part[len(prefix) :])
                if value:
                    return value
    return None


def values_until_next_label(parts: list[str], start_index: int) -> list[str]:
    values: list[str] = []
    for candidate in parts[start_index : start_index + 8]:
        if is_label(candidate):
            break
        if candidate:
            values.append(candidate)
    return values


def collect_until_section(parts: list[str], start_index: int, stop_labels: set[str]) -> list[str]:
    values: list[str] = []
    for candidate in parts[start_index:]:
        if candidate in stop_labels:
            break
        values.append(candidate)
    return values


def join_text_fragments(values: list[str]) -> str:
    text = " ".join(values)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def next_value(parts: list[str], start_index: int) -> str | None:
    for candidate in parts[start_index:]:
        if candidate and not is_label(candidate):
            return candidate
    return None


def is_label(text: str) -> bool:
    return text.rstrip(":") in {
        "Код ЄДРПОУ",
        "Статус компанії",
        "Статус",
        "Стан",
        "Дата заснування",
        "Дата реєстрації",
        "Час витягу з ЄДР",
        "Адреса",
        "Місцезнаходження",
        "Директор",
        "Керівник",
        "Статутний капітал",
        "Основний вид діяльності",
        "Основний КВЕД",
        "Інші види діяльності",
        "Додаткові види діяльності",
        "Повна назва",
        "Назва",
        "Власники",
        "ПДВ",
        "ПДВ-статус",
        "Статус платника ПДВ",
        "Судові справи",
        "Судові згадки",
        "Судові рішення",
        "Судовий реєстр",
        "Тендери",
        "Участь у тендерах",
        "Публічні закупівлі",
    }


def parse_owners(parts: list[str]) -> tuple[list[OwnerData], list[OwnerData]]:
    start = find_first_index(parts, "Власники")
    if start is None:
        return [], []
    block = collect_until_section(parts, start + 1, SECTION_END_LABELS)
    owners: list[OwnerData] = []
    beneficial_owners: list[OwnerData] = []
    index = 0
    while index + 2 < len(block):
        name, country, role = block[index], block[index + 1], block[index + 2]
        if role == "Засновник":
            contribution = parse_uah_amount(block[index + 3]) if index + 3 < len(block) else None
            share = parse_percent(block[index + 4]) if index + 4 < len(block) else None
            owners.append(
                OwnerData(
                    name=name,
                    country=country,
                    role=role,
                    contribution_uah=contribution,
                    share_percent=share,
                    is_beneficial_owner=False,
                )
            )
            index += 5
            continue
        if "бенефіціар" in role.lower():
            owner = OwnerData(name=name, country=country, role=role, is_beneficial_owner=True)
            beneficial_owners.append(owner)
            index += 3
            continue
        index += 1
    return owners + beneficial_owners, beneficial_owners


def parse_additional_activities(text: str | None) -> list[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def split_activity(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    match = re.match(r"^(\d{2}\.\d{2}(?:\.\d)?)\s+(.+)$", text)
    if not match:
        return None, text
    return match.group(1), match.group(2)


def extract_city(address: str | None) -> str | None:
    if not address:
        return None
    match = re.search(r"місто\s+([^,]+)", address, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_region(address: str | None) -> str | None:
    if not address:
        return None
    match = re.search(r"([^,]+область)", address, re.IGNORECASE)
    return match.group(1).strip() if match else None


def parse_uah_amount(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"-?\d[\d\s]*", text)
    if not match:
        return None
    return int(match.group(0).replace(" ", ""))


def parse_percent(text: str | None) -> float | None:
    if not text or "%" not in text:
        return None
    match = re.search(r"[-+]?\d+(?:[,.]\d+)?", text)
    if not match:
        return None
    value = float(match.group(0).replace(",", "."))
    return int(value) if value.is_integer() else value


def money_values(values: list[str]) -> list[int]:
    return [amount for amount in (parse_uah_amount(value) for value in values if "₴" in value) if amount is not None]


def percent_values(values: list[str]) -> list[float]:
    return [percent for percent in (parse_percent(value) for value in values if "%" in value) if percent is not None]


def integer_values(values: list[str]) -> list[int]:
    numbers: list[int] = []
    for value in values:
        if re.fullmatch(r"\d+", value):
            numbers.append(int(value))
    return numbers


def parse_first_int(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def calculate_company_age_years(registration_date: str | None) -> int | None:
    if not registration_date:
        return None
    try:
        registered_at = datetime.strptime(registration_date, "%d.%m.%Y").date()
    except ValueError:
        return None
    today = date.today()
    return today.year - registered_at.year - ((today.month, today.day) < (registered_at.month, registered_at.day))
