from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

from app.services.contact_parsing import (
    build_found_result,
    empty_result,
    fetch_url,
    is_blocked_page,
    source_error_result,
    visible_text,
)
from app.utils.validators import is_valid_edrpou


SOURCE = "business-guide.com.ua"


def fetch_business_guide_company(
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
            evidence=[f"Business Guide: за ЄДРПОУ {edrpou} профіль компанії не знайдено."],
        )

    queries = [
        f'"{edrpou}" site:business-guide.com.ua',
        f'"{edrpou}" "телефон" site:business-guide.com.ua',
        f'"{edrpou}" "email" site:business-guide.com.ua',
        f'"{edrpou}" "ЄДРПОУ" site:business-guide.com.ua',
    ]
    if context and context.get("company_name"):
        queries.insert(1, f'"{context["company_name"]}" site:business-guide.com.ua')

    first_error: dict | None = None
    for query in queries:
        for url in searcher(query)[:5]:
            if not is_business_guide_url(url):
                continue
            try:
                html = fetcher(url)
            except Exception as exc:
                first_error = first_error or source_error_result(SOURCE, url, exc)
                continue
            result = parse_business_guide_profile(html, edrpou, context or {}, url)
            if result["status"] == "found":
                return result
    return first_error or empty_result(
        SOURCE,
        status="not_found",
        error="not_found",
        evidence=[f"Business Guide: за ЄДРПОУ {edrpou} профіль компанії не знайдено."],
    )


def is_business_guide_url(url: str) -> bool:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    return host == "business-guide.com.ua" or host.endswith(".business-guide.com.ua")


def parse_business_guide_profile(html: str, edrpou: str, context: dict | None, raw_url: str) -> dict:
    text = visible_text(html)
    if is_blocked_page(html, text):
        return empty_result(SOURCE, status="blocked", raw_url=raw_url, error="blocked")
    if not text:
        return empty_result(SOURCE, status="not_found", raw_url=raw_url, error="not_found")

    return build_found_result(
        SOURCE,
        edrpou=edrpou,
        html=html,
        raw_url=raw_url,
        context=context or {},
        default_evidence=["Business Guide: знайдено профіль компанії у бізнес-каталозі."],
    )
