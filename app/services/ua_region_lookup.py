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


SOURCE = "ua-region.com.ua"
BASE_URL = "https://www.ua-region.com.ua/{edrpou}"


def fetch_ua_region_company(
    edrpou: str,
    context: dict | None = None,
    *,
    fetcher: Callable[[str], str] = fetch_url,
    searcher: Callable[[str], list[str]] | None = None,
) -> dict:
    if not is_valid_edrpou(edrpou):
        return empty_result(SOURCE, status="parse_error", error="invalid_edrpou")

    direct_url = BASE_URL.format(edrpou=edrpou)
    result = fetch_ua_region_url(edrpou, direct_url, context or {}, fetcher)
    if result["status"] != "not_found":
        return result

    if searcher is None:
        return result
    for url in searcher(f'"{edrpou}" site:ua-region.com.ua')[:5]:
        fallback = fetch_ua_region_url(edrpou, url, context or {}, fetcher)
        if fallback["status"] == "found":
            return fallback
    return result


def fetch_ua_region_url(edrpou: str, url: str, context: dict, fetcher: Callable[[str], str]) -> dict:
    try:
        html = fetcher(url)
    except Exception as exc:
        return source_error_result(SOURCE, url, exc)

    text = visible_text(html)
    if is_blocked_page(html, text):
        return empty_result(SOURCE, status="blocked", raw_url=url, error="blocked")
    if not text or not document_has_edrpou(html, edrpou):
        return empty_result(
            SOURCE,
            status="not_found",
            raw_url=url,
            error="not_found",
            evidence=[f"UA-REGION: за ЄДРПОУ {edrpou} профіль компанії не знайдено."],
        )
    return build_found_result(SOURCE, edrpou=edrpou, html=html, raw_url=url, context=context)
