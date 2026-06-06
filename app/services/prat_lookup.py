from __future__ import annotations

import re
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

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


SOURCE = "prat.ua/pat.ua"
REGISTRY_URLS = (
    "https://prat.ua/reestr.php?edrpou={edrpou}",
    "https://pat.ua/reestr.php?edrpou={edrpou}",
)


def fetch_prat_company(
    edrpou: str,
    context: dict | None = None,
    *,
    fetcher: Callable[[str], str] = fetch_url,
    searcher: Callable[[str], list[str]] | None = None,
) -> dict:
    if not is_valid_edrpou(edrpou):
        return empty_result(SOURCE, status="parse_error", error="invalid_edrpou")

    context = context or {}
    first_not_found: dict | None = None
    for registry_url in REGISTRY_URLS:
        url = registry_url.format(edrpou=edrpou)
        result = fetch_prat_registry_url(edrpou, url, context, fetcher)
        if result["status"] == "found":
            return result
        first_not_found = first_not_found or result

    if searcher:
        queries = [
            f'"{edrpou}" site:pat.ua',
            f'"{edrpou}" site:prat.ua',
            f'"{edrpou}" "prat.ua"',
        ]
        if context.get("company_name"):
            queries.append(f'"{edrpou}" "{context["company_name"]}"')
        for query in queries:
            for url in searcher(query)[:5]:
                fallback = fetch_first_available_prat_profile(edrpou, url, context, fetcher)
                if fallback["status"] == "found":
                    fallback["fallback_used"] = True
                    return fallback

    return first_not_found or empty_result(SOURCE, status="not_found", error="not_found")


def fetch_prat_registry_url(edrpou: str, url: str, context: dict, fetcher: Callable[[str], str]) -> dict:
    try:
        html = fetcher(url)
    except Exception as exc:
        return source_error_result(SOURCE, url, exc)

    text = visible_text(html)
    if is_blocked_page(html, text):
        return empty_result(SOURCE, status="blocked", raw_url=url, error="blocked")
    if edrpou not in text:
        return empty_result(
            SOURCE,
            status="not_found",
            raw_url=url,
            error="not_found",
            evidence=[f"PRAT/PAT: за ЄДРПОУ {edrpou} сайт або запис у реєстрі акціонерних товариств не знайдено."],
        )

    subdomain = extract_prat_subdomain(html, edrpou)
    if not subdomain:
        return build_found_result(
            SOURCE,
            edrpou=edrpou,
            html=html,
            raw_url=url,
            context=context,
            default_evidence=["Знайдено запис у реєстрі PRAT/PAT."],
        )

    profile = fetch_first_available_prat_profile(edrpou, subdomain, context, fetcher)
    if profile["status"] == "found":
        return profile
    if profile["status"] in {"unavailable", "blocked", "parse_error", "not_found"}:
        return {
            **build_found_result(
                SOURCE,
                edrpou=edrpou,
                html=html,
                raw_url=url,
                context=context,
                website_override=subdomain,
                default_evidence=[
                    "Знайдено запис у реєстрі PRAT/PAT.",
                    "PRAT/PAT: знайдено запис у реєстрі, але сайт компанії не відкривається або недоступний.",
                ],
            ),
            "confidence": "medium",
        }
    return profile


def fetch_prat_profile_url(edrpou: str, url: str, context: dict, fetcher: Callable[[str], str]) -> dict:
    try:
        html = fetcher(url)
    except Exception as exc:
        return source_error_result(SOURCE, url, exc)
    return parse_prat_profile(html, edrpou, context, url)


def parse_prat_profile(html: str, edrpou: str, context: dict | None, raw_url: str) -> dict:
    text = visible_text(html)
    if is_blocked_page(html, text):
        return empty_result(SOURCE, status="blocked", raw_url=raw_url, error="blocked")
    if not text:
        return empty_result(SOURCE, status="not_found", raw_url=raw_url, error="not_found")

    result = build_found_result(
        SOURCE,
        edrpou=edrpou,
        html=html,
        raw_url=raw_url,
        context=context or {},
        website_override=raw_url if raw_url and (".prat.ua" in raw_url or ".pat.ua" in raw_url) else None,
        default_evidence=["Сайт знайдено у реєстрі PRAT/PAT."],
    )
    if document_has_edrpou(html, edrpou) and result["confidence"] == "medium":
        result["confidence"] = "high"
    if not document_has_edrpou(html, edrpou) and result["confidence"] in {"medium", "high"}:
        result["confidence"] = "low"
    result.setdefault("fallback_used", False)
    return result


def fetch_first_available_prat_profile(
    edrpou: str,
    url: str,
    context: dict,
    fetcher: Callable[[str], str],
) -> dict:
    last_result: dict | None = None
    first_found: dict | None = None
    for profile_url in extract_prat_profile_urls(url):
        result = fetch_prat_profile_url(edrpou, profile_url, context, fetcher)
        if result["status"] == "found":
            if profile_url.startswith("https://"):
                return result
            first_found = first_found or result
            continue
        last_result = result
    return first_found or last_result or empty_result(SOURCE, status="not_found", raw_url=url, error="not_found")


def extract_prat_profile_urls(url: str) -> list[str]:
    host = extract_prat_host(url)
    if not host:
        return []
    return [f"http://{host}", f"https://{host}"]


def extract_prat_host(url: str) -> str | None:
    for candidate in candidate_urls_from_search_result(url):
        parsed = urlparse(candidate if "://" in candidate else f"http://{candidate}")
        host = (parsed.hostname or "").lower()
        if re.fullmatch(r"[\w.-]+\.(?:prat|pat)\.ua", host):
            return host
    return None


def candidate_urls_from_search_result(url: str) -> list[str]:
    decoded = unquote(url or "")
    candidates = [decoded]
    parsed = urlparse(decoded if "://" in decoded else f"http://{decoded}")
    for values in parse_qs(parsed.query).values():
        candidates.extend(unquote(value) for value in values)
    candidates.extend(re.findall(r"https?://[\w.-]+\.(?:prat|pat)\.ua", decoded, flags=re.IGNORECASE))
    candidates.extend(re.findall(r"[\w.-]+\.(?:prat|pat)\.ua", decoded, flags=re.IGNORECASE))
    return candidates


def extract_prat_subdomain(html: str, edrpou: str | None = None) -> str | None:
    if edrpou:
        for match in re.finditer(re.escape(edrpou), html or ""):
            start = html.rfind('<div class="reestr_item"', 0, match.start())
            if start == -1:
                continue
            end = html.find('<div style="clear: both;"></div>', match.end())
            if end == -1:
                end = min(len(html), match.end() + 1200)
            row_html = html[start:end]
            row_url = first_prat_url(row_html)
            if row_url:
                return row_url

    matches = re.findall(r"https?://[\w.-]+\.(?:prat|pat)\.ua", html or "", flags=re.IGNORECASE)
    if matches:
        return matches[0]
    href_match = re.search(r"href=[\"']([^\"']+\.(?:prat|pat)\.ua/?)[\"']", html or "", flags=re.IGNORECASE)
    if not href_match:
        return None
    url = href_match.group(1)
    return url if url.startswith(("http://", "https://")) else f"http://{url.lstrip('/')}"


def first_prat_url(html: str) -> str | None:
    matches = re.findall(r"https?://[\w.-]+\.(?:prat|pat)\.ua", html or "", flags=re.IGNORECASE)
    if matches:
        return matches[0]
    href_match = re.search(r"href=[\"']([^\"']+\.(?:prat|pat)\.ua/?)[\"']", html or "", flags=re.IGNORECASE)
    if not href_match:
        return None
    url = href_match.group(1)
    return url if url.startswith(("http://", "https://")) else f"http://{url.lstrip('/')}"
