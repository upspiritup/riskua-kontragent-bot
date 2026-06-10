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

from app.models.company_lookup import ProzorroProcurement


BASE_PROZORRO_API_URL = "https://public.api.openprocurement.org/api/2.5"
HTTP_TIMEOUT_SECONDS = 8.0
FetchJson = Callable[[str], dict[str, Any] | Awaitable[dict[str, Any]]]


async def fetch_recent_prozorro_procurements_by_edrpou(
    edrpou: str,
    max_pages: int = 3,
    limit: int = 100,
    timeout_seconds: float = 60.0,
    *,
    fetch_json: FetchJson | None = None,
) -> list[ProzorroProcurement]:
    logger = logging.getLogger(__name__)
    logger.info("Prozorro live source start edrpou=%s", edrpou)
    records: list[ProzorroProcurement] = []
    offset: str | None = None
    deadline = time.monotonic() + max(0.0, timeout_seconds)

    try:
        for page_number in range(1, max(0, max_pages) + 1):
            if search_time_exhausted(deadline):
                log_live_time_budget_reached(logger, edrpou, records)
                break
            feed_url = build_tenders_feed_url(limit=limit, offset=offset)
            feed_payload = await fetch_json_with_deadline(fetch_json, feed_url, deadline)
            tenders = feed_payload.get("data") if isinstance(feed_payload, dict) else []
            if not isinstance(tenders, list):
                tenders = []
            logger.info("Prozorro feed page fetched page=%s count=%s", page_number, len(tenders))

            for tender_ref in tenders:
                if search_time_exhausted(deadline):
                    log_live_time_budget_reached(logger, edrpou, records)
                    return records
                tender_id = tender_ref.get("id") if isinstance(tender_ref, dict) else None
                if not tender_id:
                    continue
                detail_url = build_tender_detail_url(str(tender_id))
                try:
                    detail_payload = await fetch_json_with_deadline(fetch_json, detail_url, deadline)
                except Exception as exc:
                    if search_time_exhausted(deadline):
                        log_live_time_budget_reached(logger, edrpou, records)
                        return records
                    logger.info("Prozorro tender detail fetch failed tender_id=%s error=%s", tender_id, exc)
                    continue
                logger.info("Prozorro tender detail fetched tender_id=%s", tender_id)
                detail = detail_payload.get("data") if isinstance(detail_payload, dict) else None
                if not isinstance(detail, dict):
                    continue
                record, roles = normalize_tender_detail_for_edrpou(detail, edrpou)
                if record is None:
                    continue
                logger.info(
                    "Prozorro tender matched edrpou=%s tender_id=%s roles=%s",
                    edrpou,
                    record.procurement_id or tender_id,
                    ",".join(sorted(roles)),
                )
                records.append(record)

            next_page = feed_payload.get("next_page") if isinstance(feed_payload, dict) else None
            next_offset = next_page.get("offset") if isinstance(next_page, dict) else None
            if not next_offset or next_offset == offset:
                break
            offset = str(next_offset)
    except TimeoutError:
        log_live_time_budget_reached(logger, edrpou, records)
        return records
    except Exception as exc:
        logger.info("Prozorro live source error edrpou=%s error=%s", edrpou, exc)
        raise

    logger.info("Prozorro live source done edrpou=%s found=%s", edrpou, len(records))
    return records


def build_tenders_feed_url(*, limit: int, offset: str | None = None) -> str:
    query: dict[str, str | int] = {"limit": limit}
    if offset:
        query["offset"] = offset
    return f"{BASE_PROZORRO_API_URL}/tenders?{urlencode(query)}"


def build_tender_detail_url(tender_id: str) -> str:
    return f"{BASE_PROZORRO_API_URL}/tenders/{tender_id}"


async def fetch_json_url(url: str) -> dict[str, Any]:
    return await asyncio.to_thread(fetch_json_url_sync, url, HTTP_TIMEOUT_SECONDS)


def fetch_json_url_sync(url: str, timeout_seconds: float = HTTP_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "RiskUA Bot MVP/0.1",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


async def fetch_json_with_deadline(
    fetch_json: FetchJson | None,
    url: str,
    deadline: float,
) -> dict[str, Any]:
    remaining = remaining_search_seconds(deadline)
    if remaining <= 0:
        raise TimeoutError("Prozorro live search time budget exhausted")
    if fetch_json is None:
        return await asyncio.to_thread(fetch_json_url_sync, url, min(HTTP_TIMEOUT_SECONDS, remaining))

    value = fetch_json(url)
    if inspect.isawaitable(value):
        try:
            return await asyncio.wait_for(value, timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Prozorro live search time budget exhausted") from exc
    return value


def remaining_search_seconds(deadline: float) -> float:
    return deadline - time.monotonic()


def search_time_exhausted(deadline: float) -> bool:
    return remaining_search_seconds(deadline) <= 0


def log_live_time_budget_reached(
    logger: logging.Logger,
    edrpou: str,
    records: list[ProzorroProcurement],
) -> None:
    logger.info("Prozorro live source time budget reached edrpou=%s found=%s", edrpou, len(records))


def normalize_tender_detail_for_edrpou(
    tender: dict[str, Any],
    edrpou: str,
) -> tuple[ProzorroProcurement | None, set[str]]:
    normalized_edrpou = normalize_identifier(edrpou)
    roles = tender_roles_for_edrpou(tender, normalized_edrpou)
    if not roles:
        return None, set()

    matching_bid = first_matching_bid(tender, normalized_edrpou)
    matching_awards = matching_supplier_items(tender.get("awards"), normalized_edrpou)
    matching_contracts = matching_supplier_items(tender.get("contracts"), normalized_edrpou)
    active_award = first_item_with_status(matching_awards, {"active"})
    disqualified_award = first_item_with_status(matching_awards, {"unsuccessful", "cancelled"})
    matching_contract = matching_contracts[0] if matching_contracts else None
    terminated_contract = first_item_with_status(matching_contracts, {"terminated", "cancelled"})

    contract_value = money_amount(matching_contract.get("value")) if matching_contract else None
    award_value = money_amount(active_award.get("value")) if active_award else None
    amount_change = amount_change_between(award_value, contract_value)

    return (
        ProzorroProcurement(
            procurement_id=first_text(tender, "tenderID", "id"),
            url=build_tender_detail_url(str(tender.get("id") or "")) if tender.get("id") else None,
            title=first_text(tender, "title"),
            cpv_code=classification_value(tender, "id"),
            cpv_name=classification_value(tender, "description"),
            procedure_type=first_text(tender, "procurementMethodType", "procurementMethod"),
            status=first_text(tender, "status"),
            expected_value_uah=money_amount(tender.get("value")),
            bid_value_uah=money_amount(matching_bid.get("value")) if matching_bid else None,
            contract_value_uah=contract_value,
            buyer_name=nested_text(tender.get("procuringEntity"), "name"),
            buyer_edrpou=nested_identifier(tender.get("procuringEntity")),
            participants_count=participants_count(tender),
            participated=bool(roles.intersection({"participant", "winner", "contract_supplier"})),
            won=active_award is not None,
            disqualified=disqualified_award is not None,
            disqualification_reason=disqualification_reason(disqualified_award),
            has_contract=matching_contract is not None,
            contract_completed=matching_contract is not None
            and normalize_status(matching_contract.get("status")) in {"complete", "completed"},
            contract_terminated=terminated_contract is not None,
            termination_reason=termination_reason(terminated_contract),
            complaints_count=count_items(tender.get("complaints")),
            amendments_count=count_contract_changes(matching_contracts),
            contract_amount_change_uah=amount_change[0],
            contract_amount_change_percent=amount_change[1],
            date=date_part(first_text(tender, "dateModified", "date")),
            award_date=date_part(first_text(active_award or {}, "date")),
            contract_date=date_part(first_text(matching_contract or {}, "dateSigned", "date")),
        ),
        roles,
    )


def tender_roles_for_edrpou(tender: dict[str, Any], edrpou: str) -> set[str]:
    roles: set[str] = set()
    if nested_identifier(tender.get("procuringEntity")) == edrpou:
        roles.add("buyer")
    if first_matching_bid(tender, edrpou):
        roles.add("participant")
    if matching_supplier_items(tender.get("awards"), edrpou):
        roles.add("winner")
    if matching_supplier_items(tender.get("contracts"), edrpou):
        roles.add("contract_supplier")
    return roles


def first_matching_bid(tender: dict[str, Any], edrpou: str) -> dict[str, Any] | None:
    for bid in as_dicts(tender.get("bids")):
        if any(nested_identifier(tenderer) == edrpou for tenderer in as_dicts(bid.get("tenderers"))):
            return bid
    return None


def matching_supplier_items(items: Any, edrpou: str) -> list[dict[str, Any]]:
    return [
        item
        for item in as_dicts(items)
        if any(nested_identifier(supplier) == edrpou for supplier in as_dicts(item.get("suppliers")))
    ]


def first_item_with_status(items: list[dict[str, Any]], statuses: set[str]) -> dict[str, Any] | None:
    return next((item for item in items if normalize_status(item.get("status")) in statuses), None)


def participants_count(tender: dict[str, Any]) -> int:
    participants: set[str] = set()
    for bid in as_dicts(tender.get("bids")):
        for tenderer in as_dicts(bid.get("tenderers")):
            identifier = nested_identifier(tenderer)
            if identifier:
                participants.add(identifier)
    return len(participants)


def classification_value(tender: dict[str, Any], key: str) -> str | None:
    for item in as_dicts(tender.get("items")):
        classification = item.get("classification")
        if isinstance(classification, dict):
            value = classification.get(key)
            if value:
                return str(value)
    return None


def money_amount(value: Any) -> float | None:
    if isinstance(value, dict):
        currency = str(value.get("currency") or "UAH").upper()
        if currency != "UAH":
            return None
        value = value.get("amount")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def amount_change_between(initial: float | None, final: float | None) -> tuple[float | None, float | None]:
    if initial is None or final is None or initial == 0:
        return None, None
    change = final - initial
    if change == 0:
        return None, None
    return change, round(change / initial * 100, 2)


def disqualification_reason(award: dict[str, Any] | None) -> str | None:
    if not award:
        return None
    return first_text(award, "description", "rejectionReason", "reason", "complaintDescription")


def termination_reason(contract: dict[str, Any] | None) -> str | None:
    if not contract:
        return None
    return first_text(contract, "terminationDetails", "description", "reason")


def count_contract_changes(contracts: list[dict[str, Any]]) -> int:
    return sum(count_items(contract.get("changes")) for contract in contracts)


def count_items(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def as_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def nested_identifier(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    identifier = value.get("identifier")
    if not isinstance(identifier, dict):
        return None
    return normalize_identifier(identifier.get("id"))


def nested_text(value: Any, key: str) -> str | None:
    if not isinstance(value, dict):
        return None
    text = value.get(key)
    return str(text).strip() if text else None


def first_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value).strip()
    return None


def date_part(value: str | None) -> str | None:
    if not value:
        return None
    return value[:10]


def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_identifier(value: Any) -> str:
    return str(value or "").strip()
