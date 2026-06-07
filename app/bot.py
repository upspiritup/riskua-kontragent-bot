from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import Callable
from datetime import date, datetime
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from app.config import load_settings
from app.models.clarity import ClarityData
from app.models.company_lookup import (
    CompanyData,
    CompanyLookupResult,
    FinancialYearData,
    ProzorroAnalysis,
    ProzorroSaleAnalysis,
    ProzorroSearchSummary,
    RiskFlagSnapshot,
    RiskSummary,
    SourceDiagnostic,
)
from app.services.check_storage import save_check_result
from app.services.clarity_lookup import (
    FOUND as CLARITY_FOUND,
    LARGE_CLARITY_TAX_DEBT_THRESHOLD_UAH,
    PARTIAL as CLARITY_PARTIAL,
    PARSE_ERROR as CLARITY_PARSE_ERROR,
    SOURCE_ERROR as CLARITY_SOURCE_ERROR,
    format_clarity_large_tax_debt_text,
    format_clarity_tax_debt_text,
    lookup_clarity_by_edrpou,
)
from app.services.company_contacts_lookup import fetch_company_contacts_async
from app.services.debtors_lookup import fetch_debtors_registry
from app.services.diagnostic_logging import configure_diagnostic_logging, log_diagnostic_event
from app.services.domain_reputation_lookup import fetch_domain_reputation, normalize_url
from app.services.opendatabot_lookup import (
    FOUND,
    NOT_FOUND,
    PARSE_ERROR,
    PARTIAL,
    SOURCE_ERROR,
    lookup_company,
)
from app.services.prozorro_lookup import lookup_prepared_prozorro
from app.services.prozorro_sale_lookup import lookup_prozorro_sale_by_edrpou
from app.services.risk_scoring import RISK_FLAG_ALIASES, calculate_final_risk
from app.services.tax_lookup import fetch_tax_status
from app.services.youcontrol_lookup import fetch_youcontrol_company
from app.utils.validators import is_valid_edrpou


START_TEXT = (
    "Вітаю! Я RiskUA.\n\n"
    "Допомагаю швидко перевірити компанію за ЄДРПОУ перед оплатою, договором або співпрацею.\n\n"
    "Надішліть код ЄДРПОУ — я покажу базові дані, можливі ризики та коротку рекомендацію.\n\n"
    "Приклад: 12345678\n\n"
    "⏳ Аналіз може зайняти до 1 хвилини."
)

HELP_TEXT = (
    "Доступні команди:\n"
    "/start - почати роботу\n"
    "/help - інструкція\n"
    "/check - перевірити ЄДРПОУ\n"
    "/info - дізнатись як працює RiskUA\n"
    "/stop - зупинити діалог і сховати кнопки\n"
    "/example - приклад відповіді\n"
    "/about - про RiskUA Bot"
)

EXAMPLE_TEXT = (
    'Компанія: ТОВ "Приклад"\n'
    "ЄДРПОУ: 12345678\n"
    "Статус: активна\n"
    "Рівень ризику: середній\n\n"
    "Рекомендація: перед передоплатою перевірте договір, реквізити та наявність товару або послуги."
)

ABOUT_TEXT = (
    "RiskUA Bot допомагає швидко оцінити базові ризики постачальника за ЄДРПОУ. "
    "Результат має інформаційний характер і не є юридичним або фінансовим висновком."
)

INFO_TEXT = (
    "RiskUA — бот для швидкої перевірки компаній за ЄДРПОУ перед оплатою, договором або співпрацею.\n\n"
    "Бот збирає базову інформацію з відкритих джерел, визначає можливі ризикові ознаки та за допомогою AI формує короткий зрозумілий висновок.\n\n"
    "Як користуватись:\n"
    "1. Надішліть ЄДРПОУ компанії у форматі 8 цифр.\n"
    "2. Дочекайтесь завершення аналізу.\n"
    "3. Отримайте базові дані, ризикові ознаки та рекомендацію.\n\n"
    "⏳ Аналіз може зайняти до 1 хвилини."
)

STOP_TEXT = "Діалог зупинено. Щоб повернути кнопки та почати знову, натисніть /start."

INVALID_EDRPOU_TEXT = "Будь ласка, введіть ЄДРПОУ у форматі 8 цифр. Наприклад: 12345678"
NOT_FOUND_TEXT = "ЄДРПОУ має правильний формат, але компанію з таким кодом не знайдено у джерелі перевірки."
SOURCE_ERROR_TEXT = "Не вдалося отримати дані з джерела. Спробуйте пізніше або перевірте ЄДРПОУ вручну."

EDRPOU_SEARCH_TEXT = "🔎 Шукаю дані та формую коротку рекомендацію. Це може зайняти до 1 хвилини..."
STOP_BUTTON_TEXT = "🛑 Зупинити"
INFO_BUTTON_TEXT = "ℹ️ Як працює"
ANALYSIS_TIMEOUT_SECONDS = 60.0
SHOW_TECHNICAL_LIMITATIONS = False
LOW_AUTHORIZED_CAPITAL_THRESHOLD_UAH = 5001
PROZORRO_UNCONFIRMED_SEARCH_NOISE_THRESHOLD = 1000
YOUCONTROL_RISK_DEFINITIONS = {
    "company_not_found": (
        "medium",
        "YouControl не знайшов компанію за цим ЄДРПОУ. Потрібна ручна перевірка джерела.",
    ),
    "company_inactive": (
        "high",
        "YouControl показує ознаки неактивного або ліквідованого статусу компанії.",
    ),
    "company_in_termination": (
        "medium",
        "YouControl показує ознаки припинення компанії.",
    ),
    "tax_debt_found": (
        "medium",
        "У YouControl є ознака податкового боргу.",
    ),
    "court_cases_found": (
        "info",
        "YouControl показує судові згадки або справи. Варто перевірити їх зміст.",
    ),
    "enforcement_found": (
        "medium",
        "YouControl показує виконавчі провадження або боргові ознаки.",
    ),
    "bankruptcy_found": (
        "high",
        "YouControl показує ознаки, пов'язані з банкрутством.",
    ),
    "suspicious_status": (
        "medium",
        "YouControl показує ризикове попередження або нетиповий статус.",
    ),
    "data_mismatch_between_sources": (
        "medium",
        "Дані YouControl відрізняються від іншого джерела. Потрібна ручна звірка.",
    ),
}


def build_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=STOP_BUTTON_TEXT), KeyboardButton(text=INFO_BUTTON_TEXT)]],
        resize_keyboard=True,
    )


def build_edrpou_response(
    text: str,
    lookup_result: CompanyLookupResult | None = None,
    clarity_data: ClarityData | None = None,
    youcontrol_data: dict | None = None,
    debtors_registry_data: dict | None = None,
    tax_data: dict | None = None,
    domain_reputation_data: dict | None = None,
    contacts_summary: dict | None = None,
) -> str:
    edrpou, _website_url = parse_edrpou_query(text)
    if not edrpou:
        return INVALID_EDRPOU_TEXT

    if lookup_result is None or lookup_result.status in {SOURCE_ERROR, PARSE_ERROR}:
        return SOURCE_ERROR_TEXT
    if lookup_result.status == NOT_FOUND:
        return NOT_FOUND_TEXT
    if lookup_result.status in {FOUND, PARTIAL} and lookup_result.company_data:
        return format_found_company(
            lookup_result,
            clarity_data,
            youcontrol_data,
            debtors_registry_data,
            tax_data,
            domain_reputation_data,
            contacts_summary,
        )

    return SOURCE_ERROR_TEXT


def format_found_company(
    lookup_result: CompanyLookupResult,
    clarity_data: ClarityData | None = None,
    youcontrol_data: dict | None = None,
    debtors_registry_data: dict | None = None,
    tax_data: dict | None = None,
    domain_reputation_data: dict | None = None,
    contacts_summary: dict | None = None,
) -> str:
    company = lookup_result.company_data or CompanyData()
    clarity_company = get_clarity_company(clarity_data)
    company_name = company.short_name or company.full_name or (clarity_company.name if clarity_company else None)
    status = format_company_status_for_report(lookup_result, clarity_data, youcontrol_data)
    registration_date = company.registration_date or (clarity_company.registration_date if clarity_company else None)
    director = company.director or (clarity_company.director if clarity_company else None)
    kved = format_kved(company) or (clarity_company.main_activity if clarity_company else None)
    company_age_years = lookup_result.risk_input.company_age_years
    if company_age_years is None:
        company_age_years = calculate_company_age_years(registration_date)
    final_risk = calculate_final_risk(
        collect_source_risk_flags(
            lookup_result,
            clarity_data,
            youcontrol_data,
            debtors_registry_data,
            tax_data,
            domain_reputation_data,
        )
    )
    display_contacts_summary = merge_youcontrol_contacts_summary(contacts_summary, youcontrol_data)
    contact_lines = build_contacts_summary_lines(display_contacts_summary) or build_contact_lines(domain_reputation_data)
    limitation_lines = build_limitation_lines(
        lookup_result,
        clarity_data,
        youcontrol_data,
        debtors_registry_data,
        tax_data,
        domain_reputation_data,
        contacts_summary,
    )
    court_document_lines = build_court_document_block_lines(lookup_result)
    clarity_used_for_company = bool(
        clarity_company
        and (
            (not (company.short_name or company.full_name) and clarity_company.name)
            or (not company.status and clarity_company.status)
            or (not company.registration_date and clarity_company.registration_date)
            or (not company.director and clarity_company.director)
            or (not format_kved(company) and clarity_company.main_activity)
        )
    )
    lines = [
        "🔎 Перевірка контрагента",
        "",
        f"Назва компанії: {company_name or 'не вдалося визначити'}",
        f"ЄДРПОУ: {company.edrpou or lookup_result.edrpou}",
    ]
    base_lines: list[str] = []
    base_lines.extend(optional_field("Статус", status))
    base_lines.extend(optional_field("Дата реєстрації", registration_date))
    base_lines.extend(optional_field("Керівник", director))
    base_lines.extend(optional_field("Адреса", company.address))
    base_lines.extend(optional_field("КВЕД", kved))
    base_lines.extend(optional_field("ПДВ-статус", company.vat_status))
    base_lines.extend(optional_field("Тендери за відкритими джерелами", format_tenders(company)))
    if base_lines:
        lines.extend(["", "Короткі базові дані:", *base_lines])
    if contact_lines:
        lines.extend(["", "Контакти:", *contact_lines])
    financial_lines = build_financial_lines(lookup_result, clarity_data)
    if financial_lines:
        lines.extend(["", "Фінансові дані:", *financial_lines])
    prozorro_source_label = get_prozorro_source_label(lookup_result.prozorro_analysis)
    prozorro_source_included = prozorro_source_label is not None
    prozorro_report_mode = get_prozorro_report_mode(lookup_result)
    log_prozorro_report_mode(prozorro_report_mode, lookup_result.prozorro_analysis, prozorro_source_included)
    prozorro_lines = build_prozorro_section_lines(lookup_result)
    if prozorro_lines:
        lines.extend(["", "Prozorro:", *prozorro_lines])
    prozorro_sale_lines = build_prozorro_sale_section_lines(lookup_result.prozorro_sale_analysis)
    if prozorro_sale_lines:
        lines.extend(["", "Prozorro.Sale:", *prozorro_sale_lines])
    if court_document_lines:
        lines.extend(["", "Судові документи:", *court_document_lines])
    assessment_reason_lines = build_assessment_reason_lines(
        lookup_result,
        final_risk,
        status=status,
        company_age_years=company_age_years,
        kved=kved,
        clarity_data=clarity_data,
        tax_data=tax_data,
        contacts_summary=display_contacts_summary,
        youcontrol_data=youcontrol_data,
    )
    technical_limitation_lines = limitation_lines if SHOW_TECHNICAL_LIMITATIONS else []
    lines.extend(
        [
            "",
            "Причини оцінки:",
            *(assessment_reason_lines or ["• Суттєвих ризикових причин у доступних джерелах не виявлено."]),
            *technical_limitation_lines,
            "",
            format_user_risk_line(final_risk),
            "",
            format_sources(
                clarity_included=bool(clarity_data and clarity_data.status in {CLARITY_FOUND, CLARITY_PARTIAL}) or clarity_used_for_company,
                youcontrol_included=is_successful_youcontrol(youcontrol_data),
                debtors_registry_included=is_successful_debtors_registry(debtors_registry_data),
                tax_included=is_successful_tax(tax_data),
                domain_reputation_included=is_useful_domain_reputation_source(domain_reputation_data),
                contacts_summary=contacts_summary,
                prozorro_source_label=prozorro_source_label,
                prozorro_sale_included=is_reportable_prozorro_sale_analysis(lookup_result.prozorro_sale_analysis),
                court_included=has_court_source(lookup_result),
            ),
            "Результат має інформаційний характер і не є юридичним висновком.",
        ]
    )
    return "\n".join(lines)


def get_clarity_company(clarity_data: ClarityData | None):
    if clarity_data is None or clarity_data.status not in {CLARITY_FOUND, CLARITY_PARTIAL}:
        return None
    return clarity_data.company


def format_company_status_for_report(
    lookup_result: CompanyLookupResult,
    clarity_data: ClarityData | None = None,
    youcontrol_data: dict | None = None,
) -> str | None:
    statuses = collect_company_statuses(lookup_result, clarity_data, youcontrol_data)
    if has_company_status_conflict(statuses):
        return "потребує ручної перевірки статусу"
    company = lookup_result.company_data
    clarity_company = get_clarity_company(clarity_data)
    return (company.status if company else None) or (clarity_company.status if clarity_company else None)


def format_kved(company: CompanyData) -> str | None:
    if company.main_activity_code and company.main_activity_name:
        return f"{company.main_activity_code} — {company.main_activity_name}"
    return company.main_activity_code or company.main_activity_name


def format_tenders(company: CompanyData) -> str | None:
    if company.tenders_count is not None:
        return format_int(company.tenders_count)
    if company.tenders_text:
        count = parse_first_int_from_text(company.tenders_text)
        return format_int(count) if count is not None else company.tenders_text
    return None


def format_sources(
    *,
    clarity_included: bool,
    youcontrol_included: bool = False,
    debtors_registry_included: bool = False,
    tax_included: bool = False,
    domain_reputation_included: bool = False,
    contacts_summary: dict | None = None,
    prozorro_source_label: str | None = None,
    prozorro_sale_included: bool = False,
    court_included: bool = False,
) -> str:
    sources = ["Opendatabot"]
    if clarity_included:
        sources.append("Clarity")
    if youcontrol_included:
        sources.append("YouControl")
    if debtors_registry_included:
        sources.append("Єдиний реєстр боржників")
    if tax_included:
        sources.append("ДПС / tax")
    if domain_reputation_included:
        sources.append("перевірка сайту")
    if contacts_summary_has_source(contacts_summary, "prat.ua/pat.ua"):
        sources.append("PAT.UA")
    if prozorro_source_label:
        sources.append(prozorro_source_label)
    if prozorro_sale_included:
        sources.append("Prozorro.Sale")
    if court_included:
        sources.append("Судові джерела")
    sources = dedupe_lines(sources)
    if len(sources) == 1:
        return f"Джерело: {sources[0]}"
    return f"Джерела: {', '.join(sources)} та інші джерела"


def is_reportable_prozorro_analysis(prozorro_analysis: ProzorroAnalysis | None) -> bool:
    return bool(
        prozorro_analysis
        and prozorro_analysis.status in {"found", "partial"}
        and prozorro_records_count(prozorro_analysis) > 0
    )


def is_prozorro_source_included(prozorro_analysis: ProzorroAnalysis | None) -> bool:
    return is_reportable_prozorro_analysis(prozorro_analysis) or has_prozorro_search_summary(prozorro_analysis)


def get_prozorro_source_label(prozorro_analysis: ProzorroAnalysis | None) -> str | None:
    if is_reportable_prozorro_analysis(prozorro_analysis):
        return "Prozorro"
    if has_prozorro_search_summary(prozorro_analysis):
        confirmed_count = prozorro_analysis.search_summary.confirmed_participation_count or 0
        return "Prozorro" if confirmed_count > 0 else "Prozorro search"
    return None


def has_prozorro_search_summary(prozorro_analysis: ProzorroAnalysis | None) -> bool:
    return bool(
        prozorro_analysis
        and prozorro_analysis.search_summary
        and (prozorro_analysis.search_summary.total_count or 0) > 0
    )


def prozorro_records_count(prozorro_analysis: ProzorroAnalysis | None) -> int:
    return len(prozorro_analysis.procurements) if prozorro_analysis else 0


def get_prozorro_report_mode(lookup_result: CompanyLookupResult) -> str:
    if is_reportable_prozorro_analysis(lookup_result.prozorro_analysis):
        return "detailed"
    if has_prozorro_search_summary(lookup_result.prozorro_analysis):
        return "summary"
    status = str(lookup_result.prozorro_analysis.status) if lookup_result.prozorro_analysis else ""
    if status in {"source_error", "unavailable"}:
        return "source_error"
    if build_prozorro_tender_fallback_lines(lookup_result.company_data):
        return "fallback"
    return "fallback" if status == "not_found" else "none"


def log_prozorro_report_mode(
    mode: str,
    prozorro_analysis: ProzorroAnalysis | None,
    source_added: bool,
) -> None:
    logging.info("Prozorro report mode: %s", mode)
    logging.info("Prozorro records_count=%s", prozorro_records_count(prozorro_analysis))
    logging.info("Prozorro source added=%s", str(source_added).lower())


def build_prozorro_section_lines(lookup_result: CompanyLookupResult) -> list[str]:
    if is_reportable_prozorro_analysis(lookup_result.prozorro_analysis):
        return build_prozorro_lines(lookup_result.prozorro_analysis)
    if has_prozorro_search_summary(lookup_result.prozorro_analysis):
        return build_prozorro_search_summary_lines(lookup_result.prozorro_analysis)
    return build_prozorro_tender_fallback_lines(lookup_result.company_data)


def is_reportable_prozorro_sale_analysis(prozorro_sale_analysis: ProzorroSaleAnalysis | None) -> bool:
    return bool(
        prozorro_sale_analysis
        and prozorro_sale_analysis.status == "found"
        and (prozorro_sale_analysis.risky_auctions or prozorro_sale_analysis.informational_mentions)
    )


def build_prozorro_sale_section_lines(prozorro_sale_analysis: ProzorroSaleAnalysis | None) -> list[str]:
    if not is_reportable_prozorro_sale_analysis(prozorro_sale_analysis):
        return []

    lines: list[str] = []
    if prozorro_sale_analysis.risky_auctions:
        lines.append(f"⚠️ Знайдено ризикові аукціони: {len(prozorro_sale_analysis.risky_auctions)}")
        for index, auction in enumerate(prozorro_sale_analysis.risky_auctions[:5], start=1):
            auction_id = auction.auction_id or "без ID"
            lines.append(f"{index}. {auction_id} — {auction.risk}")
            lines.append(f"   {auction.url}")
    debtor_mentions = [
        mention
        for mention in prozorro_sale_analysis.informational_mentions[:5]
        if mention.role == "debtor_mention"
    ]
    if debtor_mentions:
        lines.append(
            "Prozorro.Sale: компанія згадується у складі дебіторської заборгованості банкрута. "
            "Це не означає банкрутство самої компанії."
        )
        for mention in debtor_mentions:
            auction_id = mention.auction_id or "без ID"
            lines.append(f"{auction_id}: {mention.url}")
    general_mentions = [
        mention
        for mention in prozorro_sale_analysis.informational_mentions[:5]
        if mention.role != "debtor_mention"
    ]
    if general_mentions:
        lines.append(
            "Prozorro.Sale: знайдено аукціони з участю/згадкою компанії. "
            "Негативної дії саме з боку компанії не підтверджено."
        )
        for mention in general_mentions:
            auction_id = mention.auction_id or "без ID"
            lines.append(f"{auction_id}: {mention.url}")
    return lines


def build_prozorro_search_summary_lines(prozorro_analysis: ProzorroAnalysis | None) -> list[str]:
    if not has_prozorro_search_summary(prozorro_analysis):
        return []
    search_summary = prozorro_analysis.search_summary
    total_count = search_summary.total_count or 0
    checked_count = search_summary.checked_count
    confirmed_participation_count = search_summary.confirmed_participation_count or 0
    lines = [
        f"Результатів у пошуку Prozorro: {format_int(total_count)}.",
        f"Перевірено у видачі: {format_int(checked_count)}.",
        (
            "Підтверджено участь компанії серед перевірених: "
            f"{format_int(confirmed_participation_count)}."
        ),
        build_prozorro_search_risk_scan_line(
            search_summary.items,
            confirmed_participation_count=confirmed_participation_count,
        ),
    ]
    if confirmed_participation_count > 0:
        lines.append(build_prozorro_search_participation_line(confirmed_participation_count))
    lines.extend(build_prozorro_search_text_match_note_lines(confirmed_participation_count))
    return lines


def build_prozorro_search_participation_line(confirmed_participation_count: int) -> str:
    if confirmed_participation_count <= 0:
        return "Участей/перемог/договорів: серед перевірених результатів участь компанії не підтверджена."
    return "Участей/перемог/договорів: дані уточнюються за деталями закупівель."


def build_prozorro_search_text_match_note_lines(confirmed_participation_count: int) -> list[str]:
    if confirmed_participation_count > 0:
        return []
    return ["Частина результатів пошуку може бути текстовими збігами, а не закупівлями цієї компанії."]


def build_prozorro_search_item_lines(items: list[dict]) -> list[str]:
    if not items:
        return []

    lines = ["Перші закупівлі у видачі:"]
    for index, item in enumerate(items[:3], start=1):
        tender_id = first_nonempty_text(item, "tenderID", "id") or "без ID"
        title = truncate_text(first_nonempty_text(item, "title") or "без назви", 120)
        lines.append(f"{index}. {tender_id} — {title}")

        details: list[str] = []
        status = first_nonempty_text(item, "status")
        buyer_name = first_nonempty_text(item, "buyer_name", "buyer")
        expected_value = item.get("expected_value_uah")
        if status:
            details.append(f"Статус: {status}")
        if buyer_name:
            details.append(f"замовник: {truncate_text(buyer_name, 80)}")
        if isinstance(expected_value, int | float):
            details.append(f"очікувана сума: {format_uah(expected_value)}")
        if details:
            lines.append("; ".join(details) + ".")
    return lines


def build_prozorro_search_risk_scan_line(items: list[dict], *, confirmed_participation_count: int = 1) -> str:
    checked_count = len(items)
    marker_count = count_prozorro_search_potential_critical_signals(items)
    if marker_count:
        if confirmed_participation_count <= 0:
            return (
                f"У пошуковій видачі є потенційні маркери: {marker_count}, але участь компанії "
                "в цих результатах не підтверджена, тому вони не враховані як ризик."
            )
        return f"У перших {checked_count} результатах пошуку знайдено явні маркери: {marker_count}."
    if confirmed_participation_count <= 0:
        return "У перших перевірених результатах не знайдено підтверджених ризикових ознак, пов’язаних із компанією."
    return (
        f"У перших {checked_count} результатах пошуку не знайдено явних маркерів: "
        "скасування, розірвання, скарги або моніторингу."
    )


def count_prozorro_search_potential_critical_signals(items: list[dict]) -> int:
    return sum(1 for item in items if has_prozorro_search_potential_critical_signal(item))


def has_prozorro_search_potential_critical_signal(item: dict) -> bool:
    marker_codes = item.get("risk_marker_codes")
    if isinstance(marker_codes, list) and marker_codes:
        return True
    text_parts = [
        first_nonempty_text(item, "status"),
        first_nonempty_text(item, "title"),
        first_nonempty_text(item, "description"),
    ]
    text = " ".join(part for part in text_parts if part).casefold()
    return any(
        marker in text
        for marker in (
            "cancelled",
            "unsuccessful",
            "terminated",
            "complaint",
            "monitoring",
            "скасован",
            "відмін",
            "розірван",
            "скарг",
            "моніторинг",
        )
    )


def first_nonempty_text(item: dict, *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 1)].rstrip() + "…"


def build_prozorro_tender_fallback_lines(company: CompanyData | None) -> list[str]:
    if company is None:
        return []
    tenders_text = format_tenders_for_prozorro_fallback(company)
    if not tenders_text:
        return []
    return [
        f"За відкритими даними знайдено участь у тендерах: {tenders_text}.",
        "Детальна історія закупівель Prozorro тимчасово недоступна або не знайдена live-пошуком.",
        "Примітка: сам факт участі у тендерах не є ризиком. Score не підвищено.",
    ]


def format_tenders_for_prozorro_fallback(company: CompanyData) -> str | None:
    if company.tenders_count is not None:
        return f"{format_int(company.tenders_count)} {plural_uk(company.tenders_count, 'тендер', 'тендери', 'тендерів')}"
    return company.tenders_text


def build_prozorro_lines(prozorro_analysis: ProzorroAnalysis | None) -> list[str]:
    if not is_reportable_prozorro_analysis(prozorro_analysis):
        return []

    stats = prozorro_analysis.stats
    lines: list[str] = []
    search_summary = prozorro_analysis.search_summary
    confirmed_search_count = search_summary.confirmed_participation_count or 0 if search_summary else 0
    if prozorro_analysis.search_summary:
        lines.extend(
            [
                f"Результатів у пошуку Prozorro: {format_int(search_summary.total_count or 0)}.",
                f"Перевірено у видачі: {format_int(search_summary.checked_count)}.",
            ]
        )
        if confirmed_search_count > 0:
            lines.append(
                "Підтверджено закупівель із компанією: "
                f"{format_int(confirmed_search_count)}."
            )
            lines.extend(build_prozorro_role_lines(search_summary))
    search_confirmed_count = (
        prozorro_analysis.search_summary.confirmed_participation_count
        if prozorro_analysis.search_summary
        else None
    )
    stats_participation_label = (
        "Участей у деталізованій статистиці"
        if search_confirmed_count is not None and search_confirmed_count != stats.participations_count
        else "Участей"
    )
    stat_items: list[tuple[str, int | float | None]] = [
        (stats_participation_label, stats.participations_count),
        ("Перемог", stats.wins_count),
        ("Договорів", stats.contracts_count),
        ("Завершених договорів", stats.completed_contracts_count),
        ("Розірваних договорів", stats.terminated_contracts_count),
        ("Дискваліфікацій", stats.disqualifications_count),
    ]
    if not (search_summary and confirmed_search_count > 0):
        stat_items.insert(0, ("Закупівель", stats.procurements_count))
    lines.extend(
        nonzero_stat_lines(stat_items)
    )
    if search_confirmed_count is not None and search_confirmed_count != stats.procurements_count:
        lines.append("Примітка: кількість підтверджених закупівель і деталізована статистика можуть відрізнятися.")
    buyer_only = is_prozorro_buyer_only_summary(search_summary)
    if stats.complaints_count:
        complaints_label = "Скарг/вимог у закупівлях як замовника" if buyer_only else "Скарг/вимог"
        lines.append(f"{complaints_label}: {stats.complaints_count}")
    monitoring_count = count_prozorro_search_marker_items(
        prozorro_analysis.search_summary,
        "monitoring",
        confirmed_only=True,
    )
    if monitoring_count:
        monitoring_label = "Моніторингів закупівель як замовника" if buyer_only else "Моніторингів"
        lines.append(f"{monitoring_label}: {monitoring_count}")
    lines.extend(optional_percent_field("Частка перемог", stats.win_rate_percent))
    lines.extend(optional_percent_field("Частка розірвань", stats.termination_rate_percent))
    lines.extend(optional_percent_field("Частка дискваліфікацій", stats.disqualification_rate_percent))
    lines.extend(optional_field("Остання участь", stats.last_participation_date))
    lines.extend(optional_field("Остання перемога", stats.last_win_date))
    lines.extend(build_prozorro_negative_fact_summary_lines(prozorro_analysis))
    lines.extend(build_prozorro_detected_signal_lines(prozorro_analysis))
    if should_show_prozorro_analysis_summary(prozorro_analysis):
        lines.append(prozorro_analysis.summary)
    for note in prozorro_analysis.info_notes:
        lines.append(f"Примітка: {note}")
    if prozorro_analysis.status == "partial":
        lines.append("Примітка: дані Prozorro часткові; варто перевірити їх вручну.")
    if prozorro_analysis.status == "source_error":
        lines.append("Примітка: дані Prozorro недоступні; варто перевірити їх вручну.")
    return lines


def build_prozorro_role_lines(search_summary: ProzorroSearchSummary) -> list[str]:
    if not any(
        (
            search_summary.participant_count,
            search_summary.winner_count,
            search_summary.supplier_contract_count,
            search_summary.buyer_count,
        )
    ):
        return []
    return [
        "Ролі:",
        f"• учасник: {format_int(search_summary.participant_count)}",
        f"• переможець/постачальник: {format_int(max(search_summary.winner_count, search_summary.supplier_contract_count))}",
        f"• замовник: {format_int(search_summary.buyer_count)}",
    ]


def is_prozorro_buyer_only_summary(search_summary: ProzorroSearchSummary | None) -> bool:
    return bool(
        search_summary
        and search_summary.buyer_count > 0
        and search_summary.participant_count == 0
        and search_summary.winner_count == 0
        and search_summary.supplier_contract_count == 0
    )


def should_show_prozorro_analysis_summary(prozorro_analysis: ProzorroAnalysis) -> bool:
    return bool(prozorro_analysis.summary and not prozorro_analysis.search_summary)


def build_prozorro_negative_fact_summary_lines(prozorro_analysis: ProzorroAnalysis) -> list[str]:
    stats = prozorro_analysis.stats
    complaints_or_monitoring_count = stats.complaints_count + count_prozorro_search_marker_items(
        prozorro_analysis.search_summary,
        "monitoring",
        confirmed_only=True,
    )
    buyer_only = is_prozorro_buyer_only_summary(prozorro_analysis.search_summary)
    if buyer_only and not any((stats.terminated_contracts_count, stats.disqualifications_count)):
        if complaints_or_monitoring_count > 0:
            return [
                "Сигнали серед закупівель як замовника:",
                f"• скарги/моніторинги: {format_int(complaints_or_monitoring_count)}",
            ]
        return ["Висновок: підтверджених негативних Prozorro-фактів серед перевірених закупівель не знайдено."]
    if not any(
        (
            stats.terminated_contracts_count,
            stats.disqualifications_count,
            complaints_or_monitoring_count,
        )
    ):
        return ["Висновок: підтверджених негативних Prozorro-фактів серед перевірених закупівель не знайдено."]
    lines = ["Негативні факти серед перевірених:"]
    if stats.terminated_contracts_count > 0:
        lines.append(f"• розірвані договори: {format_int(stats.terminated_contracts_count)}")
    if stats.disqualifications_count > 0:
        lines.append(f"• дискваліфікації: {format_int(stats.disqualifications_count)}")
    if complaints_or_monitoring_count > 0:
        lines.append(f"• скарги/моніторинги: {format_int(complaints_or_monitoring_count)}")
    return lines


def build_prozorro_detected_signal_lines(prozorro_analysis: ProzorroAnalysis) -> list[str]:
    stats = prozorro_analysis.stats
    buyer_only = is_prozorro_buyer_only_summary(prozorro_analysis.search_summary)
    signal_lines: list[str] = []
    if stats.disqualifications_count > 0:
        signal_lines.append("• Була дискваліфікація учасника.")
    if stats.terminated_contracts_count > 0:
        signal_lines.append("• Є розірвання договору.")
    if stats.complaints_count > 0 or stats.supplier_related_complaints_count > 0:
        if buyer_only:
            signal_lines.append("• Є скарги/вимоги щодо закупівель компанії як замовника.")
        else:
            signal_lines.append("• Є скарги/вимоги у закупівлях.")
    if count_prozorro_search_marker_items(prozorro_analysis.search_summary, "monitoring", confirmed_only=True) > 0:
        if buyer_only:
            signal_lines.append("• Є моніторинг закупівлі компанії як замовника.")
        else:
            signal_lines.append("• Є моніторинг закупівлі.")
    if any(item.amendments_count > 0 for item in prozorro_analysis.procurements):
        signal_lines.append("• Є зміни договору.")
    if not signal_lines:
        return []
    header = "Сигнали як замовника:" if buyer_only else "⚠️ Виявлені сигнали:"
    return [header, *signal_lines]


def nonzero_stat_lines(items: list[tuple[str, int | float | None]]) -> list[str]:
    lines: list[str] = []
    for label, value in items:
        if value is None or value == 0:
            continue
        lines.append(f"{label}: {format_int(value) if isinstance(value, int) else value}")
    return lines


def count_prozorro_search_marker_items(
    search_summary: ProzorroSearchSummary | None,
    marker_code: str,
    *,
    confirmed_only: bool = False,
) -> int:
    if not search_summary:
        return 0
    count = 0
    for item in search_summary.items:
        if confirmed_only and not item.get("participation_confirmed"):
            continue
        marker_codes = item.get("risk_marker_codes")
        if isinstance(marker_codes, list) and marker_code in marker_codes:
            count += 1
    return count


def optional_percent_field(label: str, value: float | None) -> list[str]:
    if value is None or value == 0:
        return []
    return [f"{label}: {value:.1f}%"]


def format_user_risk_line(final_risk: dict) -> str:
    score = int(final_risk.get("score") or 0)
    return f"Загальний ризик: {user_risk_label_from_score(score)} — {score}/100"


def user_risk_label_from_score(score: int) -> str:
    if score <= 20:
        return "низький"
    if score <= 45:
        return "помірний"
    if score <= 70:
        return "підвищений"
    if score <= 80:
        return "високий"
    return "критичний"


def contacts_summary_has_source(contacts_summary: dict | None, source: str) -> bool:
    if not isinstance(contacts_summary, dict):
        return False
    source_statuses = contacts_summary.get("source_statuses") or {}
    if source_statuses.get(source) == "found":
        return any(
            source in ((contacts_summary.get(field) or {}).get("sources") or [])
            and is_displayable_contact_value(field, (contacts_summary.get(field) or {}).get("value"))
            for field in ("website", "phone", "email")
        )
    for field in ("website", "phone", "email"):
        contact = contacts_summary.get(field) or {}
        if source in (contact.get("sources") or []) and is_displayable_contact_value(field, contact.get("value")):
            return True
    return False


def merge_youcontrol_contacts_summary(contacts_summary: dict | None, youcontrol_data: dict | None) -> dict | None:
    contacts = extract_youcontrol_contacts(youcontrol_data)
    if not contacts:
        return contacts_summary

    summary = copy_contacts_summary(contacts_summary)
    for field, value in contacts.items():
        target = dict(summary.get(field) or {"value": None, "confidence": "unknown", "sources": [], "evidence": []})
        if not target.get("value"):
            target["value"] = value
            target["confidence"] = "medium"
            target["sources"] = dedupe_lines([*(target.get("sources") or []), "youcontrol"])
            target["evidence"] = dedupe_lines(
                [*(target.get("evidence") or []), "Контакт знайдено на сторінці YouControl за тим самим ЄДРПОУ."]
            )
        summary[field] = target
    source_statuses = dict(summary.get("source_statuses") or {})
    source_statuses["youcontrol"] = "found"
    summary["source_statuses"] = source_statuses
    return summary


def copy_contacts_summary(contacts_summary: dict | None) -> dict:
    summary = dict(contacts_summary or {})
    for field in ("website", "phone", "email"):
        summary[field] = dict(summary.get(field) or {"value": None, "confidence": "unknown", "sources": [], "evidence": []})
    summary["source_statuses"] = dict(summary.get("source_statuses") or {})
    return summary


def extract_youcontrol_contacts(youcontrol_data: dict | None) -> dict[str, str]:
    if not youcontrol_data or not youcontrol_data.get("found"):
        return {}
    company = youcontrol_data.get("company") or {}
    contacts = youcontrol_data.get("contacts") or {}
    values = {
        "website": first_contact_value(company.get("website"), contacts.get("website"), contacts.get("websites")),
        "phone": first_contact_value(company.get("phone"), company.get("phones"), contacts.get("phone"), contacts.get("phones")),
        "email": first_contact_value(company.get("email"), company.get("emails"), contacts.get("email"), contacts.get("emails")),
    }
    return {field: value for field, value in values.items() if value}


def first_contact_value(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return None


def build_financial_lines(lookup_result: CompanyLookupResult, clarity_data: ClarityData | None = None) -> list[str]:
    company = lookup_result.company_data or CompanyData()
    clarity_company = get_clarity_company(clarity_data)
    statutory_capital = company.statutory_capital_uah
    if statutory_capital is None and clarity_company and clarity_company.statutory_capital_uah is not None:
        statutory_capital = int(clarity_company.statutory_capital_uah)

    lines: list[str] = []
    if statutory_capital is not None:
        lines.append(f"Статутний капітал: {format_uah(statutory_capital)}")

    latest_year = max(lookup_result.financial_data.years.keys(), default=None)
    latest_financial = lookup_result.financial_data.years.get(latest_year) if latest_year else None
    if latest_year and latest_financial:
        lines.extend(optional_money_field(f"Дохід ({latest_year})", latest_financial.revenue_uah))
        lines.extend(optional_money_field(f"Прибуток/збиток ({latest_year})", latest_financial.net_profit_uah))
        lines.extend(optional_money_field(f"Активи ({latest_year})", latest_financial.assets_uah))
        lines.extend(optional_money_field(f"Зобов’язання ({latest_year})", latest_financial.liabilities_uah))
        if latest_financial.employees_count is not None:
            lines.append(f"Працівники ({latest_year}): {format_int(latest_financial.employees_count)}")
        equity_trend_line = build_equity_capital_trend_line(lookup_result.financial_data.years)
        if equity_trend_line:
            lines.append(equity_trend_line)
    elif lines:
        lines.append("Інші фінансові показники у доступних джерелах не знайдено.")
    return lines


def optional_money_field(label: str, value: int | float | None) -> list[str]:
    if value is None:
        return []
    return [f"{label}: {format_uah(value)}"]


def build_equity_capital_trend_line(years: dict[str, FinancialYearData], max_years: int = 3) -> str | None:
    points: list[tuple[str, int]] = []
    for year in sorted(years, key=sort_financial_year):
        equity = financial_year_equity_uah(years[year])
        if equity is not None:
            points.append((year, equity))
    if len(points) < 2:
        return None

    recent_points = points[-max_years:]
    first_year, first_value = recent_points[0]
    last_year, last_value = recent_points[-1]
    if last_value > first_value:
        trend = "зростає"
    elif last_value < first_value:
        trend = "знижується"
    else:
        trend = "без суттєвих змін"
    return (
        "Динаміка власного капіталу: "
        f"{trend} ({first_year}: {format_uah(first_value)} → {last_year}: {format_uah(last_value)})."
    )


def financial_year_equity_uah(year_data: FinancialYearData) -> int | None:
    if year_data.equity_uah is not None:
        return year_data.equity_uah
    if year_data.assets_uah is None or year_data.liabilities_uah is None:
        return None
    return year_data.assets_uah - year_data.liabilities_uah


def sort_financial_year(year: str) -> int:
    return int(year) if year.isdigit() else 0


def format_uah(value: int | float) -> str:
    return f"{format_int(int(value))} грн"


def format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def build_good_lines(
    lookup_result: CompanyLookupResult,
    *,
    status: str | None,
    company_age_years: int | None,
    kved: str | None,
    tax_data: dict | None = None,
    clarity_data: ClarityData | None = None,
) -> list[str]:
    lines: list[str] = []
    if status and "зареєстр" in status.lower():
        lines.append("✅ Компанія має активний/зареєстрований статус у доступних даних.")
    if company_age_years is not None and company_age_years >= 3:
        lines.append("✅ Компанія працює тривалий час.")
    if kved:
        lines.append("ℹ️ Основний КВЕД визначено.")
    if lookup_result.risk_input.has_financial_history:
        lines.append("ℹ️ Знайдено фінансові дані.")
    if not lookup_result.risk_input.has_court_mentions:
        lines.append("✅ Судові згадки не знайдені у відкритому блоці Opendatabot.")
    lines.extend(build_tax_good_lines(tax_data))
    lines.extend(build_clarity_good_lines(clarity_data))
    return lines


LOSS_ASSESSMENT_REASON_TYPES = {
    "small_loss_found",
    "medium_loss_found",
    "large_loss_found",
    "very_large_loss_found",
    "critical_loss_found",
}
FINANCIAL_ASSESSMENT_REASON_TYPES = {
    "negative_equity_found",
    "severe_negative_equity",
    "liabilities_exceed_assets",
    "negative_equity_multiple_years",
    "losses_with_negative_equity",
    "weak_financial_position",
} | LOSS_ASSESSMENT_REASON_TYPES
POSITIVE_FINANCIAL_ASSESSMENT_REASON_TYPES = {
    "positive_profit_found",
    "positive_equity_found",
    "equity_growth_found",
    "assets_exceed_liabilities",
    "strong_revenue_found",
    "strong_financial_profile",
    "very_strong_financial_profile",
}


def build_assessment_reason_lines(
    lookup_result: CompanyLookupResult,
    final_risk: dict,
    *,
    status: str | None,
    company_age_years: int | None,
    kved: str | None,
    clarity_data: ClarityData | None = None,
    tax_data: dict | None = None,
    contacts_summary: dict | None = None,
    youcontrol_data: dict | None = None,
) -> list[str]:
    company = lookup_result.company_data or CompanyData()
    lines: list[str] = []
    status_is_registered = bool(status and "зареєстр" in status.lower())
    status_is_terminal = bool(status and is_terminal_status(status))
    if status_is_registered and company_age_years is not None and company_age_years >= 3:
        lines.append("✅ Компанія зареєстрована та працює тривалий час.")
    elif status_is_registered:
        lines.append("✅ Компанія має зареєстрований статус у доступних даних.")
    elif company_age_years is not None and company_age_years >= 3 and not status_is_terminal:
        lines.append("✅ Компанія працює тривалий час.")

    if core_registration_data_present(company, status):
        lines.append("✅ Відкриті джерела підтверджують основні реєстраційні дані.")
    if kved:
        lines.append(f"✅ Основний КВЕД визначено: {as_sentence(kved)}")
    if contacts_are_confirmed(contacts_summary):
        lines.append("✅ Контактні дані підтверджені відкритими джерелами.")

    reason_types = {reason.get("type") for reason in final_risk.get("reasons", [])}
    if not reason_types.intersection({"bankruptcy_found", "company_in_termination", "company_inactive", "company_status_mismatch"}):
        lines.append("✅ Ознак банкрутства або припинення у доступних відкритих даних не виявлено.")
    debt_reason_types = {
        "tax_debt_found",
        "large_tax_debt_found",
        "tax_debt_enforcement_found",
        "debt_collection_found",
        "debtor_registry_found",
    }
    if not reason_types.intersection(debt_reason_types) and tax_debts_not_found(clarity_data, tax_data):
        lines.append("✅ Податковий борг та борг ЄСВ у доступних даних не виявлено.")
    enforcement_assessment_lines = build_clarity_enforcement_assessment_lines(clarity_data)
    lines.extend(enforcement_assessment_lines)

    court_line = build_court_mentions_assessment_line(lookup_result, youcontrol_data)
    if court_line:
        lines.append(court_line)
    lines.extend(build_positive_financial_assessment_lines(reason_types))

    group_financial_reasons = should_group_financial_assessment_reasons(reason_types)
    financial_reason_added = False
    for reason in final_risk.get("reasons", []):
        reason_type = reason.get("type")
        if reason.get("weight", 0) <= 0 or reason_type == "court_cases_found":
            continue
        if reason_type in {"enforcement_found", "many_enforcement_proceedings_found"} and enforcement_assessment_lines:
            continue
        if reason_type == "many_court_mentions_found" and court_line:
            continue
        if reason_type == "prozorro_sale_bankruptcy_asset_sale" and "bankruptcy_found" in reason_types:
            continue
        if (
            group_financial_reasons
            and reason_type in FINANCIAL_ASSESSMENT_REASON_TYPES
            and reason_type not in LOSS_ASSESSMENT_REASON_TYPES
        ):
            if not financial_reason_added:
                lines.append(f"⚠️ {format_financial_assessment_reason(reason_types)}")
                financial_reason_added = True
            continue
        lines.append(f"⚠️ {user_risk_reason_text(reason, lookup_result)}")
    return dedupe_lines(lines)


def should_group_financial_assessment_reasons(reason_types: set[str]) -> bool:
    financial_reason_types = reason_types.intersection(FINANCIAL_ASSESSMENT_REASON_TYPES)
    return "weak_financial_position" in financial_reason_types or len(financial_reason_types) >= 2


def format_financial_assessment_reason(reason_types: set[str]) -> str:
    details: list[str] = []
    if reason_types.intersection({"negative_equity_found", "severe_negative_equity"}):
        details.append("від’ємний власний капітал")
    if "liabilities_exceed_assets" in reason_types:
        details.append("зобов’язання перевищують активи")
    if "severe_negative_equity" in reason_types:
        details.append("суттєвий дефіцит капіталу")
    if "negative_equity_multiple_years" in reason_types:
        details.append("від’ємний капітал у кількох періодах")
    if "losses_with_negative_equity" in reason_types:
        details.append("збиток на фоні від’ємного капіталу")
    if not details:
        return "Фінансова звітність показує слабкий фінансовий стан."
    return f"Фінансова звітність показує комплексні проблеми: {', '.join(details)}."


def build_positive_financial_assessment_lines(reason_types: set[str]) -> list[str]:
    if not reason_types.intersection(POSITIVE_FINANCIAL_ASSESSMENT_REASON_TYPES):
        return []
    if reason_types.intersection(
        FINANCIAL_ASSESSMENT_REASON_TYPES
        | {"bankruptcy_found", "company_in_termination", "company_inactive", "sanctions_found"}
    ):
        return []

    lines: list[str] = []
    if reason_types.intersection({"strong_financial_profile", "very_strong_financial_profile"}):
        lines.append(
            "✅ Фінансовий профіль виглядає стабільним: прибуток, активи перевищують зобов’язання, власний капітал позитивний."
        )
    if "equity_growth_found" in reason_types:
        lines.append("✅ Власний капітал зростає.")
    if reason_types.intersection({"strong_revenue_found", "very_strong_financial_profile"}):
        lines.append("✅ Компанія має значний дохід/активи.")
    return lines


def build_court_mentions_assessment_line(
    lookup_result: CompanyLookupResult,
    youcontrol_data: dict | None = None,
) -> str | None:
    opendatabot_count = get_court_mentions_count(lookup_result)
    youcontrol_count = get_youcontrol_court_mentions_count(youcontrol_data)
    has_opendatabot_mentions = lookup_result.risk_input.has_court_mentions or lookup_result.court_data.has_court_mentions
    if has_opendatabot_mentions and youcontrol_count is not None and youcontrol_count != opendatabot_count:
        return (
            "⚠️ Судові документи: "
            f"Opendatabot — {format_court_count_for_user(opendatabot_count)}, "
            f"YouControl — {format_court_count_for_user(youcontrol_count)}. "
            "Потрібна ручна перевірка змісту справ."
        )
    if has_opendatabot_mentions:
        count_text = format_court_count_for_user(opendatabot_count) if opendatabot_count else "знайдено"
        return f"⚠️ Судові документи: {count_text}. Потрібна ручна перевірка змісту справ."
    if youcontrol_count:
        return (
            f"⚠️ Судові документи за YouControl: {format_court_count_for_user(youcontrol_count)}. "
            "Потрібна ручна перевірка змісту справ."
        )
    return None


def get_youcontrol_court_mentions_count(youcontrol_data: dict | None) -> int | None:
    if not youcontrol_data or not youcontrol_data.get("found"):
        return None
    for signal in youcontrol_data.get("signals") or []:
        signal_text = str(signal)
        if signal_text.lower().startswith(("судові справи:", "судові згадки:")):
            return parse_first_int_from_text(signal_text)
    return None


def parse_first_int_from_text(text: str) -> int | None:
    match = re.search(r"\d+", text.replace(" ", ""))
    return int(match.group(0)) if match else None


def format_court_count_for_user(count: int) -> str:
    return format_int(count)


def core_registration_data_present(company: CompanyData, status: str | None) -> bool:
    present_fields = [
        bool(company.short_name or company.full_name),
        bool(company.edrpou),
        bool(status),
        bool(company.registration_date),
        bool(company.director),
        bool(company.address),
    ]
    return sum(present_fields) >= 4


def contacts_are_confirmed(contacts_summary: dict | None) -> bool:
    if not isinstance(contacts_summary, dict):
        return False
    for field in ("website", "phone", "email"):
        contact = contacts_summary.get(field) or {}
        if is_displayable_contact_value(field, contact.get("value")) and contact.get("confidence") == "high":
            return True
    return False


def as_sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else f"{text}."


def tax_debts_not_found(clarity_data: ClarityData | None, tax_data: dict | None = None) -> bool:
    if tax_data and (tax_data.get("error") or tax_data.get("checked") is False):
        return False
    if clarity_data and clarity_data.tax:
        if clarity_data.tax.tax_debt is True or clarity_data.tax.esv_debt is True:
            return False
        if clarity_data.tax.tax_debt is False and clarity_data.tax.esv_debt is False:
            return True
    tax_debt = (tax_data or {}).get("tax_debt") or {}
    if tax_data and tax_data.get("checked") and not tax_data.get("error") and tax_debt.get("found") is False:
        return True
    return False


def build_clarity_enforcement_assessment_lines(clarity_data: ClarityData | None) -> list[str]:
    if clarity_data is None or clarity_data.status not in {CLARITY_FOUND, CLARITY_PARTIAL}:
        return []
    signals = clarity_data.signals
    if not signals or signals.enforcement_proceedings_count is None or signals.enforcement_proceedings_count <= 0:
        return []
    if signals.enforcement_proceedings_count > 100:
        return ["⚠️ велика кількість записів, пов’язаних з виконавчими провадженнями"]
    if signals.enforcement_proceedings_count >= 10:
        return ["⚠️ Виявлено значну кількість виконавчих проваджень."]
    return [f"⚠️ Виконавчі провадження: {signals.enforcement_proceedings_count}"]


def build_caution_lines(
    lookup_result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None,
    debtors_registry_data: dict | None,
    tax_data: dict | None,
    final_risk: dict,
) -> list[str]:
    lines: list[str] = []
    reason_types = {reason.get("type") for reason in final_risk.get("reasons", [])}
    if lookup_result.risk_input.company_age_years is not None and lookup_result.risk_input.company_age_years < 3:
        lines.append("ℹ️ Компанія зареєстрована відносно нещодавно.")
    if lookup_result.risk_input.has_court_mentions and "court_cases_found" not in reason_types:
        lines.append(format_court_mentions_line(get_court_mentions_count(lookup_result)))
    lines.extend(line for line in build_debtors_signal_lines(debtors_registry_data) if line)
    lines.extend(line for line in build_tax_signal_lines(tax_data) if line)
    lines.extend(line for line in build_clarity_caution_lines(clarity_data) if line)
    return dedupe_lines(lines)


def build_top_risk_reason_lines(
    final_risk: dict,
    *,
    lookup_result: CompanyLookupResult | None = None,
    limit: int = 3,
) -> list[str]:
    reasons = sorted(
        [reason for reason in final_risk["reasons"] if reason.get("weight", 0) > 0],
        key=lambda reason: reason["weight"],
        reverse=True,
    )
    return [f"• {user_risk_reason_text(reason, lookup_result)}" for reason in reasons[:limit]]


def user_risk_reason_text(reason: dict, lookup_result: CompanyLookupResult | None = None) -> str:
    reason_type = reason.get("type")
    if reason.get("status") == "conflict" and reason_type == "bankruptcy_found":
        return "Є суперечливі дані щодо банкрутства. Потрібна ручна перевірка першоджерел."
    if reason_type == "court_cases_found":
        if lookup_result is not None:
            return format_court_mentions_line(get_court_mentions_count(lookup_result)).removeprefix("ℹ️ ")
        return "Судові документи потребують ручної перевірки змісту."
    if reason_type == "website_unavailable":
        return "Сайт не вдалося перевірити автоматично. Це не є доказом ризику, але потребує ручної перевірки."
    if reason_type == "company_status_mismatch":
        return "Джерела по-різному показують статус компанії. Потрібна ручна перевірка."
    if reason_type == "tax_debt_found":
        opendatabot_text = first_reason_evidence_text(reason, "opendatabot")
        if opendatabot_text:
            return format_opendatabot_tax_debt_reason(opendatabot_text)
        detailed_clarity_text = first_reason_evidence_text(reason, "clarity_project", prefix="Clarity показує податковий борг:")
        if detailed_clarity_text:
            return detailed_clarity_text
        if reason_has_source(reason, "tax"):
            return "Знайдено податковий борг у доступних даних ДПС."
        return first_reason_evidence_text(reason, "clarity_project") or "Знайдено податковий борг у доступних податкових даних."
    if reason_type == "tax_debt_enforcement_found":
        return "Виявлено виконавче провадження на користь ДПС / державного бюджету."
    if reason_type == "many_enforcement_proceedings_found":
        return "Виявлено значну кількість виконавчих проваджень."
    if reason_type == "many_court_mentions_found":
        return "Є значна кількість судових документів у відкритих джерелах."
    if reason_type == "low_statutory_capital_with_debt":
        capital = (lookup_result.company_data.statutory_capital_uah if lookup_result and lookup_result.company_data else None)
        if capital is not None:
            return f"Статутний капітал невеликий: {format_uah(capital)}."
        return "Статутний капітал невеликий на фоні боргових ознак."
    if reason_type == "large_tax_debt_found":
        detailed_clarity_text = first_reason_evidence_text(reason, "clarity_project", prefix="Сума податкового боргу за Clarity")
        if detailed_clarity_text:
            return detailed_clarity_text
        return "Сума податкового боргу виглядає суттєвою, тому передоплата потребує додаткової перевірки."
    return reason.get("description") or "Є ризикова ознака, яку потрібно перевірити вручну."


def first_reason_evidence_text(reason: dict, source: str, prefix: str | None = None) -> str | None:
    for evidence in reason.get("evidence") or []:
        if evidence.get("source") != source:
            continue
        raw_text = evidence.get("raw_text")
        if isinstance(raw_text, str) and raw_text.strip():
            text = raw_text.strip()
            if prefix is None or text.startswith(prefix):
                return text
    return None


def reason_has_source(reason: dict, source: str) -> bool:
    return source in (reason.get("sources") or [])


def format_opendatabot_tax_debt_reason(raw_text: str) -> str:
    count = parse_first_int_from_text(raw_text) or 1
    return f"Opendatabot показує, що ДПС стягує з компанії {count} {plural_tax_debt(count)}."


def plural_uk(count: int, singular: str, paucal: str, plural: str) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return singular
    if count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        return paucal
    return plural


def plural_tax_debt(count: int) -> str:
    return plural_uk(count, "податковий борг", "податкові борги", "податкових боргів")


def get_court_mentions_count(lookup_result: CompanyLookupResult) -> int:
    return (
        lookup_result.risk_input.court_mentions_count
        or lookup_result.court_data.court_mentions_count
        or lookup_result.risk_input.total_court_cases_found
        or lookup_result.court_data.total_cases_found
    )


def format_court_mentions_line(court_mentions_count: int) -> str:
    count_text = format_court_count_for_user(court_mentions_count) if court_mentions_count else "знайдено"
    return f"ℹ️ Судові документи: {count_text}. Потрібна ручна перевірка змісту справ."


def build_court_document_block_lines(lookup_result: CompanyLookupResult) -> list[str]:
    if not has_court_source(lookup_result):
        return []
    details_limit = 3
    lines = [format_court_document_count_line(lookup_result)]
    shown_count_line = format_court_shown_details_count_line(lookup_result, limit=details_limit)
    if shown_count_line:
        lines.append(shown_count_line)
    lines.extend(build_court_decision_lines(lookup_result, limit=details_limit))
    return lines


def format_court_shown_details_count_line(lookup_result: CompanyLookupResult, *, limit: int) -> str | None:
    decisions = lookup_result.court_data.decisions if lookup_result.court_data else []
    shown_count = min(len(decisions), limit)
    total_count = get_court_mentions_count(lookup_result)
    if shown_count <= 0 or total_count <= shown_count:
        return None
    return f"Показано деталізованих документів: {format_int(shown_count)} з {format_int(total_count)}."


def format_court_document_count_line(lookup_result: CompanyLookupResult) -> str:
    count = get_court_mentions_count(lookup_result)
    if count:
        return f"Знайдено судових документів: {format_int(count)}."
    return "Судові документи: знайдено. Кількість у доступних даних не визначена."


def has_court_source(lookup_result: CompanyLookupResult) -> bool:
    court_data = lookup_result.court_data
    if not court_data:
        return False
    return bool(
        court_data.has_court_mentions
        or get_court_mentions_count(lookup_result) > 0
        or court_data.decisions
        or court_data.source_urls
        or court_data.risk_flags
    )


def build_court_decision_lines(lookup_result: CompanyLookupResult, *, limit: int = 5) -> list[str]:
    decisions = lookup_result.court_data.decisions if lookup_result.court_data else []
    lines: list[str] = []
    for index, decision in enumerate(decisions[:limit], start=1):
        lines.extend(format_court_decision_lines(index, decision))
    return lines


def format_court_decision_lines(index: int, decision: dict) -> list[str]:
    document_type = str(decision.get("document_type") or "Судовий документ").strip()
    decision_date = str(decision.get("decision_date") or "").strip()
    case_number = str(decision.get("case_number") or "").strip()
    url = first_nonempty_text(decision, "url", "source_url", "document_url", "link")
    title = document_type
    if decision_date:
        title = f"{title} від {decision_date}"
    if case_number:
        title = f"{title}, справа №{case_number}"
    lines = [f"{index}. {title}"]
    if url:
        lines.append(f"   Посилання: {url}")
    return lines


def short_text(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1].rstrip()}…"


def dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result


def build_signal_lines(
    lookup_result: CompanyLookupResult,
    *,
    effective_company_age_years: int | None = None,
    effective_kved: str | None = None,
) -> list[str]:
    risk_input = lookup_result.risk_input
    company_age_years = (
        effective_company_age_years
        if effective_company_age_years is not None
        else risk_input.company_age_years
    )
    main_activity_defined = bool(effective_kved or risk_input.main_activity_code)
    signals: list[str] = []
    if company_age_years is None:
        signals.append("ℹ️ Не вдалося визначити вік компанії.")
    elif company_age_years >= 3:
        signals.append("✅ Компанія працює тривалий час.")
    else:
        signals.append("ℹ️ Компанія зареєстрована відносно нещодавно.")

    if main_activity_defined:
        signals.append("ℹ️ Основний КВЕД визначено.")
    else:
        signals.append("ℹ️ Основний КВЕД не вдалося визначити.")

    if risk_input.has_financial_history:
        signals.append("ℹ️ Знайдено фінансові дані.")
    else:
        signals.append("ℹ️ Фінансові дані не знайдені у відкритому блоці.")

    if risk_input.has_court_mentions:
        court_mentions_count = risk_input.court_mentions_count or risk_input.total_court_cases_found
        signals.append(format_court_mentions_line(court_mentions_count))
    else:
        signals.append("✅ Судові згадки не знайдені у відкритому блоці.")

    return signals


def calculate_company_age_years(registration_date: str | None) -> int | None:
    if not registration_date:
        return None
    for date_format in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            registered_at = datetime.strptime(registration_date, date_format).date()
            break
        except ValueError:
            registered_at = None
    if registered_at is None:
        return None

    today = date.today()
    return today.year - registered_at.year - ((today.month, today.day) < (registered_at.month, registered_at.day))


def build_debtors_signal_lines(debtors_registry_data: dict | None) -> list[str]:
    if not debtors_registry_data or not debtors_registry_data.get("found"):
        return []

    risk_flags = set(debtors_registry_data.get("risk_flags") or [])
    items_count = int(debtors_registry_data.get("items_count") or 0)
    lines: list[str] = []
    if "debtor_registry_found" in risk_flags:
        lines.append("⚠️ Компанія знайдена в Єдиному реєстрі боржників.")
    if "multiple_debtor_records" in risk_flags or items_count >= 3:
        lines.append("⚠️ Знайдено кілька записів у Єдиному реєстрі боржників.")
    if "salary_debt_enforcement_found" in risk_flags:
        lines.append("⚠️ Є виконавче провадження щодо заборгованості із заробітної плати.")
    if "court_fee_enforcement_found" in risk_flags:
        lines.append("⚠️ Є виконавчі провадження щодо стягнення судового збору.")
    if "tax_debt_enforcement_found" in risk_flags:
        lines.append("⚠️ Виявлено виконавче провадження на користь ДПС / державного бюджету.")
    return lines


def build_tax_good_lines(tax_data: dict | None) -> list[str]:
    if not tax_data or not tax_data.get("checked") or tax_data.get("error"):
        return []
    tax_debt = tax_data.get("tax_debt") or {}
    if tax_debt.get("found") is False:
        return ["✅ Податковий борг у доступному наборі ДПС не знайдено."]
    return []


def build_tax_signal_lines(tax_data: dict | None) -> list[str]:
    if not tax_data or not tax_data.get("checked") or tax_data.get("error"):
        return []

    risk_flags = set(tax_data.get("risk_flags") or [])
    lines: list[str] = []
    if "tax_debt_found" in risk_flags:
        lines.append("⚠️ Знайдено податковий борг у доступних даних ДПС.")
    if "large_tax_debt_found" in risk_flags:
        lines.append(
            "⚠️ Сума податкового боргу виглядає суттєвою, тому передоплата потребує додаткової перевірки."
        )
    if "vat_registration_cancelled" in risk_flags or "vat_status_problem" in risk_flags:
        lines.append("⚠️ Є ознаки проблеми з ПДВ-статусом.")
    return lines


def build_website_check_lines(domain_reputation_data: dict | None) -> list[str]:
    if not domain_reputation_data or not domain_reputation_data.get("checked"):
        return []

    if domain_reputation_data.get("error") == "website_unavailable" or not domain_reputation_data.get("found"):
        return [
            "⚠️ Сайт не вдалося перевірити автоматично. Це не є доказом ризику, але потребує ручної перевірки."
        ]

    flags = set(domain_reputation_data.get("risk_flags") or [])
    lines: list[str] = []
    http = domain_reputation_data.get("http") or {}
    ssl_info = domain_reputation_data.get("ssl") or {}
    dns_info = domain_reputation_data.get("dns") or {}
    if http.get("status_code") and int(http["status_code"]) < 400:
        lines.append("✅ Сайт відкривається")
    if ssl_info.get("present"):
        lines.append("✅ HTTPS працює")
    if dns_info.get("found"):
        lines.append("✅ DNS-записи знайдено")
    if "company_edrpou_not_found_on_website" in flags:
        lines.append("⚠️ На сайті не знайдено ЄДРПОУ компанії")
    if "company_name_not_found_on_website" in flags:
        lines.append("⚠️ На сайті не знайдено назву компанії")
    if "free_email_used" in flags:
        lines.append("⚠️ Знайдено тільки безкоштовну email-адресу")
    if "ssl_missing" in flags:
        lines.append("⚠️ HTTPS/SSL не підтверджено")
    if "dns_not_found" in flags:
        lines.append("⚠️ DNS-записи домену не підтверджено")
    if "suspicious_redirects" in flags:
        lines.append("⚠️ Сайт має підозрілі редиректи")
    if "empty_website" in flags:
        lines.append("⚠️ Сайт відкривається, але сторінка майже порожня")
    return dedupe_lines(lines)


def build_contact_lines(domain_reputation_data: dict | None) -> list[str]:
    if not domain_reputation_data or not domain_reputation_data.get("checked") or not domain_reputation_data.get("found"):
        return []
    contacts = domain_reputation_data.get("contacts") or {}
    lines: list[str] = []
    if is_displayable_contact_value("website", domain_reputation_data.get("url")):
        lines.append(f"🌐 Сайт: {domain_reputation_data['url']}")
    phones = [phone for phone in (contacts.get("phones") or []) if is_displayable_contact_value("phone", phone)]
    if phones:
        lines.append(f"☎️ Телефон: {', '.join(phones[:3])}")
    emails = [email for email in (contacts.get("emails") or []) if is_displayable_contact_value("email", email)]
    if emails:
        lines.append(f"✉️ Email: {', '.join(emails[:3])}")
    return lines


def build_contacts_summary_lines(contacts_summary: dict | None) -> list[str]:
    if not contacts_summary:
        return []
    lines: list[str] = []
    for field, icon, label in (
        ("website", "🌐", "Сайт"),
        ("phone", "☎️", "Телефон"),
        ("email", "✉️", "Email"),
    ):
        contact = contacts_summary.get(field) or {}
        value = contact.get("value")
        if is_displayable_contact_value(field, value):
            lines.append(f"{icon} {label}: {format_contact_value(field, str(value))}")
    return lines


def is_displayable_contact_value(field: str, value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    lowered = text.casefold()
    if "*" in text:
        return False
    if "не вдалося автоматично перевірити" in lowered or "не знайдено" in lowered:
        return False
    if "невідом" in lowered or "unknown" in lowered:
        return False
    if field == "phone" and len("".join(char for char in text if char.isdigit())) < 5:
        return False
    if field == "email" and "@" not in text:
        return False
    return True


def format_contact_value(field: str, value: str) -> str:
    if field != "phone":
        return value
    digits = "".join(char for char in value if char.isdigit())
    if digits.startswith("38") and len(digits) == 12:
        national = digits[2:]
        if national.startswith("03422") and len(national) == 10:
            return f"(03422) {national[5:8]}-{national[8:]}"
        if national.startswith("0522") and len(national) == 10:
            return f"+38 ({national[:4]}) {national[4:6]}-{national[6:8]}-{national[8:]}"
    return value


def contact_confidence_label(confidence: str | None) -> str:
    return {
        "high": "високий",
        "medium": "середній",
        "low": "низький",
        "unknown": "невідомий",
    }.get(confidence or "unknown", "невідомий")


def contact_source_label(source: str) -> str:
    return {
        "ua-region.com.ua": "UA-REGION",
        "prat.ua/pat.ua": "PRAT/PAT",
        "smida.gov.ua": "SMIDA",
        "business-guide.com.ua": "Business Guide",
    }.get(source, source)


def build_conflict_lines(final_risk: dict) -> list[str]:
    conflicts = final_risk.get("conflicts") or []
    lines: list[str] = []
    for conflict in conflicts:
        found_sources = ", ".join(conflict.get("found_sources") or [])
        not_found_sources = ", ".join(conflict.get("not_found_sources") or [])
        lines.append(
            f"• {conflict.get('label_uk')}: одні джерела підтверджують ({found_sources}), інші не підтверджують ({not_found_sources}). Потребує ручної перевірки."
        )
    return lines


def build_clarity_good_lines(clarity_data: ClarityData | None) -> list[str]:
    if clarity_data is None or clarity_data.status not in {CLARITY_FOUND, CLARITY_PARTIAL}:
        return []

    tax = clarity_data.tax
    signals = clarity_data.signals
    lines: list[str] = []
    if signals and signals.bankruptcy_count == 0:
        lines.append("✅ Банкрутство у Clarity не виявлено.")
    if tax and tax.tax_debt is False:
        lines.append("✅ Податковий борг у Clarity не виявлено.")
    if tax and tax.esv_debt is False:
        lines.append("✅ Борг ЄСВ у Clarity не виявлено.")
    return lines


def build_clarity_caution_lines(clarity_data: ClarityData | None) -> list[str]:
    if clarity_data is None or clarity_data.status not in {CLARITY_FOUND, CLARITY_PARTIAL}:
        return []

    tax = clarity_data.tax
    signals = clarity_data.signals
    lines: list[str] = []
    if signals and signals.bankruptcy_count and signals.bankruptcy_count > 0:
        lines.append("• У Clarity є ознаки банкрутства, потрібно звірити актуальний стан справ.")
    if tax and tax.tax_debt is True:
        lines.append("• У Clarity є ознака податкового боргу.")
    if tax and tax.esv_debt is True:
        lines.append("• У Clarity є ознака боргу ЄСВ.")
    if signals and signals.enforcement_proceedings_count is not None:
        if signals.enforcement_proceedings_count > 100:
            lines.append("• велика кількість записів, пов’язаних з виконавчими провадженнями")
        elif signals.enforcement_proceedings_count > 0:
            lines.append(f"• Виконавчі провадження: {signals.enforcement_proceedings_count}")
    return lines


def build_clarity_signal_lines(clarity_data: ClarityData | None) -> list[str]:
    if clarity_data is None or clarity_data.status not in {CLARITY_FOUND, CLARITY_PARTIAL}:
        return []

    tax = clarity_data.tax
    signals = clarity_data.signals
    lines = ["", "Додаткові сигнали Clarity:"]
    if signals and signals.bankruptcy_count is not None:
        lines.append(
            f"• Банкрутство: {'виявлено' if signals.bankruptcy_count > 0 else 'не виявлено'}"
        )
    if tax and tax.tax_debt is not None:
        lines.append(f"• Податковий борг: {'виявлено' if tax.tax_debt else 'відсутній'}")
    if tax and tax.esv_debt is not None:
        lines.append(f"• Борг ЄСВ: {'виявлено' if tax.esv_debt else 'відсутній'}")
    if signals and signals.enforcement_proceedings_count is not None:
        if signals.enforcement_proceedings_count > 100:
            lines.append("• велика кількість записів, пов’язаних з виконавчими провадженнями")
        else:
            lines.append(f"• Виконавчі провадження: {signals.enforcement_proceedings_count}")
    if signals and signals.edr_history_count is not None:
        lines.append(f"• Історія ЄДР: {signals.edr_history_count} записів")
    return lines if len(lines) > 2 else []


def build_limitation_lines(
    lookup_result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None = None,
    debtors_registry_data: dict | None = None,
    tax_data: dict | None = None,
    domain_reputation_data: dict | None = None,
    contacts_summary: dict | None = None,
) -> list[str]:
    limitations: list[str] = []
    if lookup_result.status == PARTIAL or lookup_result.parse_warnings:
        limitations.append("• Opendatabot повернув неповні дані, тому частину полів варто перевірити вручну.")

    if clarity_data is not None:
        if clarity_data.status == CLARITY_PARTIAL or clarity_data.parse_warnings:
            limitations.append("• Clarity повернула неповні дані, тому додаткові сигнали можуть бути не повними.")
        elif clarity_data.status == CLARITY_SOURCE_ERROR and clarity_data.error == "analysis_timeout":
            limitations.append("• Clarity не встигла відповісти, тому додаткові сигнали не враховані.")
        elif clarity_data.status == CLARITY_SOURCE_ERROR:
            limitations.append("• Clarity тимчасово недоступний, тому додаткові сигнали не враховані.")

    if youcontrol_data and not youcontrol_data.get("found") and youcontrol_data.get("error"):
        if youcontrol_data.get("error") == "blocked_or_unavailable":
            limitations.append("• YouControl тимчасово недоступний або обмежив автоматичний доступ, тому це джерело не враховане.")
        elif youcontrol_data.get("error") == "company_not_found":
            limitations.append("• YouControl не знайшов компанію за цим ЄДРПОУ, варто перевірити це джерело вручну.")
        else:
            limitations.append("• YouControl повернув неповні або неузгоджені дані, тому це джерело потребує ручної перевірки.")

    if debtors_registry_data and not debtors_registry_data.get("checked") and debtors_registry_data.get("error"):
        limitations.append(
            "• Єдиний реєстр боржників тимчасово недоступний або форма не може бути оброблена, тому це джерело не підвищує ризик автоматично."
        )

    if tax_data and not tax_data.get("checked") and tax_data.get("error"):
        limitations.append("• ДПС / податкові відкриті дані не вдалося перевірити автоматично.")

    if domain_reputation_data and domain_reputation_data.get("error") == "website_source_unavailable":
        limitations.append("• Технічну перевірку сайту не вдалося виконати автоматично.")

    if contacts_summary and contacts_summary_has_unavailable_sources(contacts_summary):
        limitations.append("• Частина джерел могла бути недоступна або повернути неповні дані.")

    if not limitations:
        return []
    return ["", "Обмеження перевірки:", *limitations]


def contacts_summary_has_unavailable_sources(contacts_summary: dict) -> bool:
    source_statuses = contacts_summary.get("source_statuses") or {}
    return any(status in {"unavailable", "blocked", "parse_error", "analysis_timeout"} for status in source_statuses.values())


def build_risk_flag_lines(
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None = None,
) -> list[str]:
    final_risk = calculate_final_risk(collect_source_risk_flags(CompanyLookupResult(status="found", edrpou="00000000"), clarity_data, youcontrol_data))
    reasons = [reason for reason in final_risk["reasons"] if reason["weight"] > 0]
    if not reasons and clarity_data and clarity_data.risk_flags:
        risk_level = clarity_risk_level(clarity_data)
        lines = ["", "Можливі ризикові ознаки:", f"Рівень: {format_risk_level(risk_level)}"]
        for flag in clarity_data.risk_flags[:3]:
            lines.append(f"• {flag.text}")
        return lines
    if not reasons:
        return []

    lines = ["", "Можливі ризикові ознаки:", f"Рівень: {format_risk_level(final_risk['level'])}"]
    for reason in reasons[:3]:
        lines.append(f"• {reason['description']}")
    return lines


def clarity_risk_level(clarity_data: ClarityData | None) -> str:
    if clarity_data is None or not clarity_data.risk_flags:
        return "low"
    return highest_risk_level([flag.level for flag in clarity_data.risk_flags])


def combined_risk_level(
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None = None,
) -> str:
    return calculate_final_risk(
        collect_source_risk_flags(CompanyLookupResult(status="found", edrpou="00000000"), clarity_data, youcontrol_data)
    )["level"]


def build_plain_language_summary(final_risk: dict) -> str:
    if final_risk.get("manual_review_required") or final_risk["level"] == "manual_review":
        return "Є суперечливі дані між джерелами. Перед передоплатою потрібна ручна перевірка першоджерел."
    if final_risk["level"] == "critical":
        return "Є сильні ризикові ознаки. Передоплата без додаткової перевірки може бути небезпечною."
    if final_risk["level"] == "high":
        return "Є кілька суттєвих сигналів, які варто перевірити перед оплатою або договором."
    if final_risk["level"] == "medium":
        return "Критичних ознак не видно, але є сигнали, які потребують додаткової перевірки."
    return "У доступних джерелах немає суттєвих ризикових ознак, але базову перевірку документів все одно варто зробити."


def build_recommendation_text(risk_level: str) -> str:
    if risk_level == "manual_review":
        return "Потрібна ручна перевірка суперечливих джерел, документів і реквізитів перед будь-якою передоплатою."
    if risk_level == "critical":
        return (
            "За таких ознак не рекомендується робити передоплату без додаткової перевірки документів, реквізитів, судових матеріалів "
            "та підтвердження фактичної наявності товару або послуги."
        )
    if risk_level == "high":
        return (
            "Є можливі суттєві ризикові ознаки: не рекомендується робити передоплату без додаткової перевірки "
            "документів, реквізитів, умов поставки та консультації з відповідальним фахівцем."
        )
    if risk_level == "medium":
        return (
            "Компанія потребує додаткової перевірки перед оплатою: звірте реквізити, договір, податкові/боргові ознаки "
            "та підтвердження наявності товару або послуги."
        )
    return (
        "Критичних ознак у базовій інформаційній перевірці не виявлено. Перед оплатою звірте реквізити, договір, "
        "умови поставки та підтвердження наявності товару."
    )


def format_risk_level(level: str) -> str:
    return {
        "critical": "критичний",
        "high": "високий",
        "medium": "середній",
        "info": "інформаційний",
        "manual_review": "потребує ручної перевірки",
        "low": "низький",
    }.get(level, "низький")


def optional_field(label: str, value: str | None) -> list[str]:
    if not value:
        return []
    return [f"{label}: {value}"]


async def run_source_lookups(
    edrpou: str,
    lookup: Callable[[str], CompanyLookupResult],
    clarity_lookup: Callable[[str], ClarityData],
    youcontrol_lookup: Callable[[str], dict] = fetch_youcontrol_company,
    debtors_lookup: Callable[[str], dict | None] = fetch_debtors_registry,
    tax_lookup: Callable[[str], dict | None] = fetch_tax_status,
    domain_reputation_lookup: Callable[[str | None, dict | None], dict | None] = fetch_domain_reputation,
    contacts_lookup: Callable[[str, dict | None], dict | None] = fetch_company_contacts_async,
    website_url: str | None = None,
    analysis_timeout: float = ANALYSIS_TIMEOUT_SECONDS,
    prozorro_lookup: Callable[[str], ProzorroAnalysis] = lookup_prepared_prozorro,
    prozorro_sale_lookup: Callable[[str], ProzorroSaleAnalysis] = lookup_prozorro_sale_by_edrpou,
) -> tuple[CompanyLookupResult, ClarityData | None, dict | None, dict | None, dict | None, dict | None, dict | None]:
    analysis_deadline = asyncio.get_running_loop().time() + max(0.0, analysis_timeout)
    lookup_task = asyncio.create_task(asyncio.to_thread(lookup, edrpou))
    clarity_task = asyncio.create_task(asyncio.to_thread(clarity_lookup, edrpou))
    youcontrol_task = asyncio.create_task(asyncio.to_thread(youcontrol_lookup, edrpou))
    debtors_task = asyncio.create_task(asyncio.to_thread(debtors_lookup, edrpou))
    tax_task = asyncio.create_task(asyncio.to_thread(tax_lookup, edrpou))
    prozorro_task = asyncio.create_task(asyncio.to_thread(prozorro_lookup, edrpou))
    prozorro_sale_task = asyncio.create_task(asyncio.to_thread(prozorro_sale_lookup, edrpou))
    first_batch_tasks = {
        lookup_task,
        clarity_task,
        youcontrol_task,
        debtors_task,
        tax_task,
        prozorro_task,
        prozorro_sale_task,
    }
    await asyncio.wait(first_batch_tasks, timeout=max(0.0, analysis_timeout))

    result = completed_lookup_result(lookup_task, edrpou)
    clarity_data = completed_clarity_result(clarity_task, edrpou)
    youcontrol_data = completed_youcontrol_result(youcontrol_task, edrpou)
    debtors_registry_data = completed_debtors_result(debtors_task, edrpou)
    tax_data = completed_tax_result(tax_task, edrpou)
    prozorro_analysis = completed_prozorro_result(prozorro_task, edrpou)
    prozorro_sale_analysis = completed_prozorro_sale_result(prozorro_sale_task, edrpou)
    result = result.model_copy(
        update={
            "prozorro_analysis": prozorro_analysis,
            "prozorro_sale_analysis": prozorro_sale_analysis,
        }
    )

    for task in first_batch_tasks:
        if not task.done():
            task.cancel()

    selected_website_url = website_url or extract_website_from_sources(result, clarity_data, youcontrol_data)
    company_context = build_domain_company_context(result, clarity_data, youcontrol_data, selected_website_url)
    domain_task = asyncio.create_task(
        asyncio.to_thread(domain_reputation_lookup, selected_website_url, company_context)
    )
    contacts_task = asyncio.create_task(run_contacts_lookup(contacts_lookup, edrpou, company_context))
    remaining_timeout = max(0.0, analysis_deadline - asyncio.get_running_loop().time())
    if remaining_timeout > 0:
        await asyncio.wait({domain_task, contacts_task}, timeout=remaining_timeout)
    domain_reputation_data = completed_domain_reputation_result(domain_task, selected_website_url)
    contacts_summary = completed_contacts_summary_result(contacts_task, edrpou)
    if not domain_task.done():
        domain_task.cancel()
    if not contacts_task.done():
        contacts_task.cancel()
    return result, clarity_data, youcontrol_data, debtors_registry_data, tax_data, domain_reputation_data, contacts_summary


def completed_lookup_result(
    task: asyncio.Task[CompanyLookupResult],
    edrpou: str,
) -> CompanyLookupResult:
    if task.cancelled() or not task.done():
        return source_error_result(edrpou, "analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Main lookup failed for EDRPOU %s", edrpou)
        return source_error_result(edrpou, "lookup_failed")


def completed_clarity_result(
    task: asyncio.Task[ClarityData],
    edrpou: str,
) -> ClarityData | None:
    if task.cancelled() or not task.done():
        return clarity_source_error_result(edrpou, "analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Clarity lookup failed for EDRPOU %s", edrpou)
        return clarity_source_error_result(edrpou, "lookup_failed")


def completed_youcontrol_result(
    task: asyncio.Task[dict],
    edrpou: str,
) -> dict | None:
    if task.cancelled() or not task.done():
        return youcontrol_source_error_result(edrpou, "analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("YouControl lookup failed for EDRPOU %s", edrpou)
        return youcontrol_source_error_result(edrpou, "lookup_failed")


def completed_debtors_result(
    task: asyncio.Task[dict | None],
    edrpou: str,
) -> dict | None:
    if task.cancelled() or not task.done():
        return debtors_source_error_result(edrpou, "analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Debtors registry lookup failed for EDRPOU %s", edrpou)
        return debtors_source_error_result(edrpou, "lookup_failed")


def completed_tax_result(
    task: asyncio.Task[dict | None],
    edrpou: str,
) -> dict | None:
    if task.cancelled() or not task.done():
        return tax_source_error_result(edrpou, "analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Tax lookup failed for EDRPOU %s", edrpou)
        return tax_source_error_result(edrpou, "lookup_failed")


def completed_prozorro_result(
    task: asyncio.Task[ProzorroAnalysis],
    edrpou: str,
) -> ProzorroAnalysis:
    if task.cancelled() or not task.done():
        return ProzorroAnalysis(status="source_error", error="analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Prozorro lookup failed for EDRPOU %s", edrpou)
        return ProzorroAnalysis(status="source_error", error="lookup_failed")


def completed_prozorro_sale_result(
    task: asyncio.Task[ProzorroSaleAnalysis],
    edrpou: str,
) -> ProzorroSaleAnalysis:
    if task.cancelled() or not task.done():
        return ProzorroSaleAnalysis(status="source_error", error="analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Prozorro.Sale lookup failed for EDRPOU %s", edrpou)
        return ProzorroSaleAnalysis(status="source_error", error="lookup_failed")


def completed_domain_reputation_result(
    task: asyncio.Task[dict | None],
    website_url: str | None,
) -> dict | None:
    if task.cancelled() or not task.done():
        return domain_reputation_source_error_result(website_url, "analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Domain reputation lookup failed for website %s", website_url)
        return domain_reputation_source_error_result(website_url, "lookup_failed")


def completed_contacts_summary_result(
    task: asyncio.Task[dict | None],
    edrpou: str,
) -> dict | None:
    if task.cancelled() or not task.done():
        return contacts_source_error_result(edrpou, "analysis_timeout")
    try:
        return task.result()
    except Exception:
        logging.exception("Contacts lookup failed for EDRPOU %s", edrpou)
        return contacts_source_error_result(edrpou, "lookup_failed")


async def run_contacts_lookup(
    contacts_lookup: Callable[[str, dict | None], dict | None],
    edrpou: str,
    company_context: dict,
) -> dict | None:
    if inspect.iscoroutinefunction(contacts_lookup):
        return await contacts_lookup(edrpou, company_context)
    return await asyncio.to_thread(contacts_lookup, edrpou, company_context)


def source_error_result(edrpou: str, error: str) -> CompanyLookupResult:
    return CompanyLookupResult(
        status=SOURCE_ERROR,
        edrpou=edrpou,
        error=error,
    )


def with_source_diagnostics(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None = None,
    debtors_registry_data: dict | None = None,
    tax_data: dict | None = None,
    domain_reputation_data: dict | None = None,
    contacts_summary: dict | None = None,
) -> CompanyLookupResult:
    prepared_youcontrol_data = prepare_youcontrol_data(result, clarity_data, youcontrol_data)
    diagnostics = build_source_diagnostics(
        result,
        clarity_data,
        prepared_youcontrol_data,
        debtors_registry_data,
        tax_data,
        domain_reputation_data,
    )
    risk_summary = build_risk_summary(
        result,
        clarity_data,
        prepared_youcontrol_data,
        debtors_registry_data,
        tax_data,
        domain_reputation_data,
    )
    sources = build_sources_snapshot(
        result,
        clarity_data,
        prepared_youcontrol_data,
        debtors_registry_data,
        tax_data,
        domain_reputation_data,
        contacts_summary,
    )
    return result.model_copy(
        update={
            "source_diagnostics": diagnostics,
            "clarity_data": clarity_data,
            "youcontrol_data": prepared_youcontrol_data,
            "debtors_registry_data": debtors_registry_data,
            "tax_data": tax_data,
            "domain_reputation_data": domain_reputation_data,
            "contacts_summary": contacts_summary,
            "sources": sources,
            "risk_summary": risk_summary,
        }
    )


def build_source_diagnostics(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None = None,
    debtors_registry_data: dict | None = None,
    tax_data: dict | None = None,
    domain_reputation_data: dict | None = None,
) -> list[SourceDiagnostic]:
    diagnostics: list[SourceDiagnostic] = []
    if should_store_diagnostic(result.status, result.error, result.parse_warnings):
        diagnostics.append(
            SourceDiagnostic(
                source=result.source,
                status=result.status,
                error=result.error,
                warnings=short_warnings(result.parse_warnings),
            )
        )

    if clarity_data and should_store_diagnostic(clarity_data.status, clarity_data.error, clarity_data.parse_warnings):
        diagnostics.append(
            SourceDiagnostic(
                source=clarity_data.source,
                status=clarity_data.status,
                error=clarity_data.error,
                warnings=short_warnings(clarity_data.parse_warnings),
            )
        )
    if youcontrol_data and should_store_youcontrol_diagnostic(youcontrol_data):
        diagnostics.append(
            SourceDiagnostic(
                source="youcontrol",
                status=youcontrol_status(youcontrol_data),
                error=youcontrol_data.get("error"),
                warnings=[],
            )
        )
    if debtors_registry_data and should_store_debtors_diagnostic(debtors_registry_data):
        diagnostics.append(
            SourceDiagnostic(
                source="debtors_registry",
                status=debtors_status(debtors_registry_data),
                error=debtors_registry_data.get("error"),
                warnings=[],
            )
        )
    if tax_data and should_store_tax_diagnostic(tax_data):
        diagnostics.append(
            SourceDiagnostic(
                source="tax",
                status=tax_status(tax_data),
                error=tax_data.get("error"),
                warnings=[],
            )
        )
    if domain_reputation_data and should_store_domain_reputation_diagnostic(domain_reputation_data):
        diagnostics.append(
            SourceDiagnostic(
                source="domain_reputation",
                status=domain_reputation_status(domain_reputation_data),
                error=domain_reputation_data.get("error"),
                warnings=[],
            )
        )
    return diagnostics


def should_store_diagnostic(status: str, error: str | None, warnings: list[str]) -> bool:
    return bool(
        error
        or warnings
        or status in {PARTIAL, PARSE_ERROR, SOURCE_ERROR, CLARITY_PARTIAL, CLARITY_PARSE_ERROR, CLARITY_SOURCE_ERROR}
    )


def short_warnings(warnings: list[str], *, limit: int = 5, max_length: int = 240) -> list[str]:
    return [warning[:max_length] for warning in warnings[:limit]]


def build_risk_summary(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None = None,
    debtors_registry_data: dict | None = None,
    tax_data: dict | None = None,
    domain_reputation_data: dict | None = None,
) -> RiskSummary:
    raw_flags = collect_source_risk_flags(
        result,
        clarity_data,
        youcontrol_data,
        debtors_registry_data,
        tax_data,
        domain_reputation_data,
    )
    final_risk = calculate_final_risk(raw_flags)
    flags = build_risk_flag_snapshots(final_risk)

    return RiskSummary(
        score=final_risk["score"],
        level=final_risk["level"],
        label_uk=final_risk["label_uk"],
        reasons=final_risk["reasons"],
        flags=flags,
        signals=final_risk.get("signals", []),
        conflicts=final_risk.get("conflicts", []),
        manual_review_required=bool(final_risk.get("manual_review_required")),
        hard_fact_present=bool(final_risk.get("hard_fact_present")),
    )


def build_risk_flag_snapshots(final_risk: dict) -> list[RiskFlagSnapshot]:
    flags: list[RiskFlagSnapshot] = []
    for reason in final_risk["reasons"]:
        first_source = reason["sources"][0] if reason["sources"] else "unknown"
        flags.append(
            RiskFlagSnapshot(
                source=first_source,
                sources=reason["sources"],
                level=risk_level_for_weight(reason["weight"]),
                code=reason["type"],
                type=reason["type"],
                weight=reason["weight"],
                text=reason["description"],
            )
        )
    return flags


def risk_level_for_weight(weight: int) -> str:
    if weight >= 80:
        return "critical"
    if weight >= 51:
        return "high"
    if weight >= 21:
        return "medium"
    return "low"


def collect_source_risk_flags(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None = None,
    debtors_registry_data: dict | None = None,
    tax_data: dict | None = None,
    domain_reputation_data: dict | None = None,
) -> list[dict]:
    flags: list[dict] = []
    flags.extend(collect_opendatabot_risk_flags(result))
    opendatabot_tax_debt_found = has_found_flag(flags, "tax_debt_found", "opendatabot")
    if clarity_data:
        clarity_found_types = {
            canonical_risk_type(flag.code)
            for flag in clarity_data.risk_flags
        }
        for flag in clarity_data.risk_flags:
            flags.append(
                {
                    "type": flag.code,
                    "source": clarity_data.source,
                    "status": "found",
                    "confidence": "medium",
                    "text": flag.text,
                    "raw_text": flag.text,
                    "checked_at": clarity_data.checked_at,
                }
            )
        if clarity_data.tax and clarity_data.tax.tax_debt is True:
            if "tax_debt_found" not in clarity_found_types:
                flags.append(
                    {
                        "type": "tax_debt_found",
                        "source": clarity_data.source,
                        "status": "found",
                        "confidence": "medium",
                        "text": format_clarity_tax_debt_text(clarity_data.tax),
                        "raw_text": format_clarity_tax_debt_text(clarity_data.tax),
                        "checked_at": clarity_data.checked_at,
                    }
                )
            if (
                (clarity_data.tax.tax_debt_amount_uah or 0) >= LARGE_CLARITY_TAX_DEBT_THRESHOLD_UAH
                and "large_tax_debt_found" not in clarity_found_types
            ):
                flags.append(
                    {
                        "type": "large_tax_debt_found",
                        "source": clarity_data.source,
                        "status": "found",
                        "confidence": "medium",
                        "text": format_clarity_large_tax_debt_text(clarity_data.tax),
                        "raw_text": format_clarity_large_tax_debt_text(clarity_data.tax),
                        "checked_at": clarity_data.checked_at,
                    }
                )
        if (
            clarity_data.signals
            and clarity_data.signals.bankruptcy_count == 0
            and "bankruptcy_found" not in clarity_found_types
        ):
            flags.append(
                {
                    "type": "bankruptcy_found",
                    "source": clarity_data.source,
                    "status": "not_found",
                    "confidence": "medium",
                    "raw_text": "Банкрутство: не виявлено",
                    "checked_at": clarity_data.checked_at,
                }
            )
        if (
            clarity_data.signals
            and clarity_data.signals.enforcement_proceedings_count == 0
            and "enforcement_found" not in clarity_found_types
        ):
            flags.append(
                {
                    "type": "enforcement_found",
                    "source": clarity_data.source,
                    "status": "not_found",
                    "confidence": "medium",
                    "raw_text": "Виконавчі провадження: відсутні",
                    "checked_at": clarity_data.checked_at,
                }
            )
        if (
            clarity_data.signals
            and clarity_data.signals.enforcement_proceedings_count is not None
            and clarity_data.signals.enforcement_proceedings_count >= 10
        ):
            flags.append(
                {
                    "type": "many_enforcement_proceedings_found",
                    "source": clarity_data.source,
                    "status": "found",
                    "confidence": "medium",
                    "raw_text": f"Виконавчі провадження: {clarity_data.signals.enforcement_proceedings_count}",
                    "checked_at": clarity_data.checked_at,
                }
            )
        if clarity_data.tax and clarity_data.tax.tax_debt is False and "tax_debt_found" not in clarity_found_types:
            if not opendatabot_tax_debt_found:
                flags.append(
                    {
                        "type": "tax_debt_found",
                        "source": clarity_data.source,
                        "status": "not_found",
                        "confidence": "medium",
                        "raw_text": "Податковий борг: відсутній",
                        "checked_at": clarity_data.checked_at,
                    }
                )
            else:
                flags.append(
                    {
                        "type": "tax_debt_source_mismatch",
                        "source": clarity_data.source,
                        "status": "found",
                        "confidence": "medium",
                        "raw_text": "Clarity: податковий борг відсутній; Opendatabot: ДПС стягує податковий борг",
                        "matched_pattern": "tax_debt_found_vs_not_found",
                        "match_type": "debug_note",
                        "checked_at": clarity_data.checked_at,
                    }
                )
        if clarity_data.status == CLARITY_SOURCE_ERROR:
            flags.append({"type": "source_unavailable", "source": clarity_data.source})

    if youcontrol_data:
        youcontrol_found_types = {
            canonical_risk_type(code)
            for code in youcontrol_data.get("risk_flags", [])
        }
        for code in youcontrol_data.get("risk_flags", []):
            flags.append(
                {
                    "type": code,
                    "source": "youcontrol",
                    "status": "found",
                    "confidence": youcontrol_flag_confidence(code),
                    **youcontrol_risk_evidence(code, youcontrol_data),
                }
            )
        flags.extend(collect_youcontrol_not_found_evidence(youcontrol_data, youcontrol_found_types))
        if youcontrol_data.get("error"):
            flags.append({"type": "source_unavailable", "source": "youcontrol"})
    if debtors_registry_data:
        for code in debtors_registry_data.get("risk_flags", []):
            flags.append({"type": code, "source": "debtors_registry"})
        if debtors_registry_data.get("error") and "source_unavailable" not in debtors_registry_data.get("risk_flags", []):
            flags.append({"type": "source_unavailable", "source": "debtors_registry"})
    if tax_data:
        for code in tax_data.get("risk_flags", []):
            flags.append({"type": code, "source": "tax"})
        if tax_data.get("error") and "tax_source_unavailable" not in tax_data.get("risk_flags", []):
            flags.append({"type": "tax_source_unavailable", "source": "tax"})
    if domain_reputation_data:
        for code in domain_reputation_data.get("risk_flags", []):
            flags.append({"type": code, "source": "domain_reputation"})
        if (
            domain_reputation_data.get("error") == "website_source_unavailable"
            and "website_source_unavailable" not in domain_reputation_data.get("risk_flags", [])
        ):
            flags.append({"type": "website_source_unavailable", "source": "domain_reputation"})
    prozorro_analysis = result.prozorro_analysis
    if prozorro_analysis and prozorro_analysis.status in {"found", "partial"}:
        for flag in prozorro_analysis.risk_flags:
            prepared_flag = dict(flag)
            prepared_flag.setdefault("source", "prozorro_analysis")
            prepared_flag.setdefault("status", "found")
            prepared_flag.setdefault("confidence", "medium")
            flags.append(prepared_flag)
        flags.extend(collect_prozorro_search_noise_flags(result))
    prozorro_sale_analysis = result.prozorro_sale_analysis
    if prozorro_sale_analysis and prozorro_sale_analysis.status == "found":
        for flag in prozorro_sale_analysis.risk_flags:
            prepared_flag = dict(flag)
            prepared_flag.setdefault("source", "prozorro_sale")
            prepared_flag.setdefault("status", "found")
            prepared_flag.setdefault("confidence", "medium")
            flags.append(prepared_flag)
    flags.extend(collect_financial_risk_flags(result))
    flags.extend(collect_company_status_risk_flags(result, clarity_data, youcontrol_data))
    flags.extend(collect_company_status_mismatch_flags(result, clarity_data, youcontrol_data))
    flags.extend(collect_low_capital_debt_flags(result, flags))
    return flags


def has_found_flag(flags: list[dict], flag_type: str, source: str | None = None) -> bool:
    for flag in flags:
        if canonical_risk_type(str(flag.get("type") or "")) != flag_type:
            continue
        if source is not None and flag.get("source") != source:
            continue
        if flag.get("status", "found") == "found":
            return True
    return False


def collect_prozorro_search_noise_flags(result: CompanyLookupResult) -> list[dict]:
    prozorro_analysis = result.prozorro_analysis
    if not prozorro_analysis or prozorro_analysis.status not in {"found", "partial"}:
        return []
    search_summary = prozorro_analysis.search_summary
    if not search_summary:
        return []
    if (search_summary.total_count or 0) <= PROZORRO_UNCONFIRMED_SEARCH_NOISE_THRESHOLD:
        return []
    if search_summary.checked_count <= 0:
        return []
    if (search_summary.confirmed_participation_count or 0) > 0:
        return []
    return [
        {
            "type": "prozorro_unconfirmed_search_noise",
            "source": "prozorro_search",
            "status": "found",
            "confidence": "low",
            "raw_text": (
                "Багато результатів пошуку Prozorro без підтвердженої участі компанії: "
                f"{format_int(search_summary.total_count or 0)}."
            ),
            "matched_pattern": "unconfirmed_search_noise",
            "match_type": "search_summary",
        }
    ]


def collect_low_capital_debt_flags(result: CompanyLookupResult, flags: list[dict]) -> list[dict]:
    capital = company_statutory_capital_uah(result)
    if capital is None or capital > 1000:
        return []
    if not any(is_debt_related_flag(flag) for flag in flags):
        return []
    return [
        {
            "type": "low_statutory_capital_with_debt",
            "source": "opendatabot",
            "status": "found",
            "confidence": "medium",
            "raw_text": f"Статутний капітал: {format_uah(capital)}",
        }
    ]


def collect_financial_risk_flags(result: CompanyLookupResult) -> list[dict]:
    years = result.financial_data.years if result.financial_data else {}
    flags: list[dict] = []
    statutory_capital = company_statutory_capital_uah(result)
    low_authorized_capital_found = (
        statutory_capital is not None
        and statutory_capital <= LOW_AUTHORIZED_CAPITAL_THRESHOLD_UAH
    )
    financial_data_missing = (
        has_financial_profile_context(result)
        and not has_core_financial_values(years)
    )

    if low_authorized_capital_found:
        flags.append(
            public_financial_profile_flag(
                "low_authorized_capital_found",
                f"Статутний капітал: {format_uah(statutory_capital)}",
            )
        )
    if financial_data_missing:
        flags.append(
            public_financial_profile_flag(
                "financial_data_missing",
                "Дохід, прибуток, активи та зобов’язання у доступних джерелах не знайдено",
            )
        )
    if low_authorized_capital_found and financial_data_missing:
        flags.append(
            public_financial_profile_flag(
                "weak_public_financial_profile",
                "Низький статутний капітал і відсутні повні фінансові показники",
            )
        )

    if not years:
        return flags

    latest_year = max(years.keys(), key=sort_financial_year)
    latest_financial = years[latest_year]
    latest_equity = financial_year_equity_uah(latest_financial)
    latest_assets = latest_financial.assets_uah
    latest_liabilities = latest_financial.liabilities_uah
    latest_profit = latest_financial.net_profit_uah
    latest_revenue = latest_financial.revenue_uah
    equity_growth_found = financial_equity_growth_found(years)
    negative_equity_years = [
        year
        for year, financial_year in years.items()
        if (financial_year_equity_uah(financial_year) or 0) < 0
    ]

    if latest_equity is not None and latest_equity < 0:
        flags.append(financial_risk_flag("negative_equity_found", latest_year, f"Власний капітал: {format_uah(latest_equity)}"))

    if latest_liabilities is not None and latest_assets is not None and latest_liabilities > latest_assets:
        gap = latest_liabilities - latest_assets
        flags.append(
            financial_risk_flag(
                "liabilities_exceed_assets",
                latest_year,
                f"Зобов’язання перевищують активи на {format_uah(gap)}",
            )
        )

    if has_severe_negative_equity(latest_equity, latest_assets, latest_liabilities):
        flags.append(financial_risk_flag("severe_negative_equity", latest_year, "Суттєвий дефіцит власного капіталу"))

    if len(negative_equity_years) >= 2:
        flags.append(
            financial_risk_flag(
                "negative_equity_multiple_years",
                latest_year,
                f"Від’ємний власний капітал у роках: {', '.join(sorted(negative_equity_years, key=sort_financial_year))}",
            )
        )

    if latest_profit is not None and latest_profit < 0 and latest_equity is not None and latest_equity < 0:
        flags.append(
            financial_risk_flag(
                "losses_with_negative_equity",
                latest_year,
                f"Збиток: {format_uah(latest_profit)}; власний капітал: {format_uah(latest_equity)}",
            )
        )

    loss_flag_type = financial_loss_flag_type(
        latest_profit,
        latest_assets,
        latest_revenue,
        latest_equity,
        latest_liabilities,
    )
    if loss_flag_type:
        flags.append(financial_risk_flag(loss_flag_type, latest_year, f"Збиток: {format_uah(latest_profit)}"))

    if latest_profit is not None and latest_profit > 0:
        flags.append(financial_risk_flag("positive_profit_found", latest_year, f"Прибуток: {format_uah(latest_profit)}"))

    if latest_equity is not None and latest_equity > 0:
        flags.append(
            financial_risk_flag("positive_equity_found", latest_year, f"Власний капітал: {format_uah(latest_equity)}")
        )

    if equity_growth_found:
        flags.append(financial_risk_flag("equity_growth_found", latest_year, "Власний капітал зростає"))

    if latest_assets is not None and latest_liabilities is not None and latest_assets > latest_liabilities:
        gap = latest_assets - latest_liabilities
        flags.append(
            financial_risk_flag(
                "assets_exceed_liabilities",
                latest_year,
                f"Активи перевищують зобов’язання на {format_uah(gap)}",
            )
        )

    if latest_revenue is not None and latest_revenue >= 10_000_000:
        flags.append(financial_risk_flag("strong_revenue_found", latest_year, f"Дохід: {format_uah(latest_revenue)}"))

    has_healthy_financial_profile = (
        latest_profit is not None
        and latest_profit > 0
        and latest_equity is not None
        and latest_equity > 0
        and latest_assets is not None
        and latest_liabilities is not None
        and latest_assets > latest_liabilities
        and latest_revenue is not None
        and latest_revenue >= 10_000_000
    )
    if has_healthy_financial_profile:
        flags.append(financial_risk_flag("strong_financial_profile", latest_year, "Прибуток, позитивний капітал і здоровий баланс"))

    has_large_financial_scale = bool(
        (latest_revenue is not None and latest_revenue >= 1_000_000_000)
        or (latest_assets is not None and latest_assets >= 1_000_000_000)
    )
    if (
        has_healthy_financial_profile
        and has_large_financial_scale
        and (equity_growth_found or (result.risk_input.company_age_years or 0) >= 5)
    ):
        flags.append(financial_risk_flag("very_strong_financial_profile", latest_year, "Великий масштаб на фоні здорових фінансів"))

    strong_financial_flags = {
        flag["type"]
        for flag in flags
        if flag["type"]
        in {
            "negative_equity_found",
            "severe_negative_equity",
            "liabilities_exceed_assets",
            "negative_equity_multiple_years",
            "losses_with_negative_equity",
            "large_loss_found",
            "very_large_loss_found",
            "critical_loss_found",
        }
    }
    if len(strong_financial_flags) >= 2:
        flags.append(
            financial_risk_flag(
                "weak_financial_position",
                latest_year,
                f"Одночасно виявлено фінансові проблеми: {', '.join(sorted(strong_financial_flags))}",
            )
        )

    return flags


LOSS_FLAG_ORDER = [
    "small_loss_found",
    "medium_loss_found",
    "large_loss_found",
    "very_large_loss_found",
    "critical_loss_found",
]


def financial_loss_flag_type(
    profit_loss: int | None,
    assets: int | None,
    revenue: int | None,
    equity: int | None = None,
    liabilities: int | None = None,
) -> str | None:
    if profit_loss is None or profit_loss >= 0:
        return None
    loss_abs = abs(profit_loss)
    if loss_abs < 10_000:
        flag_type = "small_loss_found"
    elif loss_abs < 100_000:
        flag_type = "medium_loss_found"
    elif loss_abs < 1_000_000:
        flag_type = "large_loss_found"
    else:
        flag_type = "large_loss_found"

    if is_critical_loss(loss_abs, assets, revenue, equity, liabilities):
        flag_type = "critical_loss_found"
    return flag_type


def is_critical_loss(
    loss_abs: int,
    assets: int | None,
    revenue: int | None,
    equity: int | None,
    liabilities: int | None,
) -> bool:
    if revenue is not None and revenue > 0 and loss_abs > revenue:
        return True
    if assets is not None and assets > 0 and loss_abs / assets >= 0.10:
        return True
    if loss_abs >= 10_000_000 and equity is not None and equity < 0:
        return True
    if (
        loss_abs >= 10_000_000
        and assets is not None
        and liabilities is not None
        and liabilities > assets
    ):
        return True
    return False


def loss_ratio_values(loss_abs: int, assets: int | None, revenue: int | None) -> list[float]:
    ratios: list[float] = []
    if assets is not None and assets > 0:
        ratios.append(loss_abs / assets)
    if revenue is not None and revenue > 0:
        ratios.append(loss_abs / revenue)
    return ratios


def adjacent_loss_flag(flag_type: str, step: int) -> str:
    index = LOSS_FLAG_ORDER.index(flag_type)
    next_index = min(max(index + step, 0), len(LOSS_FLAG_ORDER) - 1)
    return LOSS_FLAG_ORDER[next_index]


def company_statutory_capital_uah(result: CompanyLookupResult) -> int | None:
    if result.risk_input.statutory_capital_uah is not None:
        return result.risk_input.statutory_capital_uah
    if result.company_data and result.company_data.statutory_capital_uah is not None:
        return result.company_data.statutory_capital_uah
    return None


def has_financial_profile_context(result: CompanyLookupResult) -> bool:
    if result.risk_input.has_financial_history:
        return True
    return company_statutory_capital_uah(result) is not None


def has_core_financial_values(years: dict[str, FinancialYearData]) -> bool:
    for financial_year in years.values():
        if any(
            value is not None
            for value in (
                financial_year.revenue_uah,
                financial_year.net_profit_uah,
                financial_year.assets_uah,
                financial_year.liabilities_uah,
                financial_year.equity_uah,
            )
        ):
            return True
    return False


def public_financial_profile_flag(flag_type: str, raw_text: str) -> dict:
    return {
        "type": flag_type,
        "source": "financials",
        "status": "found",
        "confidence": "medium",
        "raw_text": raw_text,
        "matched_pattern": flag_type,
        "match_type": "public_financial_profile",
    }


def has_severe_negative_equity(
    equity: int | None,
    assets: int | None,
    liabilities: int | None,
) -> bool:
    severity_floor = 1_000_000
    if equity is not None and equity < 0:
        asset_based_threshold = int((assets or 0) * 0.25)
        if abs(equity) >= max(severity_floor, asset_based_threshold):
            return True

    if assets is None or liabilities is None or liabilities <= assets:
        return False
    liabilities_gap = liabilities - assets
    asset_based_threshold = int(assets * 0.25)
    return liabilities_gap >= max(severity_floor, asset_based_threshold)


def financial_equity_growth_found(years: dict[str, FinancialYearData]) -> bool:
    equity_points = [
        (year, financial_year_equity_uah(financial_year))
        for year, financial_year in years.items()
    ]
    equity_points = [
        (year, equity)
        for year, equity in equity_points
        if equity is not None
    ]
    if len(equity_points) < 2:
        return False
    ordered_points = sorted(equity_points, key=lambda item: sort_financial_year(item[0]))
    first_equity = ordered_points[0][1]
    latest_equity = ordered_points[-1][1]
    return latest_equity > first_equity


def financial_risk_flag(flag_type: str, year: str, raw_text: str) -> dict:
    return {
        "type": flag_type,
        "source": "financials",
        "status": "found",
        "confidence": "medium",
        "raw_text": f"{year}: {raw_text}",
        "matched_pattern": flag_type,
        "match_type": "financial_statement",
    }


def is_debt_related_flag(flag: dict) -> bool:
    return canonical_risk_type(str(flag.get("type") or "")) in {
        "tax_debt_found",
        "large_tax_debt_found",
        "tax_debt_enforcement_found",
        "salary_debt_enforcement_found",
        "debt_collection_found",
        "debtor_registry_found",
        "multiple_debtor_records",
        "enforcement_found",
    }


def canonical_risk_type(flag_type: str) -> str:
    return RISK_FLAG_ALIASES.get(flag_type, flag_type)


def collect_company_status_risk_flags(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None,
) -> list[dict]:
    flags: list[dict] = []
    statuses = collect_company_statuses(result, clarity_data, youcontrol_data)
    has_status_conflict = has_company_status_conflict(statuses)
    for source, status in statuses:
        lowered = normalize_compare_value(status) or ""
        if is_safe_negative_status(lowered):
            continue
        if "банкрут" in lowered or "bankrupt" in lowered:
            flags.append(status_risk_flag("bankruptcy_found", source, status, "банкрут"))
        elif is_company_termination_status(status) and not has_status_conflict:
            flags.append(status_risk_flag("company_in_termination", source, status, "припин"))
        elif any(marker in lowered for marker in ("ліквід", "неактив", "анульован", "liquid")):
            flags.append(status_risk_flag("company_inactive", source, status, "ліквід/неактив/анульован"))
    return flags


def status_risk_flag(flag_type: str, source: str, raw_text: str, matched_pattern: str) -> dict:
    return {
        "type": flag_type,
        "source": source,
        "status": "found",
        "confidence": "high",
        "raw_text": raw_text,
        "matched_pattern": matched_pattern,
        "match_type": "positive_match",
    }


def youcontrol_flag_confidence(code: str) -> str:
    return "high" if code in {"company_not_found", "company_inactive", "company_in_termination", "bankruptcy_found"} else "medium"


def youcontrol_risk_evidence(code: str, youcontrol_data: dict) -> dict:
    company = youcontrol_data.get("company") or {}
    status_text = str(company.get("status") or "")
    signals = [str(signal) for signal in youcontrol_data.get("signals") or []]
    raw_excerpt = str(youcontrol_data.get("raw_text_excerpt") or "")
    evidence_by_code = {
        "company_inactive": (status_text or raw_excerpt, "ліквід/неактив/анульован"),
        "company_in_termination": (status_text or raw_excerpt, "припин"),
        "bankruptcy_found": (find_signal(signals, "банкрут") or raw_excerpt, "банкрут"),
        "tax_debt_found": (find_signal(signals, "податковий борг") or raw_excerpt, "податковий борг"),
        "court_cases_found": (find_signal(signals, "судові справи") or raw_excerpt, "судові справи"),
        "enforcement_found": (find_signal(signals, "виконавчі провадження") or raw_excerpt, "виконавчі провадження"),
        "suspicious_status": (find_signal(signals, "ризикові попередження") or status_text or raw_excerpt, "ризикові попередження"),
        "data_mismatch_between_sources": (find_signal(signals, "дані youcontrol") or raw_excerpt, "data_mismatch_between_sources"),
        "company_not_found": (youcontrol_data.get("error") or raw_excerpt, "company_not_found"),
    }
    raw_text, matched_pattern = evidence_by_code.get(code, (raw_excerpt, code))
    return {
        "raw_text": raw_text or None,
        "matched_pattern": matched_pattern,
        "match_type": "positive_match",
    }


def find_signal(signals: list[str], marker: str) -> str | None:
    marker = marker.lower()
    for signal in signals:
        if marker in signal.lower():
            return signal
    return None


def collect_youcontrol_not_found_evidence(youcontrol_data: dict, found_types: set[str] | None = None) -> list[dict]:
    evidence: list[dict] = []
    found_types = found_types or set()
    signal_mapping = {
        "банкрутство: не вияв": "bankruptcy_found",
        "банкрутство: відсут": "bankruptcy_found",
        "податковий борг: відсут": "tax_debt_found",
        "податковий борг: не вияв": "tax_debt_found",
        "виконавчі провадження: 0": "enforcement_found",
        "виконавчі провадження: відсут": "enforcement_found",
        "виконавчі провадження: не вияв": "enforcement_found",
    }
    for signal in youcontrol_data.get("signals") or []:
        lowered = str(signal).lower()
        for marker, flag_type in signal_mapping.items():
            if marker in lowered and flag_type not in found_types:
                evidence.append(
                    {
                        "type": flag_type,
                        "source": "youcontrol",
                        "status": "not_found",
                        "confidence": "medium",
                        "raw_text": signal,
                        "matched_pattern": marker,
                        "match_type": "safe_phrase",
                    }
                )
                break
    return evidence


def collect_company_status_mismatch_flags(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None,
) -> list[dict]:
    statuses = collect_company_statuses(result, clarity_data, youcontrol_data)
    if not has_company_status_conflict(statuses):
        return []
    return [
        {"type": "company_status_mismatch", "source": source}
        for source in dict.fromkeys(source for source, _ in statuses)
    ]


def has_company_status_conflict(statuses: list[tuple[str, str]]) -> bool:
    active_sources = [source for source, status in statuses if is_registered_status(status)]
    terminal_sources = [source for source, status in statuses if is_terminal_status(status)]
    return bool(active_sources and terminal_sources)


def collect_company_statuses(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None,
) -> list[tuple[str, str]]:
    statuses: list[tuple[str, str]] = []
    if result.company_data and result.company_data.status:
        statuses.append(("opendatabot", result.company_data.status))
    if clarity_data and clarity_data.company and clarity_data.company.status:
        statuses.append((clarity_data.source, clarity_data.company.status))
    youcontrol_company = (youcontrol_data or {}).get("company") or {}
    if youcontrol_company.get("status"):
        statuses.append(("youcontrol", str(youcontrol_company["status"])))
    return statuses


def is_registered_status(status: str) -> bool:
    lowered = normalize_compare_value(status) or ""
    return "зареєстр" in lowered and not is_terminal_status(lowered)


def is_terminal_status(status: str) -> bool:
    lowered = normalize_compare_value(status) or ""
    if is_safe_negative_status(lowered):
        return False
    if is_company_termination_status(lowered):
        return True
    return any(
        marker in lowered
        for marker in (
            "ліквід",
            "банкрут",
            "неактив",
            "анульован",
            "terminated",
            "liquid",
            "bankrupt",
        )
    )


def is_company_termination_status(status: str) -> bool:
    lowered = normalize_compare_value(status) or ""
    if is_safe_negative_status(lowered):
        return False
    normalized = lowered.strip(" .:;")
    for prefix in ("статус:", "стан:", "актуальний статус:", "статус "):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix).strip(" .:;")
    return normalized in {
        "в стані припинення",
        "у стані припинення",
        "припиняється",
        "припинено",
        "terminated",
    }


def is_safe_negative_status(status: str) -> bool:
    lowered = normalize_compare_value(status) or ""
    return any(
        pattern in lowered
        for pattern in (
            "не перебуває в процесі припинення",
            "не перебуває у процесі припинення",
            "не перебуває в стані припинення",
            "не перебуває у стані припинення",
            "відомості про припинення відсутні",
            "припинення відсут",
            "банкрутство не виявлено",
            "банкрутство відсут",
            "статус: зареєстровано",
            "статус зареєстровано",
            "не анульовано",
            "не анульована",
            "анульовані записи відсут",
            "анульованих записів відсут",
        )
    )


def collect_opendatabot_risk_flags(result: CompanyLookupResult) -> list[dict]:
    flags: list[dict] = []
    if result.status == NOT_FOUND:
        flags.append({"type": "company_not_found", "source": "opendatabot"})
    if result.status == SOURCE_ERROR:
        flags.append({"type": "source_unavailable", "source": "opendatabot"})

    company = result.company_data
    status = (company.status if company else "") or ""
    lowered_status = status.lower()
    if not is_safe_negative_status(lowered_status) and ("ліквід" in lowered_status or "анульован" in lowered_status):
        flags.append(status_risk_flag("company_inactive", "opendatabot", status, "ліквід/анульован"))

    if result.risk_input.company_age_years is not None and result.risk_input.company_age_years < 3:
        flags.append({"type": "young_company", "source": "opendatabot"})
    if result.risk_input.has_court_mentions or result.court_data.has_court_mentions:
        flags.append({"type": "court_cases_found", "source": "opendatabot"})
    court_mentions_count = get_court_mentions_count(result)
    if 5 <= court_mentions_count < 20:
        flags.append(
            {
                "type": "several_court_mentions_found",
                "source": "opendatabot",
                "status": "found",
                "confidence": "low",
                "raw_text": f"Судові згадки: {court_mentions_count}",
            }
        )
    if court_mentions_count >= 20:
        flags.append(
            {
                "type": "many_court_mentions_found",
                "source": "opendatabot",
                "status": "found",
                "confidence": "low",
                "raw_text": f"Судові згадки: {court_mentions_count}",
            }
        )
    if court_mentions_count > 10_000:
        flags.append(
            {
                "type": "very_many_court_mentions_found",
                "source": "opendatabot",
                "status": "found",
                "confidence": "low",
                "raw_text": f"Судові згадки: {court_mentions_count}",
            }
        )
    if result.risk_input.tax_debt_found:
        flags.append(
            {
                "type": "tax_debt_found",
                "source": "opendatabot",
                "status": "found",
                "confidence": "medium",
                "raw_text": result.risk_input.tax_debt_text,
                "matched_pattern": "ДПС/податковий борг/стягнення",
                "match_type": "positive_match",
            }
        )
    for flag in result.court_data.risk_flags:
        flags.append({"type": flag, "source": "opendatabot"})
    flags.extend(collect_court_decision_risk_flags(result))
    return flags


def collect_court_decision_risk_flags(result: CompanyLookupResult) -> list[dict]:
    flags: list[dict] = []
    for decision in result.court_data.decisions:
        subject = str(decision.get("claim_subject") or "").lower()
        summary = str(decision.get("risk_summary") or "").lower()
        if decision.get("negative_outcome_detected") or decision.get("liability_detected"):
            if any(marker in subject or marker in summary for marker in ("стяг", "заборг", "пен", "санкц")):
                flags.append({"type": "debt_collection_case", "source": "court_analysis"})
        if decision.get("company_role") == "defendant" and any(marker in subject for marker in ("стяг", "заборг", "пен", "санкц")):
            flags.append({"type": "debt_collection_case", "source": "court_analysis"})
        if "догов" in subject or "догов" in summary:
            flags.append({"type": "contract_nonperformance_case", "source": "court_analysis"})
        if "кримін" in subject or "кримін" in summary:
            flags.append({"type": "criminal_case_found", "source": "court_analysis"})
    return flags


def extract_website_from_sources(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None,
) -> str | None:
    company = result.company_data
    candidates: list[object] = []
    if company:
        candidates.extend(
            [
                getattr(company, "website", None),
                *(getattr(company, "websites", []) or []),
            ]
        )
    clarity_company = clarity_data.company if clarity_data and clarity_data.company else None
    if clarity_company:
        candidates.append(getattr(clarity_company, "website", None))
    youcontrol_company = (youcontrol_data or {}).get("company") or {}
    for key in ("website", "domain", "site", "web_site", "homepage"):
        candidates.append(youcontrol_company.get(key))
    for candidate in candidates:
        normalized = normalize_url(str(candidate)) if candidate else None
        if normalized:
            return normalized
    return None


def build_domain_company_context(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None,
    website_url: str | None = None,
) -> dict:
    company = result.company_data
    clarity_company = clarity_data.company if clarity_data and clarity_data.company else None
    youcontrol_company = (youcontrol_data or {}).get("company") or {}
    company_name = (
        (company.short_name if company else None)
        or (company.full_name if company else None)
        or (clarity_company.name if clarity_company else None)
        or youcontrol_company.get("name")
    )
    address = (company.address if company else None) or youcontrol_company.get("address")
    director = (company.director if company else None) or youcontrol_company.get("director")
    phones = list(getattr(company, "phones", []) or []) if company else []
    emails = list(getattr(company, "emails", []) or []) if company else []
    known_domains = [website_url] if website_url else []
    return {
        "edrpou": result.edrpou,
        "company_name": company_name,
        "address": address,
        "director": director,
        "phones": phones,
        "emails": emails,
        "known_domains": known_domains,
    }


def prepare_youcontrol_data(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None,
) -> dict | None:
    if youcontrol_data is None:
        return None
    prepared = {
        **youcontrol_data,
        "company": dict(youcontrol_data.get("company") or {}),
        "signals": list(youcontrol_data.get("signals") or []),
        "risk_flags": list(youcontrol_data.get("risk_flags") or []),
    }
    if youcontrol_data_mismatch_detected(result, clarity_data, prepared):
        if "data_mismatch_between_sources" not in prepared["risk_flags"]:
            prepared["risk_flags"].append("data_mismatch_between_sources")
        if "Дані YouControl відрізняються від іншого джерела" not in prepared["signals"]:
            prepared["signals"].append("Дані YouControl відрізняються від іншого джерела")
    return prepared


def youcontrol_data_mismatch_detected(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict,
) -> bool:
    if not youcontrol_data.get("found"):
        return False
    company = youcontrol_data.get("company") or {}
    youcontrol_edrpou = company.get("edrpou")
    if youcontrol_edrpou and youcontrol_edrpou != result.edrpou:
        return True
    if result.company_data and result.company_data.edrpou and youcontrol_edrpou:
        if result.company_data.edrpou != youcontrol_edrpou:
            return True

    youcontrol_status = normalize_compare_value(company.get("status"))
    opendatabot_status = normalize_compare_value(result.company_data.status if result.company_data else None)
    clarity_status = normalize_compare_value(clarity_data.company.status if clarity_data and clarity_data.company else None)
    return bool(
        youcontrol_status
        and (
            opendatabot_status
            and youcontrol_status != opendatabot_status
            or clarity_status
            and youcontrol_status != clarity_status
        )
    )


def normalize_compare_value(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.lower().split())


def build_sources_snapshot(
    result: CompanyLookupResult,
    clarity_data: ClarityData | None,
    youcontrol_data: dict | None,
    debtors_registry_data: dict | None = None,
    tax_data: dict | None = None,
    domain_reputation_data: dict | None = None,
    contacts_summary: dict | None = None,
) -> dict:
    sources: dict[str, object] = {
        "opendatabot": {
            "status": result.status,
            "url": result.source_url,
            "company": result.company_data.model_dump(mode="json") if result.company_data else None,
        }
    }
    if clarity_data:
        sources["clarity"] = clarity_data.model_dump(mode="json")
    else:
        sources["clarity"] = None
    sources["youcontrol"] = youcontrol_data
    sources["debtors_registry"] = debtors_registry_data
    sources["tax"] = tax_data
    sources["domain_reputation"] = domain_reputation_data
    sources["prozorro"] = result.prozorro_analysis.model_dump(mode="json") if result.prozorro_analysis else None
    sources["prozorro_sale"] = (
        result.prozorro_sale_analysis.model_dump(mode="json") if result.prozorro_sale_analysis else None
    )
    sources["contacts_summary"] = contacts_summary
    sources["contact_sources"] = (contacts_summary or {}).get("source_results") if contacts_summary else None
    sources["court_analysis"] = {
        "has_court_mentions": result.court_data.has_court_mentions,
        "court_mentions_count": result.court_data.court_mentions_count or result.court_data.total_cases_found,
        "court_unique_cases_count": result.court_data.court_unique_cases_count,
        "court_risky_cases_count": result.court_data.court_risky_cases_count,
        "total_cases_found": result.court_data.total_cases_found,
        "decisions": result.court_data.decisions,
        "risk_flags": result.court_data.risk_flags,
    }
    return sources


def is_successful_youcontrol(youcontrol_data: dict | None) -> bool:
    return bool(youcontrol_data and youcontrol_data.get("found"))


def is_successful_debtors_registry(debtors_registry_data: dict | None) -> bool:
    return bool(debtors_registry_data and debtors_registry_data.get("checked") and debtors_registry_data.get("found"))


def is_successful_tax(tax_data: dict | None) -> bool:
    return bool(tax_data and tax_data.get("checked") and tax_data.get("found"))


def is_checked_domain_reputation(domain_reputation_data: dict | None) -> bool:
    return bool(domain_reputation_data and domain_reputation_data.get("checked"))


def is_useful_domain_reputation_source(domain_reputation_data: dict | None) -> bool:
    return bool(
        domain_reputation_data
        and domain_reputation_data.get("checked")
        and domain_reputation_data.get("found")
        and is_displayable_contact_value("website", domain_reputation_data.get("url") or domain_reputation_data.get("domain"))
    )


def should_store_youcontrol_diagnostic(youcontrol_data: dict) -> bool:
    return bool(youcontrol_data.get("error") or not youcontrol_data.get("found"))


def youcontrol_status(youcontrol_data: dict) -> str:
    if youcontrol_data.get("found"):
        return "found"
    if youcontrol_data.get("error") == "company_not_found":
        return "not_found"
    return "source_error"


def should_store_debtors_diagnostic(debtors_registry_data: dict) -> bool:
    return bool(debtors_registry_data.get("error") or debtors_registry_data.get("checked") is False)


def debtors_status(debtors_registry_data: dict) -> str:
    if debtors_registry_data.get("found"):
        return "found"
    if debtors_registry_data.get("checked"):
        return "not_found"
    return "source_error"


def should_store_tax_diagnostic(tax_data: dict) -> bool:
    return bool(tax_data.get("error") or tax_data.get("checked") is False)


def tax_status(tax_data: dict) -> str:
    if tax_data.get("found"):
        return "found"
    if tax_data.get("checked"):
        return "not_found"
    return "source_error"


def should_store_domain_reputation_diagnostic(domain_reputation_data: dict) -> bool:
    return bool(
        domain_reputation_data.get("error")
        and domain_reputation_data.get("error") != "website_not_provided"
    )


def domain_reputation_status(domain_reputation_data: dict) -> str:
    if domain_reputation_data.get("found"):
        return "found"
    if domain_reputation_data.get("checked"):
        return "not_found"
    return "source_error"


def highest_risk_level(levels: list[str]) -> str:
    priority = {"low": 0, "info": 1, "medium": 2, "high": 3}
    if not levels:
        return "low"
    return max(levels, key=lambda level: priority.get(level, 0))


def clarity_source_error_result(edrpou: str, error: str) -> ClarityData:
    return ClarityData(
        source_url=f"https://clarity-project.info/edr/{edrpou}",
        status=CLARITY_SOURCE_ERROR,
        edrpou=edrpou,
        error=error,
    )


def youcontrol_source_error_result(edrpou: str, error: str) -> dict:
    return {
        "source": "youcontrol",
        "found": False,
        "url": f"https://youcontrol.com.ua/catalog/company_details/{edrpou}/",
        "company": {
            "name": None,
            "edrpou": edrpou,
            "status": None,
            "registration_date": None,
            "address": None,
            "director": None,
            "main_kved": None,
            "additional_kveds": [],
        },
        "signals": [],
        "risk_flags": [],
        "raw_text_excerpt": None,
        "error": error,
    }


def debtors_source_error_result(edrpou: str, error: str) -> dict:
    return {
        "source": "debtors_registry",
        "checked": False,
        "found": False,
        "url": "https://erb.minjust.gov.ua/#/search-debtors",
        "searched_edrpou": edrpou,
        "items_count": 0,
        "unique_categories": [],
        "proceeding_numbers": [],
        "items": [],
        "signals": [],
        "risk_flags": ["source_unavailable"],
        "error": error,
    }


def tax_source_error_result(edrpou: str, error: str) -> dict:
    return {
        "source": "tax",
        "checked": False,
        "found": False,
        "url": "https://data.gov.ua/dataset/0e347d45-4db5-44ee-a14a-533d7cf17d7b",
        "vat_url": "https://data.gov.ua/dataset/db391c93-1e68-43c9-bd85-7c6a8427b114",
        "searched_edrpou": edrpou,
        "tax_debt": None,
        "vat": None,
        "signals": [],
        "risk_flags": ["tax_source_unavailable"],
        "error": error,
    }


def domain_reputation_source_error_result(website_url: str | None, error: str) -> dict:
    return {
        "source": "domain_reputation",
        "checked": bool(website_url),
        "found": False,
        "url": website_url,
        "domain": None,
        "http": {"status_code": None, "final_url": None, "redirects": []} if website_url else None,
        "ssl": None,
        "dns": None,
        "contacts": None,
        "signals": [],
        "risk_flags": ["website_source_unavailable"] if website_url else [],
        "error": "website_source_unavailable" if website_url else "website_not_provided",
    }


def contacts_source_error_result(edrpou: str, error: str) -> dict:
    return {
        "website": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
        "phone": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
        "email": {"value": None, "confidence": "unknown", "sources": [], "evidence": []},
        "checked_sources": ["ua-region.com.ua", "prat.ua/pat.ua", "smida.gov.ua", "business-guide.com.ua"],
        "missing_sources": [],
        "warnings": [f"Контактні джерела для ЄДРПОУ {edrpou} не вдалося перевірити автоматично: {error}."],
        "source_statuses": {
            "ua-region.com.ua": "unavailable",
            "prat.ua/pat.ua": "unavailable",
            "smida.gov.ua": "unavailable",
            "business-guide.com.ua": "unavailable",
        },
        "source_results": [],
    }


async def start_handler(message: Message) -> None:
    await message.answer(START_TEXT, reply_markup=build_main_keyboard())


async def help_handler(message: Message) -> None:
    await message.answer(HELP_TEXT)


async def check_handler(message: Message) -> None:
    await message.answer("Надішліть код ЄДРПОУ у форматі 8 цифр, наприклад: 12345678")


async def example_handler(message: Message) -> None:
    await message.answer(EXAMPLE_TEXT)


async def about_handler(message: Message) -> None:
    await message.answer(ABOUT_TEXT)


async def info_handler(message: Message) -> None:
    await message.answer(INFO_TEXT)


async def stop_handler(message: Message) -> None:
    await message.answer(STOP_TEXT, reply_markup=ReplyKeyboardRemove())


async def debug_handler(
    message: Message,
    lookup: Callable[[str], CompanyLookupResult] = lookup_company,
    clarity_lookup: Callable[[str], ClarityData] = lookup_clarity_by_edrpou,
    youcontrol_lookup: Callable[[str], dict] = fetch_youcontrol_company,
    debtors_lookup: Callable[[str], dict | None] = fetch_debtors_registry,
    tax_lookup: Callable[[str], dict | None] = fetch_tax_status,
    domain_reputation_lookup: Callable[[str | None, dict | None], dict | None] = fetch_domain_reputation,
    contacts_lookup: Callable[[str, dict | None], dict | None] = fetch_company_contacts_async,
    analysis_timeout: float = ANALYSIS_TIMEOUT_SECONDS,
    prozorro_lookup: Callable[[str], ProzorroAnalysis] = lookup_prepared_prozorro,
    prozorro_sale_lookup: Callable[[str], ProzorroSaleAnalysis] = lookup_prozorro_sale_by_edrpou,
) -> None:
    edrpou = extract_debug_edrpou(message.text or "")
    if not edrpou:
        await message.answer(INVALID_EDRPOU_TEXT)
        return

    result, clarity_data, youcontrol_data, debtors_registry_data, tax_data, domain_reputation_data, contacts_summary = await run_source_lookups(
        edrpou,
        lookup,
        clarity_lookup,
        youcontrol_lookup,
        debtors_lookup,
        tax_lookup,
        domain_reputation_lookup,
        contacts_lookup,
        website_url=None,
        analysis_timeout=analysis_timeout,
        prozorro_lookup=prozorro_lookup,
        prozorro_sale_lookup=prozorro_sale_lookup,
    )
    enriched = with_source_diagnostics(
        result,
        clarity_data,
        youcontrol_data,
        debtors_registry_data,
        tax_data,
        domain_reputation_data,
        contacts_summary,
    )
    await message.answer(json.dumps(build_debug_payload(enriched), ensure_ascii=False, indent=2))


def extract_debug_edrpou(text: str) -> str | None:
    parts = text.split()
    if len(parts) < 2:
        return None
    edrpou = parts[1].strip()
    return edrpou if is_valid_edrpou(edrpou) else None


def parse_edrpou_query(text: str) -> tuple[str | None, str | None]:
    parts = (text or "").split()
    if not parts or len(parts) > 2 or not is_valid_edrpou(parts[0].strip()):
        return None, None
    website_url = None
    if len(parts) > 1:
        website_url = normalize_url(parts[1])
        if not is_plausible_website_url(website_url):
            return None, None
    return parts[0].strip(), website_url


def is_plausible_website_url(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url).hostname or ""
    return "." in host and not host.startswith(".") and not host.endswith(".")


def build_debug_payload(result: CompanyLookupResult) -> dict:
    sources = result.sources or {}
    return {
        "edrpou": result.edrpou,
        "sources_checked": checked_sources(sources),
        "sources_unavailable": unavailable_sources(sources),
        "raw_counts": raw_debug_counts(sources),
        "contact_sources_debug": (sources.get("contacts_summary") or {}).get("source_debug", []),
        "risk_flags": result.risk_summary.reasons,
        "final_score": result.risk_summary.score,
        "final_level": result.risk_summary.level,
        "final_label_uk": result.risk_summary.label_uk,
    }


def raw_debug_counts(sources: dict) -> dict:
    court_analysis = sources.get("court_analysis") or {}
    clarity = sources.get("clarity") or {}
    clarity_signals = clarity.get("signals") or {}
    court_mentions_count = court_analysis.get("court_mentions_count")
    if court_mentions_count is None:
        court_mentions_count = court_analysis.get("total_cases_found")
    return {
        "court_mentions_count": court_mentions_count,
        "court_cases_count": court_mentions_count,
        "court_unique_cases_count": court_analysis.get("court_unique_cases_count"),
        "court_risky_cases_count": court_analysis.get("court_risky_cases_count"),
        "enforcement_count": clarity_signals.get("enforcement_proceedings_count"),
    }


def checked_sources(sources: dict) -> list[str]:
    checked: list[str] = []
    if sources.get("opendatabot"):
        checked.append("opendatabot")
    if sources.get("clarity"):
        checked.append("clarity")
    if sources.get("youcontrol"):
        checked.append("youcontrol")
    if sources.get("debtors_registry"):
        checked.append("debtors_registry")
    if sources.get("tax"):
        checked.append("tax")
    domain_reputation = sources.get("domain_reputation") or {}
    if domain_reputation and domain_reputation.get("checked"):
        checked.append("domain_reputation")
    prozorro = sources.get("prozorro") or {}
    if prozorro and prozorro.get("status") in {"found", "partial"}:
        checked.append("prozorro")
    prozorro_sale = sources.get("prozorro_sale") or {}
    if prozorro_sale and prozorro_sale.get("status") == "found":
        checked.append("prozorro_sale")
    if sources.get("contacts_summary"):
        checked.append("contacts_summary")
    if sources.get("court_analysis"):
        checked.append("court_analysis")
    return checked


def unavailable_sources(sources: dict) -> list[str]:
    unavailable: list[str] = []
    opendatabot = sources.get("opendatabot") or {}
    if opendatabot.get("status") in {SOURCE_ERROR, PARSE_ERROR}:
        unavailable.append("opendatabot")
    clarity = sources.get("clarity") or {}
    if clarity and clarity.get("status") in {CLARITY_SOURCE_ERROR, CLARITY_PARSE_ERROR}:
        unavailable.append("clarity")
    youcontrol = sources.get("youcontrol") or {}
    if youcontrol and youcontrol.get("error"):
        unavailable.append("youcontrol")
    debtors_registry = sources.get("debtors_registry") or {}
    if debtors_registry and debtors_registry.get("error"):
        unavailable.append("debtors_registry")
    tax = sources.get("tax") or {}
    if tax and tax.get("error"):
        unavailable.append("tax")
    domain_reputation = sources.get("domain_reputation") or {}
    if domain_reputation and domain_reputation.get("error") == "website_source_unavailable":
        unavailable.append("domain_reputation")
    prozorro = sources.get("prozorro") or {}
    if prozorro and prozorro.get("status") == "source_error":
        unavailable.append("prozorro")
    prozorro_sale = sources.get("prozorro_sale") or {}
    if prozorro_sale and prozorro_sale.get("status") == "source_error":
        unavailable.append("prozorro_sale")
    return unavailable


async def edrpou_handler(
    message: Message,
    lookup: Callable[[str], CompanyLookupResult] = lookup_company,
    clarity_lookup: Callable[[str], ClarityData] = lookup_clarity_by_edrpou,
    youcontrol_lookup: Callable[[str], dict] = fetch_youcontrol_company,
    debtors_lookup: Callable[[str], dict | None] = fetch_debtors_registry,
    tax_lookup: Callable[[str], dict | None] = fetch_tax_status,
    domain_reputation_lookup: Callable[[str | None, dict | None], dict | None] = fetch_domain_reputation,
    contacts_lookup: Callable[[str, dict | None], dict | None] = fetch_company_contacts_async,
    save: Callable[[CompanyLookupResult, int | None], object] = save_check_result,
    analysis_timeout: float = ANALYSIS_TIMEOUT_SECONDS,
    prozorro_lookup: Callable[[str], ProzorroAnalysis] = lookup_prepared_prozorro,
    prozorro_sale_lookup: Callable[[str], ProzorroSaleAnalysis] = lookup_prozorro_sale_by_edrpou,
) -> None:
    text = message.text or ""
    edrpou, website_url = parse_edrpou_query(text)
    if not edrpou:
        await message.answer(INVALID_EDRPOU_TEXT)
        return

    await message.answer(EDRPOU_SEARCH_TEXT)
    result, clarity_data, youcontrol_data, debtors_registry_data, tax_data, domain_reputation_data, contacts_summary = await run_source_lookups(
        edrpou,
        lookup,
        clarity_lookup,
        youcontrol_lookup,
        debtors_lookup,
        tax_lookup,
        domain_reputation_lookup,
        contacts_lookup,
        website_url=website_url,
        analysis_timeout=analysis_timeout,
        prozorro_lookup=prozorro_lookup,
        prozorro_sale_lookup=prozorro_sale_lookup,
    )
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    try:
        await asyncio.to_thread(
            save,
            with_source_diagnostics(
                result,
                clarity_data,
                youcontrol_data,
                debtors_registry_data,
                tax_data,
                domain_reputation_data,
                contacts_summary,
            ),
            user_id,
        )
    except OSError:
        logging.exception("Could not save check result for EDRPOU %s", text)
    await message.answer(
        build_edrpou_response(
            edrpou,
            result,
            clarity_data,
            youcontrol_data,
            debtors_registry_data,
            tax_data,
            domain_reputation_data,
            contacts_summary,
        )
    )


async def fallback_handler(message: Message) -> None:
    await message.answer(INVALID_EDRPOU_TEXT)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.message.register(start_handler, CommandStart())
    dispatcher.message.register(help_handler, Command("help"))
    dispatcher.message.register(check_handler, Command("check"))
    dispatcher.message.register(stop_handler, Command("stop"))
    dispatcher.message.register(info_handler, Command("info"))
    dispatcher.message.register(debug_handler, Command("debug"))
    dispatcher.message.register(stop_handler, F.text == STOP_BUTTON_TEXT)
    dispatcher.message.register(info_handler, F.text == INFO_BUTTON_TEXT)
    dispatcher.message.register(example_handler, Command("example"))
    dispatcher.message.register(about_handler, Command("about"))
    dispatcher.message.register(edrpou_handler, F.text)
    dispatcher.message.register(fallback_handler)
    return dispatcher


async def run_bot() -> None:
    settings = load_settings()
    logging.basicConfig(level=logging.INFO)
    configure_diagnostic_logging()
    log_diagnostic_event("bot_start", route="run_bot", app_env=settings.app_env)

    bot = Bot(token=settings.bot_token)
    dispatcher = create_dispatcher()
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
