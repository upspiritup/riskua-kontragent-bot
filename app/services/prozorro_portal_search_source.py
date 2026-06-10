from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models.company_lookup import ProzorroSearchSummary
from app.services.prozorro_api_source import build_tender_detail_url, normalize_tender_detail_for_edrpou


PROZORRO_PORTAL_API_URL = "https://prozorro.gov.ua/api/search/tenders"
PROZORRO_PORTAL_SEARCH_URL = "https://prozorro.gov.ua/uk/search/tender"
PROZORRO_PORTAL_TENDER_SUMMARY_URL = "https://prozorro.gov.ua/api/tenders"
HTTP_TIMEOUT_SECONDS = 8.0
FetchJson = Callable[[str], dict[str, Any] | Awaitable[dict[str, Any]]]
PROZORRO_SEARCH_MARKER_GROUPS: dict[str, tuple[str, ...]] = {
    "disqualification": (
        "дискваліфіковано",
        "дискваліфікац",
        "відхилено пропозицію",
        "відхилен",
    ),
    "qualification_mismatch": (
        "не відповідає кваліфікаційним критеріям",
        "кваліфікаційним критеріям",
        "невідповідність кваліфікаційним",
    ),
    "documents_issue": (
        "не надано документи",
        "ненадання документ",
        "невідповідність документів",
        "невідповідні документи",
    ),
    "technical_mismatch": (
        "невідповідність технічним вимогам",
        "не відповідає технічним вимогам",
    ),
    "termination": (
        "договір розірвано",
        "розірвання з ініціативи постачальника",
        "розірван",
        "terminated",
    ),
    "nonperformance": (
        "неможливість виконання договору",
        "невиконання зобов’язань",
        "невиконання зобов'язань",
        "невиконання договору",
    ),
    "complaint": (
        "скарги до амку",
        "скарга до амку",
        "вимоги/звернення",
        "вимога",
        "звернення",
        "оскарження результатів",
        "скарги на дискримінаційні умови",
        "скарг",
        "complaint",
    ),
    "monitoring": (
        "моніторинг",
        "monitoring",
    ),
    "contract_change": (
        "зміна ціни",
        "зміна строків",
        "продовження договору",
        "збільшення суми",
        "ціна суттєво зросла після перемоги",
        "строки часто продовжувалися",
        "договір багато разів змінювався",
        "зміни до договору",
        "amendment",
    ),
}


async def fetch_prozorro_search_summary_by_edrpou(
    edrpou: str,
    *,
    max_items: int = 50,
    timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
    fetch_json: FetchJson | None = None,
) -> ProzorroSearchSummary | None:
    logger = logging.getLogger(__name__)
    logger.info("Prozorro portal search start edrpou=%s", edrpou)
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    try:
        payloads = await fetch_search_pages(
            edrpou,
            max_items=max_items,
            deadline=deadline,
            fetch_json=fetch_json,
        )
    except Exception as exc:
        logger.info("Prozorro portal search error edrpou=%s error=%s", edrpou, exc)
        raise

    total_count = first_total_count(payloads)
    items = search_items_from_payloads(payloads, max_items=max_items)
    checked_items = [normalize_search_item(item) for item in items[: max(0, max_items)]]
    checked_items, detail_checked_count, confirmed_count, matched_procurements = await enrich_items_with_detail_checks(
        edrpou,
        checked_items,
        deadline=deadline,
        fetch_json=fetch_json,
        logger=logger,
    )
    logger.info(
        "Prozorro portal search done edrpou=%s total=%s checked=%s",
        edrpou,
        total_count,
        len(checked_items),
    )
    if not total_count and not checked_items:
        return None
    return ProzorroSearchSummary(
        total_count=total_count,
        checked_count=len(checked_items),
        detail_checked_count=detail_checked_count,
        confirmed_participation_count=confirmed_count,
        **count_confirmed_roles(checked_items),
        source_url=build_portal_search_page_url(edrpou),
        items=checked_items,
        matched_procurements=matched_procurements,
    )


async def fetch_search_pages(
    edrpou: str,
    *,
    max_items: int,
    deadline: float,
    fetch_json: FetchJson | None,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    collected_count = 0
    page = 1
    per_page = max(1, max_items)
    while collected_count < max_items and remaining_seconds(deadline) > 0:
        payload = await fetch_json_with_timeout(
            fetch_json,
            build_portal_search_api_url(edrpou, page=page, per_page=per_page),
            max(0.1, remaining_seconds(deadline)),
            method="POST",
        )
        if not isinstance(payload, dict):
            break
        payloads.append(payload)
        raw_items = payload.get("data")
        page_items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
        collected_count += len(page_items)
        total_count = int_or_none(payload.get("total"))
        if not page_items or (total_count is not None and collected_count >= total_count):
            break
        page += 1
    return payloads


def first_total_count(payloads: list[dict[str, Any]]) -> int | None:
    for payload in payloads:
        total_count = int_or_none(payload.get("total"))
        if total_count is not None:
            return total_count
    return None


def search_items_from_payloads(payloads: list[dict[str, Any]], *, max_items: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for payload in payloads:
        raw_items = payload.get("data")
        if isinstance(raw_items, list):
            items.extend(item for item in raw_items if isinstance(item, dict))
        if len(items) >= max_items:
            break
    return items[:max_items]


def build_portal_search_api_url(edrpou: str, *, page: int = 1, per_page: int | None = None) -> str:
    query: dict[str, Any] = {"text": edrpou, "page": page}
    if per_page is not None and per_page > 0:
        query["per_page"] = per_page
    return f"{PROZORRO_PORTAL_API_URL}?{urlencode(query)}"


def build_portal_search_page_url(edrpou: str) -> str:
    return f"{PROZORRO_PORTAL_SEARCH_URL}?{urlencode({'text': edrpou})}"


def build_portal_tender_summary_url(tender_id: str) -> str:
    return f"{PROZORRO_PORTAL_TENDER_SUMMARY_URL}/{tender_id}/summary"


async def fetch_json_with_timeout(
    fetch_json: FetchJson | None,
    url: str,
    timeout_seconds: float,
    *,
    method: str = "GET",
) -> dict[str, Any]:
    if fetch_json is None:
        return await asyncio.to_thread(fetch_json_url_sync, url, timeout_seconds, method)

    value = fetch_json(url)
    if inspect.isawaitable(value):
        return await asyncio.wait_for(value, timeout=max(0.1, timeout_seconds))
    return value


async def enrich_items_with_detail_checks(
    edrpou: str,
    items: list[dict[str, Any]],
    *,
    deadline: float,
    fetch_json: FetchJson | None,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], int, int, list[Any]]:
    detail_checked_count = 0
    confirmed_count = 0
    matched_procurements = []

    for item in items:
        if remaining_seconds(deadline) <= 0:
            break
        tender_id = text_or_none(item.get("tenderID"))
        if not tender_id:
            continue
        try:
            summary = await fetch_json_with_timeout(
                fetch_json,
                build_portal_tender_summary_url(tender_id),
                max(0.1, min(remaining_seconds(deadline), HTTP_TIMEOUT_SECONDS)),
            )
            detail_id = text_or_none(summary.get("id")) if isinstance(summary, dict) else None
            if not detail_id:
                continue
            detail_payload = await fetch_json_with_timeout(
                fetch_json,
                build_tender_detail_url(detail_id),
                max(0.1, min(remaining_seconds(deadline), HTTP_TIMEOUT_SECONDS)),
            )
            detail = detail_payload.get("data") if isinstance(detail_payload, dict) else None
            if not isinstance(detail, dict):
                continue
            detail_checked_count += 1
            item["risk_marker_codes"] = merge_marker_codes(
                item.get("risk_marker_codes"),
                detect_prozorro_search_marker_codes(detail),
            )
            record, roles = normalize_tender_detail_for_edrpou(detail, edrpou)
            item["participation_confirmed"] = bool(roles)
            item["confirmed_roles"] = sorted(roles)
            if roles:
                confirmed_count += 1
                if record is not None:
                    matched_procurements.append(record)
        except Exception as exc:
            logger.info("Prozorro portal detail check skipped tender_id=%s error=%s", tender_id, exc)
            continue

    return items, detail_checked_count, confirmed_count, matched_procurements


def count_confirmed_roles(items: list[dict[str, Any]]) -> dict[str, int]:
    counters = {
        "buyer_count": 0,
        "participant_count": 0,
        "winner_count": 0,
        "supplier_contract_count": 0,
    }
    for item in items:
        roles = item.get("confirmed_roles")
        if not isinstance(roles, list):
            continue
        role_set = {str(role) for role in roles}
        if "buyer" in role_set:
            counters["buyer_count"] += 1
        if "participant" in role_set:
            counters["participant_count"] += 1
        if "winner" in role_set:
            counters["winner_count"] += 1
        if "contract_supplier" in role_set:
            counters["supplier_contract_count"] += 1
    return counters


def remaining_seconds(deadline: float) -> float:
    return deadline - time.monotonic()


def fetch_json_url_sync(
    url: str,
    timeout_seconds: float = HTTP_TIMEOUT_SECONDS,
    method: str = "GET",
) -> dict[str, Any]:
    data = b"" if method.upper() == "POST" else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


def normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    procuring_entity = item.get("procuringEntity")
    buyer = procuring_entity if isinstance(procuring_entity, dict) else {}
    identifier = buyer.get("identifier") if isinstance(buyer.get("identifier"), dict) else {}
    value = item.get("value") if isinstance(item.get("value"), dict) else {}
    normalized = {
        "tenderID": text_or_none(item.get("tenderID")),
        "title": text_or_none(item.get("title")),
        "status": text_or_none(item.get("status")),
        "buyer_name": text_or_none(buyer.get("name") or identifier.get("legalName")),
        "buyer_edrpou": text_or_none(identifier.get("id")),
        "expected_value_uah": float_or_none(value.get("amount")),
    }
    normalized["risk_marker_codes"] = detect_prozorro_search_marker_codes(item)
    return normalized


def merge_marker_codes(first: Any, second: list[str]) -> list[str]:
    codes: set[str] = set()
    if isinstance(first, list):
        codes.update(str(item) for item in first if item)
    codes.update(second)
    return sorted(codes)


def detect_prozorro_search_marker_codes(value: Any) -> list[str]:
    text = collect_text(value).casefold()
    if not text:
        return []
    return [
        code
        for code, markers in PROZORRO_SEARCH_MARKER_GROUPS.items()
        if any(marker.casefold() in text for marker in markers)
    ]


def collect_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str | int | float | bool):
        return str(value)
    if isinstance(value, dict):
        return " ".join(collect_text(item) for item in value.values())
    if isinstance(value, list | tuple):
        return " ".join(collect_text(item) for item in value)
    return ""


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
