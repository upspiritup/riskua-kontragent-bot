from __future__ import annotations

from typing import Callable

from app.services.contact_parsing import (
    build_found_result,
    document_has_edrpou,
    empty_result,
    fetch_url,
    is_blocked_page,
    source_error_result,
    visible_text,
)
from app.utils.validators import is_valid_edrpou


SOURCE = "smida.gov.ua"
FORBIDDEN_EMAIL_DOMAINS = {"smida.gov.ua"}


def fetch_smida_company(
    edrpou: str,
    context: dict | None = None,
    *,
    fetcher: Callable[[str], str] = fetch_url,
    searcher: Callable[[str], list[str]] | None = None,
) -> dict:
    if not is_valid_edrpou(edrpou):
        return empty_result(SOURCE, status="parse_error", error="invalid_edrpou")
    if searcher is None:
        return empty_result(
            SOURCE,
            status="not_found",
            error="not_found",
            evidence=[f"SMIDA: за ЄДРПОУ {edrpou} інформацію емітента не знайдено."],
        )

    queries = [
        f'"{edrpou}" site:smida.gov.ua',
        f'"{edrpou}" "Телефон" site:smida.gov.ua',
        f'"{edrpou}" "Адреса електронної пошти" site:smida.gov.ua',
        f'"{edrpou}" "e-mail" site:smida.gov.ua',
        f'"{edrpou}" "report.xml" site:smida.gov.ua',
    ]
    if context and context.get("company_name"):
        queries.insert(1, f'"{context["company_name"]}" site:smida.gov.ua')

    first_error: dict | None = None
    for query in queries:
        for url in searcher(query)[:5]:
            try:
                payload = fetcher(url)
            except Exception as exc:
                first_error = first_error or source_error_result(SOURCE, url, exc)
                continue
            result = parse_smida_document(payload, edrpou, context or {}, url)
            if result["status"] == "found":
                return result
    return first_error or empty_result(
        SOURCE,
        status="not_found",
        error="not_found",
        evidence=[f"SMIDA: за ЄДРПОУ {edrpou} інформацію емітента не знайдено."],
    )


def parse_smida_document(html_or_xml: str, edrpou: str, context: dict | None, raw_url: str) -> dict:
    text = visible_text(html_or_xml)
    if is_blocked_page(html_or_xml, text):
        return empty_result(SOURCE, status="blocked", raw_url=raw_url, error="blocked")
    if not text or not document_has_edrpou(html_or_xml, edrpou):
        return empty_result(
            SOURCE,
            status="not_found",
            raw_url=raw_url,
            error="not_found",
            evidence=[f"SMIDA: за ЄДРПОУ {edrpou} інформацію емітента не знайдено."],
        )

    return build_found_result(
        SOURCE,
        edrpou=edrpou,
        html=html_or_xml,
        raw_url=raw_url,
        context=context or {},
        forbidden_email_domains=FORBIDDEN_EMAIL_DOMAINS,
        ignore_footer=True,
        default_evidence=["SMIDA: знайдено інформацію/звітність емітента."],
    )
